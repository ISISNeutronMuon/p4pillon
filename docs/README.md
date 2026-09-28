# p4pillon docs

Start at **[index.md](index.md)** — it routes you to the right page for what
you're trying to do. The full tree:

- **[index.md](index.md)** — overview, install, "start here" routing.
- **Getting started**
  - [Publish existing data](getting_started/publish-existing-data.md) — put data you already have on the control system, minimal EPICS knowledge.
  - [Migrating from p4p](getting_started/migrating-from-p4p.md) — `SharedPV` → `SharedNT`; "I just want timestamps to work".
- **Guide** (build a real application)
  - [Concepts](guide/concepts.md) — EPICS, PVs, pvAccess, Normative Types.
  - [Building PVs](guide/building-pvs.md) — `SharedNT`, alarms/control/display, arrays, enums, `PVRecipe`.
  - [Handlers and rules](guide/handlers-and-rules.md) — how the NT logic is assembled and extended.
  - [Updating PVs safely](guide/updating-pvs.md) — `post()` vs `post_deferred()`, polling vs handlers.
  - [Configuration files](guide/config-files.md) — describe PVs in YAML.
  - [Record fields](guide/record-fields.md) — serve `RECORD.FIELD` like an IOC.
  - [Running a server](guide/server.md) — server options and lifecycle.
- **Contributing**
  - [Architecture](contributing/architecture.md) — module map and design decisions.
  - [Concurrency](contributing/concurrency.md) — the threading/asyncio model and its invariants.
  - [Concurrency tutorial](design/dispatch_fix.md) — from-first-principles deep dive.
- **Reference**
  - [Network and discovery issues](reference/network-issues.md) — troubleshooting connections.

Every example in these pages was run against the current code before being
documented; shown output is real.
