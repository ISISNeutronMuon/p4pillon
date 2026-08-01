# Handlers and rules

This page explains how p4pillon actually implements the Normative Type logic —
and, more usefully, how you add your own behaviour without losing it. It builds
on [Building PVs](building-pvs.md).

## Handlers in p4p

In p4p, a **handler** is an object attached to a `SharedPV` whose methods p4p
calls when things happen to the PV:

| Method | Called when |
| ------ | ----------- |
| `put` | a client writes to the PV |
| `rpc` | a client makes a remote procedure call |
| `onFirstConnect` | the first client subscribes |
| `onLastDisconnect` | the last client unsubscribes |

p4pillon adds three more hooks itself, which is what makes the NT logic possible:

| Method | Called when |
| ------ | ----------- |
| `open` | the PV is (re)opened with an initial value |
| `post` | the value is updated locally via `pv.post(...)` |
| `close` | the PV is closed |

A plain p4p `SharedPV` accepts exactly **one** handler. p4pillon needs several
cooperating pieces of behaviour on one PV (a timestamp rule, an alarm rule, a
control rule, plus whatever you add), so it introduces a handler that holds
other handlers: the `CompositeHandler`.

## `CompositeHandler`

`CompositeHandler` is a `Handler` that is also an `OrderedDict` of component
handlers. When p4p calls a hook (say `post`), the composite calls that hook on
each component **in order**. Because it is an ordered dict, you can inspect and
reorder the components by name.

```python
pv.handler.keys()  # names of the component handlers, in call order
```

A `SharedNT` builds one of these for you automatically. You rarely construct a
`CompositeHandler` by hand; instead you feed handlers to `SharedNT` through
three constructor arguments, which are merged in this order:

1. **`auth_handlers`** — run *first*. Intended for identification and
   authorization: deciding whether a `put` is allowed at all.
2. **`registered_handlers`** — the NT rules (see below), inserted automatically
   based on the PV's type and fields.
3. **`user_handlers`** — your application behaviour, run *after* the NT rules so
   it sees already-validated, already-clamped values.

Each is an `OrderedDict[str, Handler]`. The `timestamp` rule is always moved to
the very end so the stored value carries the time it was actually finalised.

> [!NOTE]
> `CompositeHandler` works with `Handler` **objects**, not with p4p's `@pv.put`
> decorator syntax. On a `SharedNT` the decorators are disabled (they raise
> `NotImplementedError`) — attach behaviour with handler classes instead.

## Rules: the NT logic, as swappable components

The components in `registered_handlers` are **`Rule`s** — a specialised
`Handler` that captures the common EPICS flow of *validate → maybe modify →
store*. p4pillon ships these built-in rules:

| Rule | Responsibility |
| ---- | -------------- |
| `AlarmRule` | maintain the base `alarm` structure |
| `ControlRule` | clamp values to `control.limitLow/High` |
| `ValueAlarmRule` | trip `alarm` from `valueAlarm` thresholds |
| `AlarmNTEnumRule` | alarm handling specific to `NTEnum` |
| `TimestampRule` | stamp `timeStamp` on every change (kept last) |
| `CalcRule` | recompute `value` from other PVs (see below) |

A rule is added to a PV **only if it applies**. Each rule class declares:

- `name` — its key in the composite;
- `nttypes` — which Normative Types it supports (or `ALL`);
- `fields` — sub-fields that must be present for it to run (e.g. `ControlRule`
  needs a `control` field);
- `add_automatically` — whether it is inserted whenever applicable, or only when
  you opt in by name.

So declaring `control=True` on your `NTScalar` is what causes `ControlRule` to
be added and your values to be clamped; omit the field and the rule is silently
skipped. This is the mechanism behind "which logic is switched on depends on
which fields you declared" from [Building PVs](building-pvs.md#what-the-logic-does).

Inside a rule, work happens in `init_rule()` (on `open`) and `post_rule()` (on
`post`/`put`), each returning a `RulesFlow` value that controls the chain:

| `RulesFlow` | Effect |
| ----------- | ------ |
| `CONTINUE` | run the next rule |
| `TERMINATE` | stop, but still apply the timestamp |
| `TERMINATE_WO_TIMESTAMP` | stop without timestamping |
| `ABORT` | reject the operation (with an error message) |

### The `CalcRule`: PVs computed from other PVs

`CalcRule` recomputes a PV's value from an expression over other PVs. It is most
easily configured from a [YAML file](config-files.md), where the
`DEV:RW:DOUBLECALC` PV is defined as `pv[0] + 2.12*pv[1]` over
`[DEV:RW:INT3, DEV:RW:INT4]`. Verified live: putting `INT3=1`, `INT4=1` makes
`DOUBLECALC` recompute to `3.12`, updating automatically when either input
changes.

## Writing your own rule

Subclass `BaseRule`, declare when it applies, and register it. This example (from
`examples/custom_rule/public/`) raises a MAJOR alarm whenever an integer PV's
value equals a configured `imatch` target:

```python
from typing import ClassVar
from p4p import Value
from p4pillon.rules import AlarmRule, BaseRule, ControlRule, RulesFlow, TimestampRule, ValueAlarmRule
from p4pillon.rules.rules import check_applicable_init
from p4pillon.thread.sharednt import SharedNT


class IMatchRule(BaseRule):
    name = "imatch"
    fields: ClassVar[list[str] | None] = ["alarm", "imatch"]  # only runs if these fields exist

    @check_applicable_init
    def init_rule(self, newpvstate: Value) -> RulesFlow:
        if not newpvstate["imatch.active"]:
            return RulesFlow.CONTINUE
        if newpvstate["imatch.imatch"] == newpvstate["value"]:
            newpvstate["alarm.severity"] = 2
            newpvstate["alarm.message"] = "IMATCH"
        else:
            newpvstate["alarm.severity"] = 0
            newpvstate["alarm.message"] = ""
        return RulesFlow.CONTINUE


# Register it into the rule chain used by new SharedNT instances
SharedNT.registered_handlers = [AlarmRule, ControlRule, ValueAlarmRule, IMatchRule, TimestampRule]
```

That example adds an `imatch` field to the PV's structure so it is visible to
standard pvAccess tools. `examples/custom_rule/hidden/` shows the alternative:
keeping the extra state inside the rule instead of the `Value`, leaving the
Normative Type unmodified — at the cost of the state not being externally
manipulable. The `examples/custom_rule/README.md` compares the trade-offs.

## Plain handlers for application behaviour

Not everything needs to be a `Rule`. For side effects — writing to hardware,
logging who did what — an ordinary `Handler` in `user_handlers`/`auth_handlers`
is simpler. From `examples/thread/hwinterface.py`:

```python
from p4pillon.nthandlers import Handler


class UserReportHandler(Handler):  # an auth handler: observe every put
    def put(self, _pv, op):
        print(f"Operation by user {op.account()} on pv {op.name()}")


class HWWriteHandler(Handler):  # a user handler: push writes to hardware
    def __init__(self, hardware):
        self.hardware = hardware

    def post(self, _pv, value):
        if value.changed("value"):
            self.hardware.value = value["value"]

    def put(self, pv, op):
        pass  # allow the put; NT rules do the rest


pv = SharedNT(
    nt=NTScalar("d", control=True),
    initial={"value": 4.5, "control.limitHigh": 25},
    auth_handlers=OrderedDict({"spy": UserReportHandler()}),
    user_handlers=OrderedDict({"hwwrite": HWWriteHandler(hw)}),
)
```

Because `HWWriteHandler` runs *after* the NT rules, the value it writes to
hardware is already clamped to the control limit — ordering is doing real work
here.

### Rejecting a put

Two ways to reject a client write:

- **Read-only PV:** `pv.handler.read_only = True` — the composite refuses all
  puts with `This PV is read-only` while still allowing your own `post()`.
- **Conditional rejection:** raise `AbortHandlerError("reason")` from a
  handler's `put`; the composite stops the chain and returns that message to the
  client.

## A word on concurrency

Handlers run under locks that p4pillon manages for you, and there is **one rule
you must not break**: a handler must never call *another* PV's
`open()`/`post()`/`close()` while holding its own handler lock — it can deadlock.
Updating your *own* PV is always safe. This matters the moment a handler updates
a *different* PV (a mirror, a derived value); the safe patterns are in
[Updating PVs safely](updating-pvs.md), and the full reasoning in
[Concurrency](../contributing/concurrency.md).

## Where to go next

- [Updating PVs safely](updating-pvs.md) — `post()` vs `post_deferred()`, and
  fanning out to other PVs from a handler.
- [Configuration files](config-files.md) — configure rules like `CalcRule`
  declaratively.
- [Concurrency](../contributing/concurrency.md) — the locks behind these rules,
  for contributors.
