# Migrating from p4p

**Audience:** you already have a working p4p program and want to move it to
p4pillon. The single most common reason is *"my timestamps are stuck at the
epoch and I want them to just work"* — but the same one-line change also gets
you working alarms and control limits. This page shows the change, then covers
the couple of things you must know when you make it.

## The starting point, in p4p

Here is the classic p4p "mailbox" server, with a couple of Normative Type
fields declared (`control` and `valueAlarm`):

```python
from p4p.nt import NTScalar
from p4p.server import Server
from p4p.server.thread import SharedPV

pv = SharedPV(
    nt=NTScalar("d", control=True, valueAlarm=True),
    initial={
        "value": 2.2,
        "control.limitHigh": 10,
        "valueAlarm.active": True,
        "valueAlarm.highWarningLimit": 5,
        "valueAlarm.highWarningSeverity": 1,
        "valueAlarm.highAlarmLimit": 8,
        "valueAlarm.highAlarmSeverity": 2,
    },
)

@pv.put
def handle(pv, op):
    pv.post(op.value())   # just store and update subscribers
    op.done()

Server.forever(providers=[{"demo:pv:name": pv}])
```

The PV has the *fields* for a timestamp, an alarm, and control limits — but p4p
does not fill them in. The value changes, yet:

```console
$ uv run python -m p4p.client.cli get demo:pv:name
demo:pv:name Thu Jan  1 00:00:00 1970 2.2          # timestamp never set

$ uv run python -m p4p.client.cli put demo:pv:name=12.7
$ uv run python -m p4p.client.cli get demo:pv:name
demo:pv:name Thu Jan  1 00:00:00 1970 12.7         # 12.7 stored despite limitHigh=10
```

The structure is there; the *logic* the structure implies is not. p4p gives you
the shape of a Normative Type and leaves the behaviour to you.

## The fix: use `SharedNT`

Replace `p4p`'s `SharedPV` with p4pillon's `SharedNT`, and delete the `@pv.put`
handler — `SharedNT` supplies the store-and-timestamp behaviour itself:

```python
from p4p.nt import NTScalar
from p4p.server import Server

from p4pillon.thread.sharednt import SharedNT   # <-- the only import that changed

pv = SharedNT(
    nt=NTScalar("d", control=True, valueAlarm=True),
    initial={
        "value": 2.2,
        "control.limitHigh": 10,
        "valueAlarm.active": True,
        "valueAlarm.highWarningLimit": 5,
        "valueAlarm.highWarningSeverity": 1,
        "valueAlarm.highAlarmLimit": 8,
        "valueAlarm.highAlarmSeverity": 2,
    },
)

Server.forever(providers=[{"demo:pv:name": pv}])
```

Now the fields carry their meaning. Timestamps track updates, the warning fires,
and control limits clamp — this is real output from the code above:

```console
$ uv run python -m p4p.client.cli get demo:pv:name
demo:pv:name Sun Jul 19 10:18:27 2026 2.2          # timestamp is set

$ uv run python -m p4p.client.cli put demo:pv:name=6.6
$ uv run python -m p4p.client.cli --raw get demo:pv:name
demo:pv:name struct "epics:nt/NTScalar:1.0" {
    double value = 6.6
    struct "alarm_t" {
        int32_t severity = 1
        int32_t status = 0
        string message = "highWarning"                # 6.6 > highWarningLimit=5
    } alarm
    struct "time_t" {
        int64_t secondsPastEpoch = 1784452721         # real timestamp
        ...
    } timeStamp
    ...
}

$ uv run python -m p4p.client.cli put demo:pv:name=12.7
$ uv run python -m p4p.client.cli get demo:pv:name
demo:pv:name Sun Jul 19 10:18:42 2026 10.0            # clamped to limitHigh=10, MAJOR alarm
```

That is the migration in a sentence: **`SharedPV` → `SharedNT`, drop the
boilerplate `put` handler.** Everything else about your server — the provider,
the `Server`, the client tools — is unchanged.

If your program builds PVs by hand with `NTScalar`/`NTEnum` like this, keep
reading [Building PVs](../guide/building-pvs.md) for the full set of fields you
can declare. If you'd rather describe PVs more declaratively, p4pillon also
offers [PVRecipe](../guide/building-pvs.md#pvrecipe) and
[YAML config files](../guide/config-files.md).

## Choosing a flavor

p4p ships two `SharedPV` classes — `p4p.server.thread.SharedPV` and
`p4p.server.asyncio.SharedPV` — and you pick the one matching how your program
runs. p4pillon mirrors this exactly. **Import `SharedNT` from the package that
matches your program:**

| Your p4p import | Your p4pillon import |
| --------------- | -------------------- |
| `from p4p.server.thread import SharedPV` | `from p4pillon.thread.sharednt import SharedNT` |
| `from p4p.server.asyncio import SharedPV` | `from p4pillon.asyncio.sharednt import SharedNT` |

Use the **thread** flavor if your program is ordinary synchronous Python (loops,
`time.sleep`, background threads). Use the **asyncio** flavor if your program is
built around `async def`/`await` and an event loop. If you have no reason to
prefer one, the thread flavor is the simpler default and needs the least care
when you post values from your own code.

This choice is not cosmetic: the two flavors have genuinely different rules for
*where* you are allowed to call `post()` from. For simple "post from my main
loop" code it never bites you, but as soon as you post to a PV from inside a
handler, or from a different thread, read
[Updating PVs safely](../guide/updating-pvs.md). The design reasons are in
[Concurrency](../contributing/concurrency.md).

## Things that will trip you up

A short checklist of behaviours that differ from plain p4p or from older
p4pillon:

- **`asyncio` PVs must have `post()`/`open()` called on their own event loop.**
  Calling them from another thread raises `RuntimeError` (deliberately — it was
  previously undefined behaviour). To update an asyncio PV from a different
  thread, use `post_deferred()`, which marshals the update onto the loop. See
  [Updating PVs safely](../guide/updating-pvs.md).

- **`PVRecipe` classes are now flavor-bound.** Import
  `PVScalarRecipe`/`PVScalarArrayRecipe`/`PVEnumRecipe` from
  `p4pillon.thread.pvrecipe` or `p4pillon.asyncio.pvrecipe` — **not** from the
  base `p4pillon.pvrecipe`, whose classes raise `TypeError` when built. The base
  classes used to silently build unflavored PVs with no serialization; that
  footgun was removed.

- **`CompositeHandler` works with `Handler` objects, not the `@pv.put`
  decorators.** If you attach behaviour to a `SharedNT`, do it with handler
  classes / the `user_handlers`/`auth_handlers` arguments, not the decorator
  form. See [Handlers and rules](../guide/handlers-and-rules.md).

## Where to go next

- [Updating PVs safely](../guide/updating-pvs.md) — `post()` vs `post_deferred()`,
  and updating one PV from another's handler.
- [Building PVs](../guide/building-pvs.md) — every NT field you can declare, plus
  the `PVRecipe` factory.
- [Handlers and rules](../guide/handlers-and-rules.md) — customise what happens
  on `put`/`post` without losing the NT logic.
- [p4p documentation](https://epics-base.github.io/p4p/) — the underlying
  `SharedPV`, `Server`, and Normative Type API that p4pillon builds on and keeps
  compatible.
