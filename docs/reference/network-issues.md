# Network and discovery issues

An EPICS control system is many
[distributed components](https://docs.epics-controls.org/en/latest/software/epics-related-software.html)
talking over a network — servers that publish PVs (IOCs, or your p4pillon
program), operator screens (Phoebus / CS-Studio), alarm handlers, archivers, and
gateways. The pvAccess protocol both **transports** PV values and **discovers**
which server hosts which PV. When something can't connect, the cause is often the
*discovery* step, not the transport — and the symptoms are easy to misread. This
page is a practical troubleshooting guide.

## Symptoms

You have a server (a p4pillon program or an IOC) and a client (`pvget`, Phoebus,
or `uv run python -m p4p.client.cli get <pv>`). Both look healthy, yet the client
reports a **`Timeout`** fetching a PV. Crucially, this is the *same* error you get
for a PV that simply doesn't exist — so a timeout tells you "couldn't reach it",
not *why*.

A classic tell: everything works in local development, then clients can't reach
the server once it's deployed to another host, container, or subnet. That points
at discovery or firewalling rather than your code.

## Gathering the network facts

Most diagnosis needs the IP address and netmask of both the server host and the
client host. The quickest cross-platform way is this small script (run it on
each host, or fold it into your server's start-up logging):

```python
# /// script
# dependencies = ["psutil"]
# ///
import socket
import psutil

for iface, addrs in psutil.net_if_addrs().items():
    for a in addrs:
        if a.family == socket.AddressFamily.AF_INET:
            print(f"{iface:<30}: {a.address} / {a.netmask} / {a.broadcast}")
        elif a.family == socket.AddressFamily.AF_INET6:
            print(f"{iface:<30}: {a.address}")
```

It prints one line per address:

```
Ethernet                      : 169.254.3.56 / 255.255.0.0 / None
WiFi                          : 192.168.1.107 / 255.255.255.0 / None
```

(IPv6 addresses have no netmask/broadcast attributes.) The OS tools `ipconfig`
(Windows) and `ifconfig` / `ip addr` (Linux, macOS) give the same information.

## Step 1 — is the server reachable at all?

First confirm the server process is up and reachable on the network, separately
from any PV question. Identify the server host's IP (above), then try to open a
TCP connection to it on **port 5075** — the default pvAccess TCP port.

`telnet` is one way (though not installed by default on most systems):

```console
$ telnet 192.168.1.50 5075
Trying 192.168.1.50...
Connected to server.example.
Escape character is '^]'.
�A�@D   anonymousca^]
```

The garbage plus `anonymousca` means an EPICS server answered — the transport
path is fine. If you get *nothing*, the possibilities are:

- the server isn't actually running, or is on a non-standard port (check its
  start-up logs);
- there is no network path between the two hosts (physical, routing, or VLAN);
- a firewall is blocking the connection.

## Step 2 — is it a discovery problem?

If Step 1 connects but PV gets still time out, discovery is the likely culprit.
pvAccess discovery uses UDP broadcasts by default, and broadcasts do not cross
subnet boundaries. Compare the two hosts' IP/netmask (from the script above):

- **Same subnet** (their network portions match under the shared netmask):
  broadcast discovery should work; suspect a firewall blocking UDP, or a host
  with multiple interfaces broadcasting on the wrong one.
- **Different subnets:** broadcast discovery will not reach the server. You need
  to tell the client where to look explicitly, via the
  **`EPICS_PVA_ADDR_LIST`** environment variable (the server's IP address), and
  usually set **`EPICS_PVA_AUTO_ADDR_LIST=NO`** so the client uses only your
  list. A [PVA Gateway](https://mdavidsaver.github.io/p4p/gw.html) is the
  standard solution for bridging subnets in a larger deployment.

Multi-homed server hosts (several network interfaces — common with containers,
VPNs, or `169.254.x.x` link-local addresses alongside a real one) are a frequent
cause: the server may announce itself on an interface the client can't route to.
Binding the server to the correct interface, or setting the appropriate
`EPICS_PVA*` address environment variables, resolves it.

## Quick checklist

1. Server process running? Check its logs for the port it bound.
2. `telnet <server-ip> 5075` connects? If not → process/network/firewall.
3. Client and server on the same subnet? If not → set `EPICS_PVA_ADDR_LIST`
   (and `EPICS_PVA_AUTO_ADDR_LIST=NO`), or use a gateway.
4. Server host multi-homed? Ensure it announces on the reachable interface.
5. UDP broadcast blocked by a firewall? Allow it, or use an explicit address
   list.

## See also

- [EPICS pvAccess protocol](https://docs.epics-controls.org/en/latest/pv-access/protocol.html)
- [p4p PVA Gateway](https://mdavidsaver.github.io/p4p/gw.html)
- [Concepts: pvAccess](../guide/concepts.md#pvaccess-pva) for how discovery fits
  into the protocol.
