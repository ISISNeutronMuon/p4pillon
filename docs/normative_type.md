# Normative Types
The intention of this page is to give a beginner's guide to Normative Types. See the [EPICS V4 Normative Types](https://github.com/epics-docs/epics-docs/blob/master/pv-access/Normative-Types-Specification.rst) specification for a full and definitive treatment.

## What is a Normative Type?
EPICS Version 4 defined a new protocol called [pvAccess](https://docs.epics-controls.org/en/latest/pv-access/protocol.html) (often abbreviated PVA) for exchanging information between EPICS devices, e.g. between IOCs and client software such as Phoebus. This protocol covers discovery of PVs, reading and setting values, subscribing to value changes (i.e. monitor), etc. We won't go into more detail here, except to note that the protocol is very flexible in what data may be exchanged, allowing developers to exchange whatever binary data they wish.

This flexibility means that a server (e.g. an IOC providing PVs) and a client (e.g. Phoebus which displays PVs) must agree the format in which they will exchange data. Normative Types provide a standard definition of what format will be used for exchange of the most commonly used types of data. Note that there are several different Normative Types, and which one is appropriate depends on the type of data is being exchanged.

The pvAccess protocol defines *how* the data will be exchanged, the Normative Type defines the format in which the data is exchanged, i.e. *what* kind of data is exchanged. Alternatively, the Normative Type defines the structure of the data payload.

## What is a Normative Type (part 2)?
Previously we've looked at why we need a Normative Type and what purpose they serve. But what is a Normative Type from a more technical perspective? Let's take a look at one of the more commonly used Normative Types, the NTScalar. An NTScalar is used to exchange data where the value of a PV may be represented by a single scalar number, e.g. an integer or a floating point number. 

Here's how an NTScalar is defined in the EPICS V4 Normative Types specification:
```
structure
    scalar_t    value
    string      descriptor  :opt
    alarm_t     alarm       :opt
    time_t      timeStamp   :opt
    display_t   display     :opt
    control_t   control     :opt
```
The fields (subcomponents of the structure) marked with `:opt` are optional, so the simplest possible NTScalar is simply:
```
structure
    scalar_t    value
```
which is what we expect! A single value.

However, this isn't quite correct. A `scalar_t` is actually "a simple numerical, boolean, or string value". So, an NTScalar may contain a single string (which is regarded as a single value).

Note, that often numeric versions of a NTScalar will include a valueAlarm field. It is not clear why this is not included in the list of optional fields above.

### The Other Fields
In practice, you should almost never use an NTScalar without any of the optional fields. At a minimum you should include a `timeStamp` field so that it's possible to see when a reading was made, or a command sent, and to allow correct archiving.


