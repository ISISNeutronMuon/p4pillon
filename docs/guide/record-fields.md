# Record fields

A real EPICS IOC serves more than a record's value. Ask an IOC for
`RECORD.RTYP` and it tells you the record *type*; `RECORD.SCAN`, `RECORD.DESC`,
`RECORD.NAME`, and the other fields common to every record are all reachable as
their own channels. Some client tools rely on this. A plain p4p server serves
only the base PV. p4pillon can serve these `RECORD.FIELD` **sub-PVs** too, so
your Python server behaves like an IOC to tools that expect one.

This page covers the three ways to do that and when to pick each. For the
"I just want it to work" case, [Publish existing data](../getting_started/publish-existing-data.md)
already showed the shortest path; here is the whole picture.

## What gets served

For a base PV named `EXAMPLE:PV`, p4pillon can serve the fields from
`dbCommon.dbd` (the fields every EPICS record shares) plus `RTYP`, `DTYP`, and
`NAME` — for example `EXAMPLE:PV.SCAN`, `EXAMPLE:PV.STAT`, `EXAMPLE:PV.DESC`.
Defaults follow [EPICS Base](https://docs.epics-controls.org/projects/base/en/latest/):

- **menu fields** (`SCAN`, `PINI`, `STAT`, `SEVR`, …) start at the same choice a
  freshly initialised record would have;
- **`RTYP`** is *inferred* from the base PV's value type (the full mapping is in
  the table below). The guess always picks the *input*-side record type — `ai`
  not `ao`, `bi` not `bo`, `mbbi` not `mbbo` — since a served PV is fundamentally
  a value to read; pass an explicit `RTYP` to choose otherwise. Non-scalar PVs
  (tables, images) have no sensible guess: they are served on their own with
  *no* sub-PVs — as a real IOC serves a group — unless you supply an explicit
  `RTYP`;
- **`DTYP`** defaults to `Soft Channel`;
- **`DESC`** mirrors the base PV's `display.description`;
- **`ADEL`/`MDEL`** (deadbands) appear only for the numeric scalar record types
  that really have them.

The full value-type → `RTYP` mapping:

| Base PV value type | Inferred `RTYP` |
| --- | --- |
| `double` / `float` | `ai` |
| 8-, 16-, or 32-bit integer | `longin` |
| 64-bit integer | `int64in` (holds the full 64 bits; a `longin`'s 32-bit `VAL` would truncate) |
| boolean | `bi` |
| string | `stringin` |
| array (any element type) | `waveform` |
| `NTEnum` (a value chosen from a labelled list) | `mbbi` |
| anything else (`NTTable`, `NTNDArray`, …) | *none* — the base PV is served alone, unless you supply an explicit `RTYP` to force record treatment |

Every string-valued field is *also* servable with a `$` suffix
(`EXAMPLE:PV.DESC$`), mirroring the IOC long-string convention. In pvAccess this
is simply an identical-valued alias (pvAccess has no 40-character string limit
to work around), provided for tools that ask for it.

Verified against `examples/asyncio/ioc_fields_server.py`:

```console
$ uv run python -m p4p.client.cli get EXAMPLE:PV.RTYP EXAMPLE:PV.DTYP EXAMPLE:PV.NAME EXAMPLE:PV.SCAN EXAMPLE:PV.DESC
EXAMPLE:PV.RTYP  'ai'
EXAMPLE:PV.DTYP  Soft Channel
EXAMPLE:PV.NAME  'EXAMPLE:PV'
EXAMPLE:PV.SCAN  1 second
EXAMPLE:PV.DESC  'An example ai-like record'
```

## Option 1 — `IOCMimicServer` with a plain dict (simplest)

Drop-in replacement for p4p's `Server`. Any `{name: pv}` dict in `providers=`
gets its sub-PVs served automatically, with the defaults above:

```python
from p4p.nt import NTScalar
from p4pillon.server.thread import SharedPV
from p4pillon.server.records import IOCMimicServer

pvs = {"DEV:PV1": SharedPV(nt=NTScalar("d"), initial=0.0)}

with IOCMimicServer(providers=[pvs]):
    ...  # DEV:PV1, and DEV:PV1.RTYP / .SCAN / .DESC / ... are all served
```

Use this when the inferred defaults are fine — which is most of the time.

## Option 2 — `IOCMimicProvider` (per-PV overrides)

When you need to override a field for a specific PV — a particular `RTYP`, a
custom `DTYP` menu, an explicit `SCAN` — build an `IOCMimicProvider` and use
`add()`:

```python
from p4pillon.server.records import IOCMimicProvider, IOCMimicServer

base = IOCMimicProvider("base")
base.add(
    "EXAMPLE:PV",
    SharedPV(
        nt=NTScalar("d", display=True),
        initial={"value": 1.234, "display": {"description": "An example ai-like record"}},
    ),
    dtyp_choices=["Soft Channel", "Raw Soft Channel"],
    fields={"SCAN": "1 second"},
)

with IOCMimicServer(providers=[base]):  # pass it directly; the server unpacks it
    ...
```

`add()` takes the base PV plus optional `valtype`, `dtyp_choices`, `fields`
overrides, and `record_fields=False` to add a PV with **no** sub-PVs. It also has
`set_desc_record(name, text)` to pin an explicit `DESC`, and `remove(name)`.
`IOCMimicProvider` and a plain dict can be mixed in the same `providers=` list.

## Option 3 — `StaticRecordProvider` (eager)

Both options above are **lazy**: each sub-PV is built the first time a client
connects to it, from a registry. `StaticRecordProvider` is the **eager**
alternative — it builds every sub-PV up front when you `add()` the base PV. The
difference has real consequences:

| | Lazy (`IOCMimicServer`/`Provider`) | Eager (`StaticRecordProvider`) |
| --- | --- | --- |
| Sub-PVs built | on first client connect | up front, at `add()` |
| Visible in `pvlist` / channel-list | **no** | **yes** |
| Sub-PV concurrency flavor | always thread `SharedPV` | matches the base PV's flavor |
| `DESC` tracks later `display.description` changes | for *new* connections (re-read per connect) | one-time snapshot (call `set_desc_record` to push an update) |
| `set_desc_record` pushes to already-open connections | no (new connections only) | yes |

Choose `StaticRecordProvider` when you need sub-PVs to show up in a
channel-list query, need the sub-PVs to match an asyncio base PV's flavor, or
need `DESC` updates pushed live to open connections. Otherwise the lazy path is
recommended — it is lighter and needs no up-front enumeration. p4pillon's package
documentation states this preference explicitly: **use `IOCMimicProvider` /
`IOCMimicServer` unless you have a specific reason to use
`StaticRecordProvider`.**

## What is *not* served

Fields with no independent external representation on a real IOC are
deliberately omitted — the `DBF_NOACCESS` internals (`MLOK`, `MLIS`, `RSET`,
`DSET`, …) and `TIME` (reachable only via `DBR_TIME_*` requests, never as
`RECORD.TIME`). This matches real IOC behaviour.

## Where to go next

- [Publish existing data](../getting_started/publish-existing-data.md) — the
  quick-start use of `IOCMimicServer`.
- [Running a server](server.md) — other server options.
- [EPICS Base — record reference](https://docs.epics-controls.org/projects/base/en/latest/) —
  the authoritative definitions of `dbCommon`, the record types, and the fields
  p4pillon mimics here.
