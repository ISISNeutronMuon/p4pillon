---
title: Network and Discovery Issues
---

# Network Connection and Discovery Issues
An EPICS control system is made of [many distributed components](https://docs.epics-controls.org/en/latest/software/epics-related-software.html), for example:

- [IOC](https://docs.epics-controls.org/en/latest/appdevguide/gettingStarted.html)s or p4pillon programs that create PVs and manage the interfaces to hardware or ML models.
- Programs such as [Phoebus / CS-Studio](https://control-system-studio.readthedocs.io/en/latest/index.html), [EDM](https://controlssoftware.sns.ornl.gov/edm/), or [React Automation Studio](https://github.com/React-Automation-Studio/React-Automation-Studio) that present human-machine interfaces (HMIs), allowing operators to control remote systems. 
- Alarm handlers and viewers.
- Data archiving tools, e.g. [EPICS Archiver Appliance](https://epicsarchiver.readthedocs.io/).
- Gateways, such as [PVA Gateway](https://mdavidsaver.github.io/p4p/gw.html) (a part of p4p).

The pvAccess protocol is used to communicate between these services running on a myriad of systems connected via a network. What is less obvious is that the pvAccess protocol also manages discovery of PVs. You may encounter issues when this discovery process breaks down. 

## Symptoms of Connection and Disovery Issues
You have a server (e.g a p4pillon program or IOC) and a client (e.g. `python -m p4p.client.cli get <pv>`, Phoebus, `pvget`, etc.). Although both the server and client appear to be working correctly, the client reports a `Timeout` when attempting to retrieve values from a PV on the server. This is the same error reported when attempting to retrieve values from a PV that definitely does not exist.

Often the problem occurs in deployment. Everything works as expected in the local development environment, but clients cannot connect to the server in deployment.

### Diagnostics from Python 
The next sections require diagnostic network data from the service / server hosting the PVs. The easiest way to provide this may be to include it in the log output from your code on startup. The following simple script will print the required information and may be easily adapted 
```py
# /// script
# dependencies = [
#   "psutil",
# ]
# ///

import socket

import psutil

ifaces = psutil.net_if_addrs()
for iface, snicaddrs in ifaces.items():
    for snicaddr in snicaddrs:
        if snicaddr.family == socket.AddressFamily.AF_INET:
            print(f"{iface:<30}: {snicaddr.address} / {snicaddr.netmask} / {snicaddr.broadcast}")
        elif snicaddr.family == socket.AddressFamily.AF_INET6:
            print(f"{iface:<30}: {snicaddr.address}")
```
This script produces output of the form:
```console
Adapter                       : IP address / Netmask / Broadcast
```

```console
Ethernet                      : 169.254.3.56 / 255.255.0.0 / None
Ethernet                      : d3ad::b33f:dd67:57a6:9023
WiFi                          : 192.168.1.107 / 255.255.255.0 / None
WiFi                          : d3ad::b33f:3af1:c3ea:f2e7
```
Note, IPv6 addresses do not have netmask or broadcast attributes.

## Confirming Network Connectivity Issues
The first step is to confirm that the server or service is running and reachable via the network. A full treatment of this topic is outside the scope of this document, but some simple steps may be used to test. First of all, you must identify the IP address hosting the server program or service. How to do this will depend on your operating system and environment (is the service running in a virtual environment, container, etc.)

You may use the script above to do so. 


On Windows, you can use a tool such as `ipconfig` on the command line, which will produce output such as:
```
Wireless LAN adapter WiFi:

   Connection-specific DNS Suffix  . : home
   Link-local IPv6 Address . . . . . : d3ad::b33f:3af1:c3ea:f2e7%19
   IPv4 Address. . . . . . . . . . . : 192.168.1.107
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . : 192.168.1.254
```
On Linux and MacOs you may use the `ifconfig` tool or equivalent to show IP address on the command line:
```
eth0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        inet 172.29.208.153  netmask 255.255.240.0  broadcast 172.29.223.255
        inet6 d3ad::b33f:5dff:fe1a:ded7  prefixlen 64  scopeid 0x20<link>
        ether 00:15:5d:1a:de:d7  txqueuelen 1000  (Ethernet)
        RX packets 1885  bytes 8419694 (8.4 MB)
        RX errors 0  dropped 0  overruns 0  frame 0
        TX packets 1106  bytes 89713 (89.7 KB)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0
```

Once you have determined the IP address of the service host, attempt to connect to that IP address on port 5075. (Port 5075 is the default TCP port for EPICS pvAccess protocol services.)

One way of doing so is to use telnet, as shown below. Unfortunately, telnet is not installed by default on most operating systems. 
```console
$ telnet 1.2.3.4 5075
Trying 130.246.91.243...
Connected to porthos.isis.rl.ac.uk.
Escape character is '^]'.
�A�@D   anonymousca^]
```
The important result is `anonymousca` on the last line. This shows that there is an EPICS server awaiting a connection at that IP address and port.

If you do not receive a result like that shown above there are a number of possibilities:

- The service is not in fact running, or is using non-standard port numbers. Check your log messages.
- No network connection exists between your machine and the remote service. This could be due to physical disconnection, or network configuration.
- One or other connections may be blocked by a firewall.

## Confirming PV Discovery Issues
To simplest way to determine whether the issue is with pvAccess protocol discovery is to determine the IP address and netmask of both the service / server and client having connection issues. You may determine this information using the tools discussed in the previous sections. 


