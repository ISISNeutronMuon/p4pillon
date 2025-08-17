# p4p_ext
p4p_ext is a library written using [p4p](https://epics-base.github.io/p4p/) which implements the logic of Normative Types. This makes it easier to create PVA Servers, i.e. create PVs to report information to other EPICS tools or which take input from such a source. The PVs created using p4p_ext are able to apply control limits, trigger value alarms, etc.

It is recommended that developers have a basic understanding of a number of EPICS technologies before using this library. These include:
* EPICS, the pvAccess protocol, and Process Variables (PVs). A brief introduction to these topics is available in the [p4p overview](https://epics-base.github.io/p4p/overview.html).
* Normative Types, a brief introduction is provided here.
* [p4p](https://epics-base.github.io/p4p/index.html) - a Python implementation of the pvAccess protocol and Normative Type structures, amongst other things.
