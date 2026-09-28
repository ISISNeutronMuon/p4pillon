# Updating PVs safely

Publishing a PV is only half the job; the other half is pushing new values to it
as your data changes. This page is the practical rulebook for *where* and *how*
to call `post()`. Most of it only matters once your program has more than one
thread or updates one PV from another's handler — but those cases are common, and
getting them wrong causes silent races or deadlocks.

If you only ever post from your program's main loop, the [short version](#the-short-version)
is all you need. The design reasoning behind these rules is in
[Concurrency](../contributing/concurrency.md).

## The short version

- **Post to your own PV from your own code (main loop, a worker thread):** call
  `pv.post(value)`. On the thread flavor this is always safe.
- **Post to your own PV from inside its own handler:** call `pv.post(value)`.
  Safe — it re-enters the same lock.
- **Post to a *different* PV from inside a handler (thread flavor):** use
  `other_pv.post_deferred(value)`, never `other_pv.post(value)`.
- **Post to an asyncio PV from another thread:** use `pv.post_deferred(value)`;
  a plain `post()` off the loop raises `RuntimeError`.
- **When in doubt on the asyncio flavor, call `post()`** — if it's on the wrong
  thread it fails loudly and names the fix.

The rest of this page explains each case.

## Posting from your own code

The simplest and most common pattern: your program reads or computes a value and
pushes it. Keep a reference to the PV and call `post()`.

```python
temperature = SharedNT(nt=NTScalar("d"), initial=21.5)

with server:
    while True:
        temperature.post(read_sensor())
        time.sleep(1)
```

On the **thread flavor**, `post()` acquires the PV's lock, runs the NT rules
(timestamp, alarms, control), and stores the value as one atomic step. It is
safe to call from your main loop or from any background thread — the lock
serializes it against client puts.

On the **asyncio flavor**, `post()` must run on the PV's event loop. Inside a
coroutine or task running on that loop, just call it. From a *different* thread
(e.g. a hardware-polling thread), use `post_deferred()` — see
[below](#the-asyncio-flavor-loop-affinity).

## Updating one PV from another's handler

A frequent need: when PV A changes, update PV B — a mirror, a summary, a derived
quantity. You do this from A's `put` or `post` handler. Here the flavor matters,
because by the time your handler runs, **A's lock is already held**.

### Thread flavor: defer to the other PV

Calling `pv_b.post(...)` *inline* from A's handler takes B's lock while still
holding A's. If any other code path ever posts A from B's handler, the two can
deadlock (A holds its lock wanting B's; B holds its wanting A's). To avoid the
nested lock entirely, hand the update to B's own worker thread with
`post_deferred()`:

```python
class MirrorHandler(Handler):
    def post(self, pv, value):
        other_pv.post_deferred(derive(value))  # NOT other_pv.post(...)
```

`post_deferred()` enqueues the update onto B's work queue and returns a
`concurrent.futures.Future`. When B's worker runs it, it holds only B's lock, so
no A→B→A cycle can form. The trade-off: the update to B happens slightly later,
so you don't get a synchronous readback of B inside your handler. Any exception
B's post raises is not lost — it surfaces on the returned Future
(`fut.result()` re-raises it, `fut.exception()` returns it).

Posting back to the **same** PV from its handler is always fine — the lock is
re-entrant, so `pv.post(...)` just re-enters it. That is exactly what a `put`
handler does when it stores its validated value.

### asyncio flavor: inline on the loop is fine

The asyncio flavor has no cross-thread lock — everything runs on the one loop
thread, and handler hooks can't `await`, so a nested `pv_a.post → pv_b.post`
runs start-to-finish without interruption. Inside a handler you are already on
the loop, so posting to another PV inline is safe:

```python
class MirrorHandler(Handler):
    def post(self, pv, value):
        other_pv.post(derive(value))  # fine: on the loop, runs atomically
```

The only requirement is affinity: `post()` must be on the loop, which inside a
handler it always is.

## The asyncio flavor: loop affinity

The asyncio `SharedPV` enforces that `open()`/`post()` are called on its own
event loop. Call them from another thread and you get an immediate, explicit
`RuntimeError` naming the fix — instead of the undefined behaviour a plain p4p
asyncio PV would give. To update an asyncio PV from a genuinely different thread
(a hardware poller, a thread-pool callback), use `post_deferred()`:

```python
pv.post_deferred(new_value)  # marshals the post onto the loop
# pv.post_deferred(new_value).result()   # only if you must wait — and NEVER
#                                         # from the loop thread itself
```

`post_deferred()` returns a `concurrent.futures.Future`. **Never block on it
from the loop thread** — that waits for work the same loop must run, an instant
deadlock.

`post_deferred()` is the one spelling that works on **both** flavors: on asyncio
it marshals onto the loop, on the thread flavor it defers onto the work queue.
Write a flavor-agnostic handler with `post_deferred()` and it does the right
thing either way.

## Worked example: polling vs a handler

A common design question: when input A changes, should you *poll* it and react,
or attach a *handler* that reacts immediately? Both are valid; the choice depends
on the cost of reacting.

Consider a server with a writable `demo:city` enum and several read-only PVs
(`demo:temperatures`, `demo:rainchance`, `demo:umbrella`) that must refresh from
a slow weather API whenever the city changes. (Full code in
`examples/interface/`.)

**Polling** — check the input on a timer and update the others when it changes:

```python
previous_city = pvs["demo:city"].value
with server:
    while True:
        await asyncio.sleep(1)
        current_city = pvs["demo:city"].value
        if current_city != previous_city:
            await updater.update_weather(current_city)  # posts the other PVs
            previous_city = current_city
```

**Handler** — react the instant the city is put, with a handler on `demo:city`
that posts the other PVs:

```python
class CitiesHandler(Handler):
    def __init__(self, temperatures_pv, rainchance_pv, umbrella_pv): ...
    async def update_weather(self, city):
        weather = await get_weather_forecast(city)
        self._temperatures_pv.post(list(temperatures.values()))
        self._rainchance_pv.post(max_rainchance)
        self._umbrella_pv.post(umbrella_needed)

    def post(self, pv, value):
        # schedule the async update on the loop
        asyncio.get_running_loop().create_task(self.post_async(pv, value))


cities_pv = SharedNT(
    nt=NTEnum(), initial={"index": 0, "choices": cities}, user_handlers={"city_change": cities_handler}
)
```

The handler reacts immediately; polling reacts within one tick. Here **polling
is the better choice**, precisely because the reaction (a call to a slow, rate-
limited external API) is expensive — you don't want it fired on every rapid
change. When the reaction is cheap and immediacy matters, prefer the handler.
This is the general trade-off: immediacy versus controlling how often the
reaction runs.

## Where to go next

- [Concurrency](../contributing/concurrency.md) — the locks and event-loop
  affinity that make these rules necessary, in depth.
- [Handlers and rules](handlers-and-rules.md) — writing the handlers that do the
  posting.
