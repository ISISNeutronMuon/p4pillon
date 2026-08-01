# Running a server

You have PVs; something has to publish them and manage their lifetime. There are
three server options in play, and it helps to know which is which.

| Server | When to use |
| ------ | ----------- |
| p4p's `Server` / `Server.forever` | quickest for a fixed set of PVs; used throughout the getting-started pages |
| p4pillon's `Server` | you build PVs from [recipes](building-pvs.md#pvrecipe) or [YAML](config-files.md), or you add/remove PVs at runtime |
| [`IOCMimicServer`](record-fields.md) | you also want `RECORD.FIELD` sub-PVs |

The first is just p4p and documented in the
[p4p server docs](https://epics-base.github.io/p4p/server.html); a `SharedNT`
works anywhere a `SharedPV` does. This page covers p4pillon's own `Server`.

## p4pillon's `Server`

`p4pillon.thread.server.Server` (and its asyncio counterpart) is a lifecycle
wrapper that owns a provider, builds PVs from recipes lazily, and lets you
start and stop cleanly. Import the flavor matching your PVs.

```python
import time
from p4pillon.definitions import PVTypes
from p4pillon.thread.pvrecipe import PVScalarRecipe
from p4pillon.thread.server import Server

server = Server(prefix="DEV:")  # prepended to every PV name

recipe = PVScalarRecipe(PVTypes.DOUBLE, "A pressure reading", initial_value=1.0)
recipe.set_control_limits(low=0, high=10)
server.add_pv("pressure", recipe)  # served as DEV:pressure

server.start()  # PVs are opened & timestamped here
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    server.stop()  # closes PVs and stops the server
```

### What it gives you

- **`prefix`** — a common string prepended to every PV name, so a whole server
  can be namespaced (`DEV:`, `MYLAB:`, …). Names you pass that already start with
  the prefix are left as-is.
- **Deferred opening** — PVs are `open()`ed (and thus first timestamped) at
  `start()`, not when added. This means the timestamp reflects when the server
  actually went live.
- **`add_pv(name, pv)` / `remove_pv(name)`** — accept either a built
  `SharedNT`/`SharedPV` **or** a `PVRecipe` (which it builds via `create_pv()`).
  Called while the server is running, they add/remove PVs from the live system.
- **`start()` / `stop()`** — manage the underlying p4p `Server` and open/close
  every PV.
- **`pvlist`** — the names currently managed.
- **`get_pv_value(name)` / `put_pv_value(name, value)`** — read or write a PV. If
  the name is served by *this* server it uses the `SharedPV` directly; otherwise
  it falls back to a pvAccess client `Context`, so the same call works for PVs
  hosted elsewhere on the network.

### With YAML

The [`config_reader`](config-files.md) pairs directly with this `Server`: pass
the server to `parse_config_file` and every PV in the file is built and
registered for you.

```python
from p4pillon import config_reader
from p4pillon.thread.server import Server

server = Server(prefix="DEV:")
config_reader.parse_config_file("pvs.yaml", server)
server.start()
```

Verified: serving `examples/basic_server_recipe.yaml` this way makes
`DEV:RW:INT`, `DEV:RW:INT1`, and the computed `DEV:RW:DOUBLECALC` reachable, and
the `calc` rule recomputes on input changes.

## Where to go next

- [Building PVs](building-pvs.md) — the recipes this server builds.
- [Configuration files](config-files.md) — serve a whole file of PVs.
- [Record fields](record-fields.md) — `IOCMimicServer`, if you want
  `RECORD.FIELD` too.
