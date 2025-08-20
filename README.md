# p4p_ext
Opinionated extensions and additional functionality for the p4p library.

[![p4p_ext](https://github.com/ISISNeutronMuon/p4p_ext/actions/workflows/build.yaml/badge.svg)](https://github.com/ISISNeutronMuon/p4p_ext/actions/workflows/build.yaml)

### Python Version
These extensions make extensive use of typing. As such they require Python 3.9 or later.

### p4p Version
These extensions require a version of p4p with [PR172](https://github.com/epics-base/p4p/pull/172). This will be installed as a dependency with the package, but note there is a potential for conflict with other installed instances.

## Extensions
### NT Logic
> [!CAUTION]
> This is not an alternative to the Process Database implemented in a traditional EPICS IOC. Although the Normative Type logic is implemented, it does not implement locking. This means that in the case of multiple simultaneous updates it is possible for a PV to become inconsistent. At this time we suggest that the NT Logic code be used for rapid prototyping and systems where consistency/reliability are not critical.

Implements the logic of Normative Types (specifically NTScalars and NTScalarArrays) using handlers.
 
### CompositeHandler
The base version of p4p only allows a single Handler class to be associated with a SharedPV. This makes it complex to combine multiple handlers from different sources. It also means that if a Handler is used to handle NormativeType logic then it either precludes a user handler or requires subclassing.

The supplied CompositeHandler has the same interface as the base Handler. It uses an OrderedDict to store componenent Handlers (standard Handlers, per base p4p) and calls them in the specified order.

It is designed to work with the Handler class, and is **not** designed to work with the Handler decorators.