# p4pillon documentation

p4pillon is a Python library built on top of
[p4p](https://epics-base.github.io/p4p/) that helps you create and manage
[pvAccess](https://docs.epics-controls.org/en/latest/pv-access/protocol.html)
PVs. Where p4p gives you the *structure* of the EPICS
[Normative Types](guide/concepts.md#normative-types) (an `NTScalar` has an
`alarm` field, a `timeStamp` field, a `control` field, …), p4pillon adds the
*logic* those fields imply: timestamps update themselves, control limits clamp
values, and alarms are raised — all without you writing a handler for it.

> [!WARNING]
> p4pillon is **not** a replacement for a traditional EPICS IOC and its
> Process Database. The Normative Type logic is implemented but does not give
> you the database-record consistency guarantees of an IOC. Under concurrent
> updates a PV can still be made inconsistent by application code that ignores
> the rules in [Updating PVs safely](guide/updating-pvs.md). Treat p4pillon as
> a tool for rapid prototyping, soft PVs, and glue between Python programs and
> the control system — not for anything where a wrong value is dangerous.

## Requirements

- **Python 3.10 or later** (p4pillon uses modern typing features heavily).
- **p4p** (installed automatically as a dependency).

```console
$ pip install p4pillon      # or: uv sync, inside this repository
```

## Start here — pick your path

The documentation is organised around what you are trying to do, not around the
module layout. Find the row that matches you.

| I want to… | Start at |
| ---------- | -------- |
| **Publish some data I already have in Python** as a PV, with as little EPICS knowledge as possible | [Publish existing data](getting_started/publish-existing-data.md) |
| **Convert an existing p4p program** to p4pillon — most often, "I just want timestamps to work" | [Migrating from p4p](getting_started/migrating-from-p4p.md) |
| **Understand EPICS and p4p and build a real application** from the ground up | [The guide](guide/concepts.md) (start at Concepts) |
| **Contribute to p4pillon**, especially if Python threads and asyncio are new to me | [Contributing](contributing/architecture.md) |

## Map of the library

A one-paragraph tour so the names below mean something when you meet them:

- **`SharedNT`** — a drop-in replacement for p4p's `SharedPV` that implements
  Normative Type logic (timestamps, alarms, control limits) for you. See
  [Building PVs](guide/building-pvs.md).
- **`PVRecipe`** — a small factory API for describing a PV in Python without
  hand-building the `NTScalar`/`NTEnum` structure. See
  [Building PVs](guide/building-pvs.md#pvrecipe).
- **YAML `config_reader`** — describe a whole set of PVs in a YAML file and let
  p4pillon build and serve them. See [Configuration files](guide/config-files.md).
- **`CompositeHandler` and `Rule`s** — the machinery that lets several handlers
  cooperate on one PV; how the NT logic is actually assembled, and how you
  extend it. See [Handlers and rules](guide/handlers-and-rules.md).
- **`IOCMimicServer` / `IOCMimicProvider` / `StaticRecordProvider`** — serve
  `RECORD.FIELD` sub-PVs (`RTYP`, `DTYP`, `SCAN`, `DESC`, …) the way a real IOC
  does, so tools that expect them keep working. See
  [Record fields](guide/record-fields.md).
- **`Server`** — a lifecycle wrapper that builds PVs from recipes and manages
  starting/stopping. See [Running a server](guide/server.md).

Everything above comes in **two concurrency flavors** — a thread-based one
(`p4pillon.thread.*`) and an asyncio one (`p4pillon.asyncio.*`). Which to pick,
and why the choice is load-bearing, is covered in
[Migrating from p4p](getting_started/migrating-from-p4p.md#choosing-a-flavor)
and in depth in [Concurrency](contributing/concurrency.md).

## Conventions in these docs

- Shell commands are shown with a `$` prompt. In this repository, prefix Python
  commands with `uv run` (e.g. `uv run python -m p4p.client.cli get demo:pv`) so
  they use the project environment.
- Every example in these docs was run against the current code before being
  written down; the command output shown is real output.
