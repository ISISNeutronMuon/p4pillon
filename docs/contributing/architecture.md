# Architecture

**Audience:** you want to contribute to p4pillon and need the shape of the
codebase — where things live, why they're structured this way, and the couple of
non-obvious design decisions that everything else follows from. Read
[Concurrency](concurrency.md) alongside this; the threading model is the other
half of understanding the code.

## The core idea, restated

p4p gives you the *structure* of Normative Types; p4pillon adds the *logic*. That
logic is implemented entirely with p4p's **handler** mechanism — there is no new
protocol code and no fork of p4p. Almost everything in the library is, at bottom,
"a handler that does something on `open`/`put`/`post`", plus the plumbing to
compose many such handlers onto one PV. Keep that framing and the module layout
falls into place.

## Two structural decisions

### 1. Inheritance, not monkey-patching

p4pillon needs three handler hooks that stock p4p lacks — `open()`, `post()`,
`close()` (the same hooks proposed upstream in
[PR #172](https://github.com/epics-base/p4p/pull/172), but p4pillon implements
its own and so does **not** depend on that PR being merged — it works against a
stock p4p). Those hooks have to live on the `SharedPV` classes. p4pillon adds
them with a mixin, `HandlerHooksMixin` in
[`p4pillon/server/raw.py`](../../p4pillon/server/raw.py), composed into each
flavor by ordinary inheritance:

```python
class SharedPV(HandlerHooksMixin, p4p.server.thread.SharedPV): ...  # server/thread.py


class SharedPV(HandlerHooksMixin, p4p.server.asyncio.SharedPV): ...  # server/asyncio.py
```

An earlier design monkey-patched `p4p.server.raw.SharedPV`'s base class instead.
That patch silently did nothing if any code imported p4p first — a genuine bug
that depended on import order. Inheritance is immune to it. (The historical note
in [`p4pillon/server/README.md`](../../p4pillon/server/README.md) still describes
the old monkey-patch approach; the code has since moved to inheritance.)

### 2. Two concurrency flavors, chosen by import

Every user-facing class exists in a **thread** and an **asyncio** variant,
selected by which subpackage you import from. This mirrors p4p, which has the
same split, and it exists because the two have genuinely different rules for
where handler code may run (see [Concurrency](concurrency.md)). The flavor-neutral
logic lives in a mixin or base class; the flavor packages compose it with the
matching p4p base:

- `SharedNT` — `SharedNTMixin` (in [`p4pillon/sharednt.py`](../../p4pillon/sharednt.py))
  + a flavored `SharedPV`, re-exported from `p4pillon/thread/sharednt.py` and
  `p4pillon/asyncio/sharednt.py`.
- `PVRecipe` — `BasePVRecipe` (in [`p4pillon/pvrecipe.py`](../../p4pillon/pvrecipe.py))
  is abstract-ish: its `build_pv()` raises `TypeError` unless a flavor subclass
  has bound `_sharednt_cls`. The usable classes live in `p4pillon/thread/pvrecipe.py`
  / `p4pillon/asyncio/pvrecipe.py`.
- `Server` — `Server` base (in [`p4pillon/server/server.py`](../../p4pillon/server/server.py))
  + a `_context` set by `p4pillon/thread/server.py` / `p4pillon/asyncio/server.py`.

When you add a feature, put the logic in the shared base/mixin and only the p4p
base binding in the flavor modules. A recurring past bug was flavor-specific code
leaking into the shared layer (an unflavored recipe silently building a
raw-flavored PV, a `Server` mutating a shared `_context`); the design now fails
loud instead.

## Module map

```
p4pillon/
├── sharednt.py          SharedNTMixin — assembles the rule chain into a CompositeHandler
├── composite_handler.py CompositeHandler (Handler + OrderedDict) + its lock; AbortHandlerError
├── nthandlers.py        Handler, ComposeableRulesHandler (adapts a Rule to a Handler)
├── pvrecipe.py          BasePVRecipe (flavor-bound via _sharednt_cls)
├── config_reader.py     YAML -> PVRecipe -> Server
├── definitions.py       PVTypes, numeric limits, alarm/format enums
├── utils.py             timestamp helpers, value-merge helpers
├── nt/                  NTScalar/NTEnum wrappers, type identification (identify.py), specs
├── rules/               the NT logic, one file per rule:
│   ├── rules.py         BaseRule, RulesFlow, SupportedNTTypes, array-wrapper plumbing
│   ├── alarm_rule.py, value_alarm_rule.py, alarm_ntenum_rule.py
│   ├── control_rule.py, timestamp_rule.py, calc_rule.py, read_only_rule.py
├── server/
│   ├── raw.py           HandlerHooksMixin + raw-flavored SharedPV, Handler (open/post/close hooks)
│   ├── thread.py        thread SharedPV: _exec under _hook_lock, post_deferred via work queue
│   ├── asyncio.py       asyncio SharedPV: loop-affinity _hook_guard, post_deferred onto loop
│   ├── server.py        Server lifecycle base
│   ├── cli.py           CLI entry
│   └── records/         RECORD.FIELD sub-PVs (see below)
├── thread/  asyncio/    flavor bindings: sharednt, pvrecipe, server
```

### How a `SharedNT` is assembled

The heart of the library is `SharedNTMixin.__init__`. Given `nt=`/`initial=`, it:

1. creates a `CompositeHandler`, seeding it with any `auth_handlers`;
2. walks `registered_handlers` (the default list: `AlarmRule`, `ControlRule`,
   `AlarmNTEnumRule`, `ValueAlarmRule`, `TimestampRule`, `CalcRule`) and adds
   each rule **only if it applies** to this PV's type and declared fields —
   `__setup_registered_rule` does the applicability check against each rule's
   `name`/`nttypes`/`fields`/`add_automatically` class attributes;
3. merges in your `user_handlers`;
4. moves `timestamp` to the end so the stored value is timestamped last;
5. hands the composite to the p4p base as the PV's single handler.

So "which NT logic runs" is a data-driven consequence of the declared fields, not
hard-coded. Adding a built-in rule means writing a `BaseRule` subclass in
`rules/` and adding it to `registered_handlers`. The user-facing side of this is
[Handlers and rules](../guide/handlers-and-rules.md).

### The `records/` subpackage

[`p4pillon/server/records/`](../../p4pillon/server/records/) is self-contained and
serves `RECORD.FIELD` sub-PVs. It splits by concern: `fields.py` (the field
schema and `build_record_fields`), `static.py` (the eager `StaticRecordProvider`),
`dynamic.py` (the lazy `DynamicRecordFields`/`IOCMimicProvider`), `server.py`
(`IOCMimicServer`). Its module docstring is an excellent, detailed rationale —
read it before touching this code. User-facing docs: [Record fields](../guide/record-fields.md).

## Dependencies

p4pillon has a deliberately small runtime footprint — two packages, declared in
[`pyproject.toml`](../../pyproject.toml):

- **`p4p`** — the pvAccess/PVXS Python binding p4pillon is built on. It supplies
  `SharedPV`, the `NTScalar`/`NTEnum` Normative Type structures, and the server
  context; p4pillon adds the NT *logic* on top (see [Architecture](#two-structural-decisions)).
  This is the one load-bearing dependency.
- **`pyyaml`** — parses the YAML PV descriptions consumed by `config_reader`
  ([Configuration files](../guide/config-files.md)). Only the config path uses it;
  building PVs in Python needs nothing beyond p4p.

The rest are development-only, grouped under `[dependency-groups]` and installed
by `uv sync`:

- **test** — `pytest` plus `pytest-asyncio` (the asyncio-flavor tests are
  coroutines and need the plugin), `coverage`, and `ruff` (lint + format).
- **dist** — `build` and `twine`, for packaging and publishing a release.

## Development workflow

From the repository root, using [`uv`](https://docs.astral.sh/uv/):

```console
$ uv sync                       # install dev dependencies (test + dist groups)
$ uv run pytest                 # run the tests
$ uv run coverage run -m pytest && uv run coverage report
$ uv run ruff check --fix       # lint
$ uv run ruff format            # format
```

CI enforces ruff and the test suite. New and edited code should carry type hints
and pass ruff. Prefer `uv run …` over bare `python` so commands use the project
environment.

## Where to go next

- [Concurrency](concurrency.md) — the locking and event-loop model, essential
  before changing anything in `server/`, `composite_handler.py`, or the rules.
- The module docstrings in `server/records/__init__.py` and `server/raw.py` are
  the most detailed in-tree design notes; keep them in sync when you change that
  code.
