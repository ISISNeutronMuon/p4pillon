# Serializing handler dispatch: a tutorial on the per-PV and per-handler locks

This document explains a concurrency fix in p4pillon's `SharedPV` handler
machinery. It assumes you are comfortable with Python — classes, inheritance,
exceptions — but **not** with Python's concurrency models (threads, locks,
event loops). We build up just enough of that background to understand what
was broken and why the fix works.

Read it top to bottom the first time; later you can jump straight to
[The fix](#4-the-fix).

---

## 1. Background you need first

### 1.1 What a `SharedPV` and a "handler" are

A `SharedPV` is a single networked value that a server publishes — a
temperature, a motor position, a status string. Clients can **read** it,
**write** to it (a "put"), and **subscribe** to changes. The server can also
change it locally by calling `post(new_value)`.

A **handler** is an object you attach to a `SharedPV` to run your own code
when things happen to it. It has methods with fixed names that p4pillon calls
for you:

| Handler method     | Called when…                                        |
| ------------------ | --------------------------------------------------- |
| `put`              | a client writes to the PV                            |
| `rpc`              | a client makes a remote procedure call              |
| `onFirstConnect`   | the first client subscribes                          |
| `onLastDisconnect` | the last client unsubscribes                         |
| `open`             | the PV is (re)opened with an initial value          |
| `post`             | the value is updated locally via `pv.post(...)`     |
| `close`            | the PV is closed                                     |

Your handler methods often keep **state** — a running total, a cache of valid
choices, the previous value. That state is just instance attributes on the
handler object. Keep that word *state* in mind: shared mutable state is the
thing this whole document is about protecting.

### 1.2 What "concurrency" means here

Concurrency means **more than one piece of your code is in progress at the
same time**. That doesn't require multiple CPU cores; it only requires that
execution can *switch* from one piece of code to another before the first one
has finished. Two mechanisms in this codebase cause that switching, and they
are different enough that we treat them separately for the whole document.

#### Mechanism A: OS threads

A **thread** is an independent stream of execution inside your program. If you
start two threads, the operating system runs them *concurrently* — it rapidly
switches back and forth between them (and on multiple cores, genuinely runs
them at the same instant).

Crucially, **the switch can happen between any two lines of your code**, even
in the middle of a single statement. You do not control when. This is the
source of most of the trouble below.

```python
import threading

def worker():
    for _ in range(1000):
        print("hi")

t = threading.Thread(target=worker)
t.start()   # worker() now runs concurrently with the code after this line
```

> **"But doesn't Python's GIL make threads safe?"** A common half-truth. The
> Global Interpreter Lock ensures a single *bytecode operation* is atomic, so
> the interpreter itself never corrupts. But your logic almost never lives in
> one bytecode op. `self.total = self.total + 1` is *read total*, *add one*,
> *store total* — three ops, and a thread switch can land between them. The
> GIL does not save you. Assume it doesn't and you'll write correct code.

#### Mechanism B: the asyncio event loop

`asyncio` is Python's other concurrency model, and it works completely
differently. Instead of the OS pre-empting you at unpredictable points, you
write `async def` functions (**coroutines**) that voluntarily pause at `await`
expressions. A single **event loop**, running on **one thread**, runs one
coroutine until it hits an `await`, then switches to another.

Two consequences matter for us:

1. **Switches happen only at `await`.** Code between two `await`s runs to
   completion without interruption *from other coroutines*. This is a much
   weaker form of concurrency than threads — and much easier to reason about.
2. **The loop lives on exactly one thread.** Anything that touches the loop
   must do so *from that thread*. Call loop machinery from another thread and
   you get undefined behavior or crashes. This "you must be on the loop's
   thread" rule is called **thread affinity**, and the fix leans on it.

### 1.3 The specific hazard: a race condition

A **race condition** is a bug where the result depends on the unpredictable
timing of concurrent execution. The classic example is the lost update:

```python
class Counter:
    def __init__(self):
        self.total = 0
    def increment(self):
        self.total = self.total + 1   # read, +1, store — NOT atomic
```

Run `increment()` from two threads a thousand times each and you will **not**
reliably get 2000. Both threads can read `total` as (say) 41, both compute 42,
both store 42 — one increment vanished. The reads and writes *interleaved*.

Now map that onto handlers. Two different things can run handler code on the
same handler object at the same time, stepping on its shared state exactly
like the counter. Section 3 shows precisely how. First we need the tool that
fixes it.

### 1.4 The tool: a lock

A **lock** (mutex) is an object with `acquire()` and `release()`. The rule the
OS enforces: **only one thread can hold the lock at a time.** A second thread
calling `acquire()` while the first holds it *blocks* — waits — until the
first calls `release()`.

Wrap the fragile region and the interleaving is gone:

```python
lock = threading.Lock()

def increment(self):
    with lock:                 # acquire on enter, release on exit
        self.total = self.total + 1
```

The `with lock:` block is a **critical section**: at most one thread is inside
it at any moment. The read-add-store can no longer interleave, so no update is
lost. The cost is that threads take turns — a thread waiting for the lock does
nothing useful until it's free.

#### The re-entrant lock (`RLock`)

A plain `Lock` has a trap: if a thread that already holds it tries to
`acquire()` it *again*, that thread blocks forever waiting for *itself*. This
is **self-deadlock**, and it happens naturally when a locked method calls
another locked method.

An **`RLock`** ("re-entrant lock") fixes this: the *same* thread may acquire it
any number of times (it just counts, releasing for real on the last exit),
while *other* threads are still kept out. Whenever a locked operation might, in
the course of its work, trigger another locked operation on the same object,
you want an `RLock`. Both locks in this fix are `RLock`s for exactly this
reason — you'll see the re-entry paths in Section 4.

#### The new hazard locks introduce: deadlock

Locks trade one problem for a subtler one. **Deadlock** is when two threads
each wait for a lock the other holds, so neither can ever proceed:

```
Thread 1 holds lock A, wants lock B
Thread 2 holds lock B, wants lock A     ← both stuck forever
```

The standard defense is **lock ordering**: pick a global order for your locks
and make *every* thread acquire them in that order. If nobody ever holds B
while reaching for A, the cycle above can't form. The fix defines exactly such
an ordering, and Section 5 spells it out.

---

## 2. How p4pillon dispatches handlers — the two regimes

Here is the fact at the heart of the bug. p4pillon runs handler methods in
**two different ways**, and they can run **at the same time** on the same
handler.

### Regime 1: put / rpc / connect — run on an *executor*

When a *client* triggers something (`put`, `rpc`, `onFirstConnect`,
`onLastDisconnect`), p4p does not run your handler on the network thread.
It hands the work to an **executor** via an internal method called `_exec()`:

- **thread flavor** (`p4pillon.server.thread.SharedPV`): the executor is a
  per-PV **work queue** served by a single dedicated worker thread. Every
  put/rpc for one PV runs on that one worker thread, one at a time.
- **asyncio flavor** (`p4pillon.server.asyncio.SharedPV`): the executor is the
  **event loop**. `_exec()` schedules the handler onto the loop thread.

So these callbacks are already nicely serialized *among themselves* for a
single PV. Good.

### Regime 2: open / post / close — run on the *caller's* thread

The `open`, `post`, and `close` hooks are different. They are p4pillon
additions (implemented by p4pillon itself, not the underlying p4p), and they run
**synchronously on whatever thread
called `pv.open()` / `pv.post()` / `pv.close()`**. They are *not* pushed onto
the executor.

Why not? Because these hooks must *modify the value in place before it is
stored* in the C extension. `post()` wraps the value, lets the handler adjust
it, and only then hands it to the C layer. That has to happen as one unbroken
sequence on the calling thread — you can't defer it onto a queue and still
return the stored value to the caller synchronously.

This asymmetry is not an accident and can't be removed by "just pushing post
onto the executor too": the underlying pvxs/p4p C library has **no callback
slot** for open/post/close at all (it has slots only for put/rpc/connect), so
these hooks can *only* live in the Python layer, on the caller's thread. That
makes the two-regime split permanent, and something we must make safe rather
than eliminate.

### The collision

Put the two regimes together:

- Regime 1 runs `handler.put(...)` on the **worker thread** (or loop).
- Regime 2 runs `handler.post(...)` on **whatever thread called `pv.post()`**.

If some *other* thread calls `pv.post()` while the worker thread is running
`handler.put()`, **both regimes execute handler code on the same handler
object at the same time** — the exact race-condition setup from Section 1.3.

Who calls `pv.post()` from another thread? Plenty of real code:

- a scan loop updating values on its own timer thread,
- one PV's handler updating a *different* PV (e.g. p4pillon's `set_desc_record`
  and `DescMirrorHandler`),
- any application background thread.

---

## 3. What was actually wrong before the fix

Let's make the abstract race concrete. Consider a handler that enforces "the
value only ever goes up" and remembers the last value it saw:

```python
class Ratchet:
    def __init__(self):
        self.last = 0.0
    def post(self, pv, value):
        if value < self.last:      # (A) read self.last
            value.value = self.last
        self.last = value.value    # (B) write self.last
```

Attach it to a PV. Now:

- the **worker thread** is inside `put()` handling a client write, which calls
  `pv.post(...)` and so runs `Ratchet.post` — it executes line (A);
- at that instant a **scan thread** calls `pv.post(...)` too, running a second
  `Ratchet.post` that also executes (A) and (B).

Both readers saw the same `self.last`; one of the two writes at (B) is lost,
and the "only goes up" guarantee can silently break. Nothing crashes. You just
get an occasional wrong value under load — the worst kind of bug to chase.

Three distinct defects lived in the pre-fix code:

1. **Corrupted handler state.** Exactly the `Ratchet` story above — any handler
   with mutable state (running totals, `NTEnum`'s cached choice list,
   p4pillon's `CompositeHandler` rule bookkeeping) could be interleaved and
   corrupted.

2. **Inverted stores ("lost update" on the value itself).** Even if a handler
   were stateless, two threads doing read-modify-write —
   `pv.post(pv.current() + 1)` — could both read the same current value and
   both store the same result, losing an increment. The value *itself* is
   shared state, not just the handler.

3. **A silent asyncio violation.** In the asyncio flavor, calling `pv.post()`
   from a non-loop thread doesn't just race — it pokes the C extension and the
   event loop from the wrong thread entirely, which is *never* legal under the
   thread-affinity rule (Section 1.2). Before the fix this was simply allowed
   to happen, with undefined results.

The pre-fix code had **no lock and no thread-affinity check anywhere** on this
path. The two regimes ran free. Here is the old `post()` from
`HandlerHooksMixin` — read it and notice there is *nothing* stopping a second
thread from running the identical sequence at the same instant:

```python
# BEFORE THE FIX — no lock; any thread may run this concurrently with put/rpc
def post(self, value, **kwargs):
    v = self._wrap(value, **kwargs)          # wrap the value

    post_fn = getattr(self._handler, "post", None)
    if post_fn is not None:
        post_fn(self, v)                     # run the handler hook (mutable state!)

    _RawSharedPV.post(self, v)               # store into the C extension
```

Three unprotected steps — wrap, run handler, store — and any of them can
interleave with the *same* three steps running on the worker thread for a
put/rpc, or with another foreign-thread `post()`. `open()` had the same shape,
and the thread flavor's `_exec()` pushed put/rpc handlers onto the worker with
no coordinating lock. Section 4 wraps exactly these sequences in a shared lock.

---

## 4. The fix

The fix is two complementary parts: the **per-PV dispatch lock** and the
**per-handler state lock**. The per-PV dispatch lock makes dispatch *for one
PV* safe; the per-handler state lock covers the one case the per-PV lock
structurally cannot. They are designed to be used together.

### The per-PV dispatch lock — one lock per PV, covering *both* regimes

The idea: give each `SharedPV` its own `RLock`, and make **both regimes take
that same lock**. If put (regime 1) and post (regime 2) must both hold the PV's
lock to run handler code, they can no longer overlap — one waits for the other.

**Step 1 — the lock, created before anything can use it.** In
`p4pillon/server/raw.py`, `HandlerHooksMixin` gains an `__init__` that creates
the lock *first*, then calls the base constructor:

```python
def __init__(self, *args, **kwargs):
    # The lock must exist before the base __init__ runs:
    # p4p.server.raw.SharedPV.__init__ calls self.open(initial) during
    # construction, and open() below acquires the lock.
    self._hook_lock = threading.RLock()
    super().__init__(*args, **kwargs)
```

The ordering comment is load-bearing: p4p's constructor calls `open()` on the
initial value *while still constructing the object*, and our `open()` now grabs
`self._hook_lock`. If the lock didn't exist yet, construction would crash. This
is a small but real gotcha of subclassing something whose `__init__` calls back
into overridable methods.

**Step 2 — regime 2 holds the lock.** `open()` and `post()` wrap their whole
body — wrap the value, run the handler hook, store into the C extension — in
`with self._hook_lock:`. Because the store happens *inside* the lock, the
read-modify-write defect (#2 above) is fixed too: current-then-post is now
atomic against any other locked post.

**Step 3 — regime 1 holds the *same* lock.** This is the clever half. The
thread flavor overrides `_exec()` — the method p4p uses to push put/rpc/connect
handlers onto the worker — so that the queued callable is wrapped to take the
lock before it runs (`p4pillon/server/thread.py`):

```python
def _exec(self, op, fn, *args):
    def locked(*call_args):
        with self._hook_lock:
            fn(*call_args)
    super()._exec(op, locked, *args)
```

One override covers *all four* executor-dispatched callbacks
(put/rpc/onFirstConnect/onLastDisconnect) in a single place. Now regime 1 and
regime 2 share one lock, and the race is gone.

**Why an `RLock` and not a `Lock`?** Because re-entry is normal here. The most
common handler pattern is a `put` handler that, after applying its rules, calls
`pv.post(op.value())`. That runs on the worker thread, which *already holds*
the lock (via the `_exec` wrapper), and `post()` then tries to take it *again*.
A plain `Lock` would self-deadlock instantly; the `RLock` lets the same thread
re-enter. (Section 1.4 has the mechanics.)

**One deadlock trap we had to design around: `close()`.** The thread flavor's
`close(sync=True)` blocks until the work queue drains — and the callables
draining out of that queue now try to take `self._hook_lock`. If `close()` held
the lock while waiting for them, it would wait forever for callables that are
waiting for it. So `close()` holds the lock *only around the close hook*, then
releases it before delegating to the flavor's blocking close:

```python
with self._hook_lock:
    close_fn = getattr(self._handler, "close", None)
    if close_fn is not None:
        close_fn(self)
# flavor close() (which may drain the queue) runs OUTSIDE the lock
return super().close(destroy, **kwargs)
```

### The per-PV dispatch lock in the asyncio flavor — affinity instead of a lock

The asyncio flavor deliberately does **not** use a cross-thread lock. Two
reasons: (1) a blocking lock acquired inside a loop callback would freeze the
*entire* event loop, and (2) a coroutine handler releases control at every
`await` anyway, so a lock wouldn't even guarantee what we want across awaits.

Instead it uses the thread-affinity rule the loop already gives us for free.
Everything that touches an asyncio PV runs on the loop thread, so if we simply
*require* `open()`/`post()` to be called on the loop thread, the loop itself
serializes them — no lock needed. `p4pillon/server/asyncio.py` enforces this:

```python
def _assert_loop_affinity(self, what):
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is not self.loop:
        raise RuntimeError(
            f"{what}() on an asyncio SharedPV must be called from its own "
            f"event loop; use post_deferred() from other threads"
        )
```

`open()` and `post()` call this first. Defect #3 (the silent violation) is now
a loud, immediate `RuntimeError` at the exact call site that's wrong.

But sometimes you genuinely *are* on another thread — a hardware polling
thread, say — and need to update the PV. For that there's `post_deferred()`:
it schedules the post onto the loop with `call_soon_threadsafe` and hands back
a `concurrent.futures.Future` so the caller can wait for completion and receive
any exception:

```python
def post_deferred(self, value, **kwargs):
    fut = concurrent.futures.Future()
    def _do():
        if not fut.set_running_or_notify_cancel():
            return
        try:
            self.post(value, **kwargs)     # runs on the loop thread now
        except BaseException as exc:
            fut.set_exception(exc)         # relay to the waiting caller
        else:
            fut.set_result(None)
    self.loop.call_soon_threadsafe(_do)
    return fut
```

**The user-facing rule** (worth memorizing): on the asyncio flavor, call
`post()` when your code is already on the PV's event loop (inside handlers,
coroutines, tasks, loop callbacks); call `post_deferred()` when you're on any
other thread. When in doubt, call `post()` — if it's wrong, the affinity check
tells you immediately and names the alternative. Never wait on the returned
Future from the loop thread itself: that blocks the very loop that must run the
scheduled work — an instant deadlock.

### The per-handler state lock — a lock inside `CompositeHandler`

The per-PV dispatch lock is, by definition, **per PV**. That leaves one gap:
what if *one handler object is shared by several PVs*? Each PV has its *own
distinct* `_hook_lock`, so PV-A running the shared handler and PV-B running the
same shared handler take *different* locks — the per-PV lock does nothing to
stop them overlapping.

`CompositeHandler` (p4pillon's handler that bundles several sub-handlers) is
exactly this kind of object, so it gets its **own** `RLock`, taken around every
dispatch method (`open`, `put`, `post`, `rpc`, connect/disconnect, `close`):

```python
def post(self, pv, value):
    with self._lock:
        for _name, handler in self.items():
            handler.post(pv, value)
```

Now even a handler shared across PVs serializes its own state access, because
the lock belongs to the *handler*, not to any one PV.

The per-handler state lock is a *complement*, not a replacement: it releases
before the C-extension store, so it can't fix the store-ordering defect on a
single PV — only the per-PV dispatch lock, held across the store, does that.
Each covers the other's blind spot. Together: the per-PV dispatch lock
serializes dispatch and stores per PV; the per-handler state lock serializes a
shared handler's state across PVs.

---

## 5. The one rule that keeps it deadlock-free

Two lock types now exist — the per-PV `_hook_lock` and the per-handler
`CompositeHandler._lock` — and Section 1.4 warned that multiple locks invite
deadlock. The defense is a fixed **lock ordering**:

> **The PV lock is always acquired before the handler lock. Never acquire them
> in the other order.**

This holds naturally, because handler methods are only ever *reached through*
PV dispatch: the PV takes `_hook_lock`, then calls into the handler, which
takes `_lock`. PV-then-handler, every time.

The one thing that would violate the order — and the single rule handler
authors must follow — is:

> **A handler must never call *another* PV's `open()`/`post()`/`close()` while
> holding its own handler lock.**

Doing so would take a *second* PV's `_hook_lock` while already holding a
handler lock (handler-then-PV), inverting the order and risking the classic
two-thread cycle. Posting back to the *same* PV is fine — both locks are
re-entrant, so the same thread just re-enters them.

(p4pillon's own `DescMirrorHandler` is safe today because the sub-PVs it posts
to have no handlers of their own, so no second handler lock is involved. If
that ever changes, this rule is what to check.)

---

## 6. How to safely put or post to *another* PV from inside a handler

Section 5 gave you the rule. This section is the practical companion: you have
a handler on PV-A, and inside its `put` or `post` you want to update PV-B — a
mirror, a derived value, a summary channel. Here is how to do it without
tripping the deadlock the rule warns about.

### First, know what you're holding

The moment your handler code runs, locks are already held on your behalf. Recall
*where* your handler is running (Sections 2 and 4):

- In a **`post`** handler, the caller's thread is inside `pv_a.post()`, which
  holds **PV-A's `_hook_lock`** for the whole body.
- In a **`put`** handler, you're on PV-A's **worker thread**, which took
  **PV-A's `_hook_lock`** via the `_exec()` wrapper before calling you.
- If PV-A's handler is a `CompositeHandler`, you *also* hold **that handler's
  `_lock`**.

Either way, by the time your code runs, **PV-A's lock is held.** Now you reach
for `pv_b.post(...)`, which wants **PV-B's `_hook_lock`** — a *different* lock.
That nesting (B's lock under A's) is the entire hazard.

### The safe case: posting back to the *same* PV

Updating your **own** PV is always fine:

```python
class Doubler:
    def put(self, pv, op):
        pv.post(op.value().value * 2)   # same PV — re-enters A's own RLock
        op.done()
```

`pv.post()` here re-acquires the lock the current thread already holds. Because
`_hook_lock` is an `RLock` (Section 1.4), the same thread just re-enters it — no
second lock, no ordering question, no deadlock. This is the overwhelmingly
common pattern and needs no special care.

### The hazardous case: reaching a *different* PV inline

The problem is calling `pv_b.post(...)` **inline** — synchronously, while PV-A's
lock is still held:

```python
class MirrorHandler:
    def post(self, pv, value):
        other_pv.post(derive(value))   # ⚠️ takes B's lock under A's lock
```

Mechanically this often *works*. But it takes PV-B's lock while holding PV-A's,
which is the `handler-then-second-PV` ordering the rule forbids. If **any** other
code path ever updates in the reverse direction (a handler on PV-B that posts to
PV-A), you have the classic cycle from Section 1.4:

```
Thread 1:  in pv_a.post → pv_b.post   holds A, wants B
Thread 2:  in pv_b.post → pv_a.post   holds B, wants A     → deadlock
```

Both threads wait forever. And note how easy this is to introduce by accident:
each handler looks locally reasonable; the deadlock only exists in the *pair*.

### Safe pattern for the thread flavor: `post_deferred` onto the other PV

The fix is to **stop holding PV-A's lock at the moment PV-B's lock is taken.**
Instead of calling `pv_b.post()` inline, hand the post to *PV-B's own worker
thread*, which will take PV-B's lock while holding nothing else. Use
`post_deferred`:

```python
class MirrorHandler:
    def post(self, pv, value):
        # NOT inline:  other_pv.post(derive(value))
        other_pv.post_deferred(derive(value))
```

`post_deferred` enqueues the post onto PV-B's work queue and returns a
`concurrent.futures.Future`. When PV-B's worker later runs it, that worker holds
**only** PV-B's lock — there is no A→B ordering edge, so the cycle above cannot
form. It is the thread-flavor counterpart of the asyncio flavor's
`post_deferred` (which marshals the post onto the loop), so a handler can fan out
the same way regardless of flavor, and it is the pattern to reach for whenever a
handler fans out to other PVs that themselves have handlers.

> Don't hand-roll this as `other_pv._exec(None, other_pv.post, v)`.
> `_exec(None, …)` routes through `_on_queue`, which *logs and swallows* the
> exception, so a failed mirror post there vanishes silently — whereas
> `post_deferred` captures it on the returned Future.

The trade-off: the mirror post now runs **later**, on another thread, so you
**don't get a synchronous readback** of PV-B inside your handler. An exception
raised by PV-B's post no longer reaches your caller inline — but it is **not
lost**: it surfaces on the returned Future (`fut.result()` re-raises,
`fut.exception()` returns it), so a fan-out failure can be logged or handled
without ever being able to abort PV-A's own post. That's the price of breaking
the lock nesting — and usually a fair one, because a mirror rarely needs to read
PV-B back mid-handler.

If you truly need the update to be synchronous, the only safe alternative is a
**global ordering**: guarantee updates always flow one way (A→B, never B→A) so
no reverse edge can exist. This is correct but brittle — one future handler that
posts B→A silently reintroduces the deadlock — so prefer deferral unless you can
enforce the direction structurally (as `DescMirrorHandler` does by giving its
sub-PVs no handlers at all).

### Safe pattern for the asyncio flavor: inline on the loop, `post_deferred` off it

The asyncio flavor is easier here, precisely because it has **no cross-thread
lock** and only one thread. Inside a handler you are already on the loop thread,
and handler hooks cannot `await` (Section 4), so a nested `pv_a.post → pv_b.post`
runs start-to-finish atomically on the loop — nothing can interleave between the
two posts, so the AB–BA cycle is structurally impossible:

```python
class MirrorHandler:
    def post(self, pv, value):
        other_pv.post(derive(value))   # fine: on the loop, runs atomically
```

The only thing to respect is affinity: `post()` must be on the loop. Inside a
handler you always are. If instead you're updating PV-B from a genuinely
different thread (a hardware poller, a thread-pool callback), use
`post_deferred()` so the post is marshalled onto the loop:

```python
other_pv.post_deferred(derive(value))          # from a foreign thread
# other_pv.post_deferred(derive(value)).result()  # only if you must wait —
#                                                  # and never from the loop
```

`post_deferred(...)` is the one spelling that works on **either** flavor — e.g.
a handler written to be flavor-agnostic. On the asyncio flavor it marshals onto
the loop; on the thread flavor it defers onto the work queue as above. Both
return a `concurrent.futures.Future`.

### Putting it together

The `put` case reduces to the same reasoning as `post`, because a `put` handler
already holds PV-A's lock (it runs on the worker under `_exec`). So the recipe,
whether you're in `put` or `post`:

1. **Same PV?** Just call `pv.post(...)`. Always safe.
2. **Different PV, thread flavor?** Defer: `other_pv.post_deferred(new_value)`.
3. **Different PV, asyncio flavor, and you're in a handler?** Call
   `other_pv.post(...)` inline — you're on the loop — or `post_deferred(...)`
   for the flavor-neutral spelling.
4. **Different PV from a foreign thread (asyncio)?** `other_pv.post_deferred(...)`.

The through-line: never let PV-B's lock be taken *while you still hold PV-A's*.
Same-PV re-entry doesn't count (one lock, re-entered); deferral and the
single-threaded loop both ensure PV-B's lock is taken with nothing else held.

---

## 7. Quick reference

| You are writing…                                   | Do this                                                        |
| -------------------------------------------------- | -------------------------------------------------------------- |
| a handler with mutable state, thread flavor        | nothing — the per-PV lock already serializes your methods      |
| a handler shared across PVs                         | subclass/use `CompositeHandler`, or add your own `RLock`       |
| code updating a **thread**-flavor PV from a thread | just call `pv.post(...)` — the lock makes it safe              |
| code updating an **asyncio** PV, on the loop        | `pv.post(...)`                                                  |
| code updating an **asyncio** PV, off the loop       | `pv.post_deferred(...)`, `.result()` if you need to wait       |
| a handler that updates a **different** PV, thread   | defer it: `other.post_deferred(v)` (see §6)                    |
| a handler that updates a **different** PV, asyncio   | `other.post(v)` inline (you're on the loop); see §6            |

### The mental model in three sentences

1. Handlers run in two regimes — put/rpc/connect on an executor, open/post/close
   on the caller's thread — and before the fix they could collide on shared
   state.
2. The thread flavor routes *both* regimes through one per-PV re-entrant lock
   (the per-PV dispatch lock), and `CompositeHandler` adds a second re-entrant
   lock for state shared across PVs (the per-handler state lock).
3. The asyncio flavor uses event-loop affinity instead of a lock — `post()` on
   the loop, `post_deferred()` off it — and one lock-ordering rule (PV lock
   before handler lock; never post to another PV under your handler lock) keeps
   the whole thing deadlock-free; §6 shows how to safely reach another PV from
   inside a handler despite that rule.
