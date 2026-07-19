# Configuration files

For a fixed set of PVs, describing them in a **YAML file** is often clearer than
building each one in Python. p4pillon's `config_reader` parses such a file into
[`PVRecipe`](building-pvs.md#pvrecipe) objects and, given a [`Server`](server.md),
builds and serves them. This is the most declarative way to stand up a server.

## A complete example

```yaml
# pvs.yaml
DEV:RW:INT1:
  description: "An example integer PV"
  type: "INTEGER"
  initial: 2

DEV:RW:DOUBLE1:
  description: "A double with display, control and alarm limits"
  type: "DOUBLE"
  initial: 17.5
  display:
    units: "mbar"
    precision: 3
  control:
    low: 1
    high: 20
  valueAlarm:
    low_warning: 2
    high_alarm: 9

DEV:RO:STATUS:
  description: "A read-only string"
  type: "STRING"
  initial: "idle"
  read_only: True
```

Load and serve it:

```python
import time
from p4pillon import config_reader
from p4pillon.thread.server import Server

server = Server(prefix="")
config_reader.parse_config_file("pvs.yaml", server)   # builds + registers each PV
server.start()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    server.stop()
```

`parse_config_file` returns a dict of recipes and, because a `server` was
passed, also adds each PV to it. (Use `parse_config_string` to parse YAML from a
string, or call either without a server to just get the recipes.) The
`Server(prefix=...)` argument prepends a common prefix to every PV name — handy
for namespacing a whole file under, say, `DEV:`.

## Schema reference

Each top-level key is a **PV name**. Its value is a mapping:

| Key | Required | Meaning |
| --- | -------- | ------- |
| `type` | **yes** | `DOUBLE`, `INTEGER`, `STRING`, or `ENUM` |
| `description` | **yes** | human-readable description (becomes `display.description`) |
| `initial` | no* | initial value; a list makes it an array |
| `array_size` | no | for a fixed-size array without listing values (defaults each element to 0 / "") |
| `read_only` | no | `True` rejects client puts |
| `display` | no | `units`, `format`, `precision`, `low`, `high` |
| `control` | no | `low`, `high`, `min_step` |
| `valueAlarm` | no | `low_warning`, `high_warning`, `low_alarm`, `high_alarm` |
| `calc` | no | `calc_str` and `variables` for a computed PV (see below) |

\* `initial` may be omitted for numeric and string PVs (defaults to `0` / `""`);
an `ENUM` always needs an explicit initial value.

Omitting `type` or `description` raises a `SyntaxError` naming the offending PV —
these are the two things every PV must declare.

The `display`/`control`/`valueAlarm` sub-mappings are passed straight through to
the recipe's `set_display_limits`/`set_control_limits`/`set_alarm_limits`
methods, so their keys match those method parameters (see
[PVRecipe](building-pvs.md#pvrecipe)).

## Computed PVs (`calc`)

A `calc` block turns a PV into one whose value is recomputed from other PVs
(via the [`CalcRule`](handlers-and-rules.md#the-calcrule-pvs-computed-from-other-pvs)):

```yaml
DEV:RW:INT3:
  description: "First input"
  type: "INTEGER"
  initial: 0

DEV:RW:INT4:
  description: "Second input"
  type: "INTEGER"
  initial: 0

DEV:RW:DOUBLECALC:
  description: "A computed value"
  type: "DOUBLE"
  initial: 0.0
  calc:
    calc_str: "pv[0] + 2.12*pv[1]"
    variables: ["DEV:RW:INT3", "DEV:RW:INT4"]
```

`calc_str` is an expression where `pv[i]` refers to the *i*-th name in
`variables`. When either input changes, the computed PV updates. Verified live
against this exact configuration: putting `INT3=1` and `INT4=1` makes
`DOUBLECALC` become `1 + 2.12*1 = 3.12`. (The `config_reader` wires the running
`server` into the `calc` rule automatically so it can read the input PVs.)

## Where to go next

- [Building PVs](building-pvs.md) — the recipe API a YAML file maps onto.
- [Running a server](server.md) — the `Server` object used above and its
  lifecycle.
- [Handlers and rules](handlers-and-rules.md) — what `CalcRule` and the other
  rules do.
