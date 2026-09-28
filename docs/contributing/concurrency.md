# Concurrency

**Audience:** you want to contribute to p4pillon and are not (yet) fluent in
Python's concurrency models. This is the single most important thing to
understand before touching the handler-dispatch code, the locks, or the rules —
a change that looks locally correct can introduce a race or a deadlock that only
appears under load.

## Read the tutorial

There is a thorough, from-first-principles walkthrough of p4pillon's concurrency
design already in the tree:

> **[Serializing handler dispatch: a tutorial on the per-PV and per-handler
> locks](../design/dispatch_fix.md)**

It assumes you know Python but **not** threads, locks, or event loops, and builds
up exactly enough of each to understand the code. If any term on this page is
unfamiliar, that document is where to start — read it top to bottom once. This
page is the short map; that one is the territory.

## The model in brief

Handlers run in **two regimes**, and before the fix documented in the tutorial
they could collide on shared state:

1. **`put` / `rpc` / connect** run on an **executor** — the thread flavor's
   per-PV work queue, or the asyncio flavor's event loop.
2. **`open` / `post` / `close`** run **synchronously on whatever thread called
   `pv.open()`/`post()`/`close()`** — they mutate the value in place before it
   is stored in the C extension, so they can't be deferred onto the executor.

Those two regimes can run at the same time on the same handler. Two mechanisms
keep them safe, one per flavor:

- **Thread flavor — a per-PV re-entrant lock** (`_hook_lock` in
  [`server/raw.py`](../../p4pillon/server/raw.py)). `open`/`post`/`close` hold it
  across *wrap → handler hook → store*; the thread flavor's `_exec`
  ([`server/thread.py`](../../p4pillon/server/thread.py)) runs every executor
  callback under the *same* lock. Both regimes therefore serialize on one lock.
  It is re-entrant (`RLock`) because a `put` handler routinely calls `pv.post()`,
  re-entering the lock the worker thread already holds.

- **asyncio flavor — event-loop affinity, not a lock** (`_hook_guard` in
  [`server/asyncio.py`](../../p4pillon/server/asyncio.py)). Everything runs on the
  one loop thread, so requiring `open`/`post` to be *called on that loop* lets the
  loop itself serialize them. Off-loop calls raise `RuntimeError`; use
  `post_deferred()` to marshal a post onto the loop from another thread. A
  cross-thread lock is avoided deliberately — it would block the whole loop.

There is also a **per-handler lock** inside
[`CompositeHandler`](../../p4pillon/composite_handler.py), for the case the per-PV
lock can't cover: *one handler object shared across several PVs* (each PV has its
own distinct `_hook_lock`, so they wouldn't otherwise serialize).

## The invariants you must not break

When editing handler, lock, or rule code, preserve these:

1. **Lock ordering: PV lock before handler lock, always.** Handler methods are
   only ever reached *through* PV dispatch, so this holds naturally. Never write
   code that takes a handler lock and then a PV lock.

2. **A handler must never call *another* PV's `open()`/`post()`/`close()` while
   holding its own handler lock.** That takes a second PV's `_hook_lock` under a
   handler lock — the inverse order — and risks the classic two-thread deadlock.
   Posting back to the *same* PV is fine (re-entrant). To fan out to a *different*
   PV, use `post_deferred()` so the other PV's lock is taken with nothing else
   held. This is the one rule that also surfaces to users, in
   [Updating PVs safely](../guide/updating-pvs.md).

3. **`_hook_lock` must exist before the base `__init__` runs.** p4p's constructor
   calls `open()` during construction, and `open()` acquires the lock —
   `HandlerHooksMixin.__init__` creates it *first*, then calls `super().__init__`.
   Don't reorder that.

4. **The flavor seam is `_hook_guard`.** Both flavors enter the hooks through it;
   the asyncio flavor overrides it to add the affinity check. Add cross-flavor
   dispatch policy there, not by overriding each hook method.

5. **Route deferred-post exceptions to the returned `Future`.** `post_deferred`
   on both flavors captures exceptions on the `concurrent.futures.Future` rather
   than logging-and-swallowing them. Preserve that when touching either
   implementation.

## Tests

Concurrency behaviour is covered by
[`tests/unit/test_concurrency_variant_isolation.py`](../../tests/unit/test_concurrency_variant_isolation.py)
and the dispatch-locking tests. Run the suite with `uv run pytest`. If you change
locking, add a test that would fail under the interleaving you're guarding
against — races don't reproduce reliably by hand.

## Where to go next

- **[The concurrency tutorial](../design/dispatch_fix.md)** — the full
  treatment, including worked deadlock scenarios and a quick-reference table.
- [Architecture](architecture.md) — where this code sits in the wider library.
- [Updating PVs safely](../guide/updating-pvs.md) — the user-facing consequences
  of everything above.
