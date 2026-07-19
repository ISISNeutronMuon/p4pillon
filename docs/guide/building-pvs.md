# Building PVs

This page covers the two ways p4pillon lets you create PVs that carry Normative
Type logic: constructing a **`SharedNT`** directly (full control, closest to
p4p), and describing one with a **`PVRecipe`** (less boilerplate). It assumes
the [concepts](concepts.md) page.

Throughout, import the flavor that matches your program — `p4pillon.thread.*`
for synchronous code, `p4pillon.asyncio.*` for async code (see
[choosing a flavor](../getting_started/migrating-from-p4p.md#choosing-a-flavor)).
Examples use the thread flavor.

## `SharedNT`

`SharedNT` is a drop-in replacement for p4p's `SharedPV`: same constructor
arguments (`nt=`, `initial=`), same `post()`/`current()`/`close()` methods,
plus the automatic NT logic. You declare which optional fields the PV has when
you build the `NTScalar`, and give them initial values in `initial`.

```python
from p4p.nt import NTScalar
from p4pillon.thread.sharednt import SharedNT

pv = SharedNT(
    nt=NTScalar("d", display=True, control=True, valueAlarm=True),
    initial={
        "value": 2.2,
        # display metadata — units, limits, description shown by clients
        "display.description": "Chamber pressure",
        "display.units": "mbar",
        "display.limitLow": 0,
        "display.limitHigh": 20,
        # control limits — values put to the PV are clamped into this range
        "control.limitHigh": 10,
        # alarm thresholds — the alarm field trips when value crosses these
        "valueAlarm.active": True,
        "valueAlarm.highWarningLimit": 5,
        "valueAlarm.highWarningSeverity": 1,   # 1 = MINOR
        "valueAlarm.highAlarmLimit": 8,
        "valueAlarm.highAlarmSeverity": 2,     # 2 = MAJOR
    },
)
```

The first argument to `NTScalar` is the **value type code**:

| Code | Type | Code | Type |
| ---- | ---- | ---- | ---- |
| `"d"` | double | `"i"` | 32-bit int |
| `"l"` | 64-bit int | `"s"` | string |
| `"b"` | byte | `"?"` | bool |

Prefix with `a` for an array (`"ad"` = double array), or pass `valueAlarm=True`
etc. to include those optional sub-structures. See p4p's
[NTScalar docs](https://epics-base.github.io/p4p/nt.html) for the full set.

### What the logic does

With the PV above, p4pillon enforces the fields automatically. Every `post()` or
client `put()`:

- **stamps the current time** into `timeStamp` (a plain p4p `SharedPV` leaves it
  at the epoch);
- **clamps** the value to `[control.limitLow, control.limitHigh]` if a `control`
  field is present;
- **evaluates alarm thresholds** and sets `alarm.severity`/`alarm.message`
  (`highWarning`, `highAlarm`, `lowWarning`, `lowAlarm`).

You saw this verified end-to-end in
[Migrating from p4p](../getting_started/migrating-from-p4p.md#the-fix-use-sharednt):
posting 6.6 to the PV above raises a `highWarning`; posting 12.7 clamps to 10.0
and raises a MAJOR alarm.

Which logic is switched on depends on which fields you declared — the machinery
that decides this is described in [Handlers and rules](handlers-and-rules.md).
If you don't declare `control`, values aren't clamped; if you don't declare
`valueAlarm`, no thresholds are checked. A timestamp is always maintained.

### Arrays

Declare an array value type and pass a list as the value. Alarm thresholds apply
element-wise (the most severe element wins):

```python
pv = SharedNT(
    nt=NTScalar("ai", display=True, valueAlarm=True),   # array of int
    initial={
        "value": [12, 11, 12, 19, 25],
        "display.description": "Forecast temperature every 3 hours",
        "display.units": "C",
        "valueAlarm.active": True,
        "valueAlarm.highWarningLimit": 18,
        "valueAlarm.highWarningSeverity": 1,
        "valueAlarm.highAlarmLimit": 25,
        "valueAlarm.highAlarmSeverity": 2,
    },
)
```

### Enums

An `NTEnum` holds an index into a list of choice labels. Use it for states with
meaning rather than a bare boolean:

```python
from p4p.nt import NTEnum
from p4pillon.thread.sharednt import SharedNT

umbrella = SharedNT(
    nt=NTEnum(),
    initial={"index": 0, "choices": ["Not needed", "Needed"]},
)
```

Reading the PV shows the *label* (`Not needed`), while the wire value is the
index. A client puts either the index or the matching label.

### Read-only PVs

To reject client puts (while still allowing your own program to `post()`
updates), set the handler's `read_only` flag:

```python
pv.handler.read_only = True
```

A client `put` then fails with `This PV is read-only`, but `pv.post(...)` from
your code still works. This is the right choice for readbacks — values your
program produces that clients should observe but not change.

## `PVRecipe`

`PVRecipe` is a higher-level factory: instead of assembling the `NTScalar`
structure and the `initial` dict by hand, you describe the PV with typed helper
methods and call `create_pv()`. **Import the recipe classes from the flavored
module** (`p4pillon.thread.pvrecipe` or `p4pillon.asyncio.pvrecipe`) — the base
`p4pillon.pvrecipe` classes raise `TypeError` on purpose (see the
[migration notes](../getting_started/migrating-from-p4p.md#things-that-will-trip-you-up)).

```python
from p4pillon.definitions import PVTypes
from p4pillon.thread.pvrecipe import PVScalarRecipe

recipe = PVScalarRecipe(PVTypes.DOUBLE, "An example double PV", initial_value=17.5)
recipe.set_alarm_limits(low_warning=2, high_alarm=9)
recipe.set_control_limits(low=-10, high=100)

pv = recipe.create_pv()          # -> a flavored SharedNT
```

`create_pv()` returns a fully-built `SharedNT` with `valueAlarm` and `control`
populated — verified: the call above produces a `p4pillon.thread.sharednt.SharedNT`
with value 17.5 and both sub-structures present.

The recipe classes are:

- **`PVScalarRecipe`** — a single scalar (`PVTypes.DOUBLE`, `.INTEGER`,
  `.STRING`).
- **`PVScalarArrayRecipe`** — an array of scalars; pass a list as
  `initial_value` (a scalar is wrapped into a one-element list).
- **`PVEnumRecipe`** — an `NTEnum` (`PVTypes.ENUM`).

Helper methods mirror the NT fields: `set_control_limits(low, high, min_step)`,
`set_display_limits(low, high, units, format, precision)`,
`set_alarm_limits(low_warning, high_warning, low_alarm, high_alarm)`, and the
`read_only` attribute. A recipe is reusable — set `initial_value`, build one PV,
change a field, build another; `copy()` gives you an independent duplicate.

Recipes pair naturally with the p4pillon [`Server`](server.md), which accepts a
recipe directly and defers building until the server starts, and with
[YAML config files](config-files.md), which are essentially recipes on disk.

## Where to go next

- [Handlers and rules](handlers-and-rules.md) — how the NT logic is assembled
  from `Rule`s, and how to add your own behaviour on `put`/`post`.
- [Updating PVs safely](updating-pvs.md) — the correct way to push new values,
  especially from handlers or other threads.
- [Running a server](server.md) — serve the PVs you just built.
