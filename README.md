# p4p_ext
Extensions to the [p4p](https://epics-base.github.io/p4p/) [Server API](https://epics-base.github.io/p4p/server.html), to aid in creation and managment of PVAccess servers.  

[![p4p_ext](https://github.com/ISISNeutronMuon/p4p_ext/actions/workflows/build.yaml/badge.svg)](https://github.com/ISISNeutronMuon/p4p_ext/actions/workflows/build.yaml)

## Installation
> [!NOTE]
> Installation via pip is not yet enabled.

p4p_ext may be installed via 
```console
pip install p4p-ext
```

### Python Version
These extensions make extensive use of typing. As such they require Python 3.10 or later.

## Documentation
Documentation intended for developers using the library is available.  

### Extensions
A brief overview of the components of the library.

#### NT Logic
> [!CAUTION]
> This is not an alternative to the Process Database implemented in a traditional EPICS IOC. Although the Normative Type logic is implemented, it does not implement locking. This means that in the case of multiple simultaneous updates it is possible for a PV to become inconsistent. At this time we suggest that the NT Logic code be used for rapid prototyping and systems where consistency/reliability are not critical.

The `SharedNT` class, derived from p4p's `SharedPV` class, automatically implements the logic of Normative Types (at this time NTScalars and NTScalarArrays) using handlers. It is possible, with the `CompositeHandler` class to 
 
#### CompositeHandler and Rules
p4p only allows a single Handler class to be associated with a SharedPV. To make it easier to combine or share handlers from multiple sources a `CompositeHandler` class is provided. The supplied `CompositeHandler` has the same interface as the base `Handler`. It uses an OrderedDict to store componenent `Handler`s (standard `Handler`s, per base p4p), call them in the specified order, and allow the component `Handler`s to be accessed through the OrderedDict interface.

It is designed to work with the Handler class, and is **not** designed to work with the `Handler` decorators.

`Rule`s are component `Handlerrs` used with the `CompositeHandler` used to implement the NT Logic discussed above. The `Rule` class is derived from the `Handler` class but implements a commonly encountered flow from `put()` (for identification and authorisation), to `put()` (for operations that require comparison between the current state of the PV and its possible future state), and `open()` (for operations that only need consider the possible future state of the PV).

#### PVRecipe and SimpleServer
`PVRecipe` is a factory method used to simplify creation of `SharedNT` objects, i.e. PVs that implement Normative Type logic. It may be used in conjunction with the `SimpleServer` class to simplify management of event loops and PV lifecycle.

#### 
The `config_reader` parses a YAML file in order to construct `SharedNT` PVs which are managed by the `SimpleServer`. This is the simplest way to create and configure 

## Testing
Install the extra dependencies required for testing using `pip install .[test]` or similar.

To run tests invoke [pytest](https://docs.pytest.org/en/latest/):

```console
python -m pytest tests
```
or to run all tests and output a coverage report:
```
uv run --extra=test python -m coverage run --source=. -m pytest -x tests
uv run --extra=test python -m coverage report
```

### Linting and Formatting
This repository's CI/CD pipeling (using GitHub Actions) checks that source code meets PEP 8, and other more stringent, coding standards. This uses the [ruff](https://docs.astral.sh/ruff/) linter and code formatter. It is included in the `.[test] dependencies (see above) and may be manually invoked:

```console
ruff check --fix
ruff format
```

## Releases
The release process requires use of the `.[dist]` dependencies, which may be installed with `pip install .[dist]`. A build may then be triggered with `python -m build`. Alternatively, use:

```console
uv run --extra=dist python -m build
```

Publication to either PyPi or TestPyPI is performed automatically via CI/CD (i.e. GitHub Actions) and is driven by tags. Any commit intended for package publication must be tagged with a unique tag, and the semantic version must be greater than any existing tag. 