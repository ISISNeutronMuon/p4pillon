---
title: p4p_ext
nav_order: 1
---

# p4p_ext
p4p_ext is a library written using [p4p](https://epics-base.github.io/p4p/) which implements the logic of Normative Types. This makes it easier to create PVA Servers, i.e. create PVs to report information to other EPICS tools or which take input from such a source. The PVs created using p4p_ext are able to apply control limits, trigger value alarms, etc.

It is recommended that developers have a basic understanding of a number of EPICS technologies before using this library. These include:
* EPICS, the pvAccess protocol, and Process Variables (PVs). A brief introduction to these topics is available in the [p4p overview](https://epics-base.github.io/p4p/overview.html).
* Normative Types, a brief introduction is provided here.
* [p4p](https://epics-base.github.io/p4p/index.html) - a Python implementation of the pvAccess protocol and Normative Type structures, amongst other things.

## Components 
p4p_ext provides the following user tools:

* SharedNT - provides a version of p4p's SharedPV that implements the logic of Normative Types through the use of p4p Handlers.
* PVRecipe - an alternative interface to generate PVs for use with a p4p Server.
* YAML Config Reader - generate PVs as defined in a YAML file. 

There are also some developer tools which may be useful outside of p4p:

* CompositeHandler - allows the use of multiple Handlers with the same p4p SharedPV or p4p_ext SharedNT.
* Rules - a specialised version of a Handler which makes common Handler patterns easier to implement.

## Warnings 
{: .warning }
> SharedNT is not an alternative to the Process Database implemented in a traditional EPICS IOC. Although the Normative Type logic is implemented, it does not implement locking. This means that in the case of multiple simultaneous updates it is possible for a PV to become inconsistent. At this time we suggest that the SharedNT code be used for rapid prototyping and systems where consistency/reliability are not critical.

## Installation
p4p_ext requires a version of p4p with [PR172](https://github.com/epics-base/p4p/pull/172). 