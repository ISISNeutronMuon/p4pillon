# Publish existing data as a PV

**Audience:** you have some data in a Python program — a reading from a sensor,
a number from a model, a status string — and you want it to appear on the
control system as a pvAccess PV so that tools like Phoebus, `pvget`, or an
archiver can see it. You do not want to learn much EPICS to do it.

This page gets you there with the shortest path p4pillon offers. When you want
to understand *why* any of it works, follow the links into [the guide](../guide/concepts.md).

## The whole thing in one file

```python
from p4p.nt import NTScalar

from p4pillon.thread.sharednt import SharedNT
from p4pillon.server.records import IOCMimicServer

# 1. Wrap each piece of data in a PV. NTScalar("d") = a double; use
#    "i" for an integer, "s" for a string. SharedNT is p4pillon's PV type:
#    it fills in timestamps (and, if you declare them, alarms/limits) for you.
pvs = {
    "MYLAB:temperature": SharedNT(nt=NTScalar("d"), initial=21.5),
    "MYLAB:status": SharedNT(nt=NTScalar("s"), initial="idle"),
}

# 2. Serve them. IOCMimicServer is a drop-in p4p Server that also answers
#    the RECORD.FIELD queries (RTYP, DTYP, NAME, ...) tools expect from a
#    real IOC — see below.
with IOCMimicServer(providers=[pvs]):
    print("Serving:", ", ".join(pvs))
    input("Press Enter to stop...\n")
```

Run it (inside this repository, use `uv run`):

```console
$ uv run python publish.py
Serving: MYLAB:temperature, MYLAB:status
Press Enter to stop...
```

Leave it running and, in another terminal, read the PVs with any pvAccess
client:

```console
$ uv run python -m p4p.client.cli get MYLAB:temperature MYLAB:status
MYLAB:temperature Sun Jul 19 10:18:27 2026 21.5
MYLAB:status Sun Jul 19 10:18:27 2026 idle
```

That is the whole job: your data is now on the control system.

## Pushing new values

When your data changes, call `post()` on the PV. Keep a reference to it:

```python
temperature = SharedNT(nt=NTScalar("d"), initial=21.5)
pvs = {"MYLAB:temperature": temperature}

with IOCMimicServer(providers=[pvs]):
    while True:
        temperature.post(read_my_sensor())  # your existing code
        time.sleep(1)
```

Each `post()` updates every subscribed client and stamps the current time on
the value automatically.

> [!IMPORTANT]
> The `post()` call above is on the **thread** flavor of `SharedNT`
> (`p4pillon.thread`), and here it runs from your own loop thread, which
> is fine. If you ever call `post()` on a PV from *inside a handler* or from the
> asyncio flavor, the rules change — see
> [Updating PVs safely](../guide/updating-pvs.md). For simply pushing values
> from your main loop, as above, there is nothing more to know.

## What "IOC mimic" buys you

Beyond the value itself, `IOCMimicServer` also answers the `RECORD.FIELD`
queries a real IOC exposes — `.RTYP`, `.DTYP`, `.NAME`, `.SCAN`, `.DESC` — which
some client tools require and a plain p4p server doesn't serve. It builds them on
demand with sensible defaults inferred from each PV, so you get them for free.
See [Record fields](../guide/record-fields.md) to override them per PV or
understand the trade-offs.

## Alarms and limits

Because these PVs are `SharedNT`, timestamps are already handled for you. To make
a value raise alarms when it crosses a threshold, or clamp itself to control
limits, declare those fields — see [Migrating from p4p](migrating-from-p4p.md)
and [Building PVs](../guide/building-pvs.md).

## Where to go next

- [Migrating from p4p](migrating-from-p4p.md) — add alarms and control limits by
  declaring `SharedNT`'s fields.
- [Record fields](../guide/record-fields.md) — per-PV field overrides, the
  eager vs lazy trade-off, and `RECORD.FIELD$` long-string aliases.
- [Running a server](../guide/server.md) — managing PV lifecycles beyond a
  single `with` block.
