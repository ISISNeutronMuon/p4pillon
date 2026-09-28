# Concepts: EPICS, PVs, pvAccess and Normative Types

**Audience:** you are comfortable in Python but new to EPICS and p4p, and you
want to build a real application. This page gives you the vocabulary and mental
model the rest of the guide assumes. It is deliberately a conceptual overview,
not a specification — links point to the authoritative documents.

## EPICS in one paragraph

[EPICS](https://docs.epics-controls.org/) (Experimental Physics and Industrial
Control System) is a toolkit for building **distributed control systems** — the
software that runs particle accelerators, telescopes, and industrial plants. An
EPICS system is many programs on many machines talking over a network:
data sources (traditionally *IOCs*), operator screens (Phoebus, CS-Studio),
alarm handlers, archivers, gateways. p4pillon lets a **Python** program be one
of those data sources without writing a traditional IOC.

## The process variable (PV)

The central concept in EPICS is the **process variable**, or **PV**. A PV is a
single named value published on the network — a temperature, a motor position, a
pump's on/off state. It has:

- a **name** (e.g. `MYLAB:temperature`), unique across the control system;
- a **value** (a number, a string, an array, or an enumerated choice);
- and, usually, **metadata** travelling with the value: when it was measured
  (timestamp), whether it is in alarm, what units and display limits it has.

Clients **get** a PV's value, **put** a new value to it, or **monitor**
(subscribe to) it to receive every change. A server publishes PVs; a client
consumes them. p4pillon is a library for writing the **server** side in Python.

## The record — and why it is not the same as a PV

A **PV is just the network-visible value and its metadata**; it says nothing
about where the value comes from or what happens when it changes. In a
traditional EPICS server — an **IOC** (Input/Output Controller) — that behaviour
lives in a **record**.

A record is one entry in the IOC's **process database**, traditionally written
in a `.db` file. About the simplest useful one looks like this:

```
record(ai, "MYLAB:temperature") {
    field(DESC, "Chamber temperature")
    field(SCAN, "1 second")
    field(EGU,  "C")
    field(HIHI, "80")
}
```

That declares a record **named** `MYLAB:temperature` whose **type** is `ai`
(analog input). The type fixes what the record does and which **fields** it may
have — `ai`, `ao` (analog output), `calc` (calculation), and `bi` (binary
input) are a handful of dozens. The four fields shown are only a few of the many
an `ai` record owns: besides its value (`VAL`) and record type (`RTYP`), there
are input/output links, deadbands, further alarm limits, and many more. The
[EPICS Base documentation](https://docs.epics-controls.org/projects/base/en/latest/)
is the authoritative reference for the record types and the fields each defines.

Crucially a record is **active**: it *processes* — on a timer (the `SCAN` above
processes it once a second), on a hardware interrupt, or when a linked record
pushes it — and processing reads inputs, runs the record type's logic, evaluates
alarms, and drives outputs.

So the two concepts sit at different levels:

| | Record | PV |
| --- | --- | --- |
| What it is | An IOC database object with behaviour | A named value on the network |
| Owns | Many fields (`VAL`, `RTYP`, `SCAN`, …) and processing logic | One value plus metadata |
| Active? | Yes — it processes and drives other records | No — it is read/written by clients |
| Reachable on the network as | Its name, plus every field as a `NAME.FIELD` channel | Itself |

The link between them: an IOC makes the record's value reachable as a PV under
the record's name (`MYLAB:temperature`), and makes **each field individually
addressable** too — `MYLAB:temperature.DESC`, `MYLAB:temperature.SCAN`,
`MYLAB:temperature.RTYP`, and so on. One record, many PVs.

But those per-field channels are **hidden**: tools that list the names a server
offers (`pvlist`, a channel browser) show only the record's own name, never the
`.DESC`/`.SCAN`/`.RTYP` channels behind it. They are fully readable if you know
the field name to ask for, yet invisible if you are just browsing — which
catches people out the first time.

**p4pillon can present a PV as a record — but it does not *process* like one.**
A [`SharedNT`](building-pvs.md) carries the *metadata behaviour* a record gives
you (timestamps, alarms, limits — see [Normative Types](#normative-types) below),
and [`IOCMimicServer`](record-fields.md) serves the `RECORD.FIELD` channels
(`RTYP`, `SCAN`, `DESC`, …), so to a tool that asks for those fields a p4pillon
PV looks like a record. What is missing is the *active* half — nothing scans,
runs record-type logic, or follows links — so p4pillon reproduces the *shape* of
a record, not its processing.

## pvAccess (PVA)

**pvAccess** (often *PVA*) is the network protocol EPICS uses to move PVs
around. It handles three things:

1. **discovery** — a client that wants `MYLAB:temperature` broadcasts a
   search; whichever server hosts it answers. (This is why connection problems
   are often *discovery* problems — see [Network issues](../reference/network-issues.md).)
2. **transport** — getting, putting, and monitoring values over TCP.
3. **structured data** — unlike the older Channel Access protocol, pvAccess can
   carry arbitrarily nested structures, not just a bare scalar.

That third point is the enabler for the next concept. A brief protocol-level
introduction is in the [p4p overview](https://epics-base.github.io/p4p/overview.html).

## p4p

[p4p](https://epics-base.github.io/p4p/) ("Python for pvAccess") is a Python
binding to the pvAccess protocol and to the C++ [PVXS](https://mdavidsaver.github.io/pvxs/)
library underneath it. It gives you `SharedPV` (a server-side PV you publish),
`Server`, client `Context`s, and Python classes for the standard data
structures (`NTScalar`, `NTEnum`, …). **p4pillon is built on p4p** and reuses
all of it — servers, providers, client tools are p4p's. What p4pillon adds is
the *behaviour* of those data structures, which is the last concept.

## Normative Types

Because pvAccess can carry any structure, a server and a client must **agree**
on the layout of the data — which fields exist, in what order, with what names.
The [EPICS V4 Normative Types](https://github.com/epics-docs/epics-docs/blob/master/pv-access/Normative-Types-Specification.rst)
are that agreement: a small catalogue of standard structures for the most common
kinds of data, so that any compliant client understands any compliant server.

The one you will use most is the **NTScalar** — a single scalar value plus
optional metadata. Its definition is:

```
structure
    scalar_t    value
    string      descriptor  :opt
    alarm_t     alarm       :opt
    time_t      timeStamp   :opt
    display_t   display     :opt
    control_t   control     :opt
```

The `:opt` fields are optional, so the simplest legal NTScalar is just a
`value`. In practice you should **almost always** include at least a
`timeStamp`, so consumers know when a reading was taken and archivers can store
it correctly. Numeric NTScalars also commonly carry a `valueAlarm` sub-structure
(thresholds that decide when the `alarm` field trips).

Other Normative Types you will meet in this guide:

- **NTScalarArray** — the same idea, but `value` is an array (e.g. a waveform of
  temperatures).
- **NTEnum** — a value chosen from a fixed list of labelled choices (e.g.
  `["Off", "On"]`, or a set of city names). Prefer this over a bare boolean when
  the states have meaning, because the labels travel with the value.

### The gap p4pillon fills

Here is the crucial point for understanding p4pillon. p4p gives you the
Normative Type **structure** — an `NTScalar` really does have `alarm`,
`timeStamp`, `control` fields. Filling those fields in is left to the
application: p4p is a binding to the pvAccess protocol and its data structures,
and applying Normative Type *semantics* sits above that layer. So on a plain p4p
`SharedPV`, a declared `control.limitHigh` of 10 does not by itself keep a value
of 12.7 from being stored, and a `timeStamp` field stays at the epoch until your
code sets it. The structure is there; the behaviour is yours to add.

**p4pillon implements that logic.** Its [`SharedNT`](building-pvs.md) fills in
timestamps, trips alarms when thresholds are crossed, and clamps values to
control limits — automatically, from the fields you declared. The next page
shows how to build one.

> [!WARNING]
> This logic is real but not a substitute for an IOC's database consistency
> guarantees — see the warning on the [home page](../index.md) and the
> concurrency rules in [Updating PVs safely](updating-pvs.md).

## Where to go next

- [Building PVs](building-pvs.md) — create `SharedNT` PVs with alarms, control
  limits, display metadata; scalars, arrays and enums; and the `PVRecipe`
  factory.
- [Handlers and rules](handlers-and-rules.md) — how that NT logic is assembled,
  and how to extend it.
- [Record fields](record-fields.md) — make your PVs answer `RECORD.FIELD`
  queries like a real IOC.
