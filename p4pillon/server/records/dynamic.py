"""`DynamicRecordFields`/`IOCMimicProvider`: the lazy, registry-driven
path, building each "<name>.<FIELD>" sub-PV on demand as clients connect
rather than eagerly for every record up front. See `.static` for the eager
`StaticRecordProvider` alternative, and the `p4pillon.server.records` package
docstring for the overall rationale.
"""

import uuid
import weakref
from collections.abc import Collection, Mapping

from p4p.server import DynamicProvider as _DynamicProvider
from p4p.server import StaticProvider as _StaticProvider
from p4p.server.raw import SharedPV as _SharedPVBase

from ._util import _KeysContainerMixin
from .fields import (
    FIELD_NAMES,
    RecordFieldOverrides,
    RegistryEntry,
    _build_one_field,
    _field_applies,
    _field_shared_pv,
    _resolve_registry_description,
    _resolve_valtype_and_description,
    _should_serve_record_fields,
    _validate_fields,
)

__all__ = ("DynamicRecordFields", "IOCMimicProvider")


class DynamicRecordFields:
    """A `~p4p.server.DynamicProvider` handler serving "<name>.<FIELD>" for base PV
    names known to a `registry`, building each field PV lazily on demand rather than
    eagerly for every record up front (unlike `~p4pillon.server.records.StaticRecordProvider`).

    Most callers should use `IOCMimicProvider` instead, which manages this
    registry for you via `add()`/`remove()` -- see its docstring for an
    example. Construct `DynamicRecordFields` directly only when building the
    registry by hand: ::

        from p4p.server import DynamicProvider
        from p4pillon.server.records import DynamicRecordFields

        registry = {
            "EXAMPLE:PV": {"valtype": "d", "dtyp_choices": ["Soft Channel"], "fields": {}},
        }
        field_provider = DynamicProvider("recfields", DynamicRecordFields(registry))

    :param registry: A mapping of base PV name to a dict with keys 'valtype'
                     (required), 'dtyp_choices', 'fields', and 'description'
                     (all optional).  See `~p4pillon.server.records.build_record_fields`.
                     Each entry's 'fields' is validated against `FIELD_NAMES`
                     eagerly here, at construction time, rather than only
                     when/if a client connects to that record's fields.
                     See `RegistryEntry` for why 'description' is a snapshot only.
    :param pv_factory: Callable used to construct each "<name>.<FIELD>" sub-PV,
                       called as ``pv_factory(initial=value)``.  Defaults to
                       `~p4pillon.server.thread.SharedPV`.  A
                       `~p4pillon.server.asyncio.SharedPV` is rejected at
                       construction time -- see `_check_pv_factory_is_safe`.
    """

    def __init__(
        self,
        registry: Mapping[str, RegistryEntry],
        pv_factory: type[_SharedPVBase] | None = None,
    ) -> None:
        if pv_factory is not None:
            _check_pv_factory_is_safe(pv_factory)
        for name, entry in registry.items():
            _validate_fields(entry.get("fields") or {}, name, entry.get("dtyp_choices"))
        # Read-only here: only .get() is ever called (testChannel/makeChannel).
        # IOCMimicProvider passes its own dict and mutates that by reference.
        self._registry: Mapping[str, RegistryEntry] = registry
        self._pv_factory: type[_SharedPVBase] | None = pv_factory

    def _lookup(self, name: str) -> tuple[str, str, RegistryEntry] | None:
        # (basename, field, entry) when `name` is a "<basename>.<FIELD>" for
        # a basename known to the registry and a field that applies to its
        # valtype; None otherwise. Shared by testChannel()/makeChannel().
        basename, field = _split_field_name(name)
        if field is None:
            return None
        entry = self._registry.get(basename)
        if entry is None or not _field_applies(field, entry["valtype"]):
            return None
        return basename, field, entry

    def testChannel(self, name: str) -> bool:  # noqa: N802 - mandated by the p4p DynamicProvider protocol
        """Whether `name` is a "<basename>.<FIELD>" for a `basename` known to
        `registry` and a `field` that applies to its `valtype`. Part of the
        `~p4p.server.DynamicProvider` handler protocol.
        """
        return self._lookup(name) is not None

    def makeChannel(  # noqa: N802 - mandated by the p4p DynamicProvider protocol
        self,
        name: str,
        peer: str,  # noqa: ARG002 - peer unused, see docstring
    ) -> _SharedPVBase | None:
        """Build the "<basename>.<FIELD>" sub-PV for `name`, or `None` if
        `testChannel` would reject it. `peer` is unused -- every field's
        initial value is the same regardless of which client connects. Part
        of the `~p4p.server.DynamicProvider` handler protocol.
        """
        found = self._lookup(name)
        if found is None:
            return None
        basename, field, entry = found
        value = _build_one_field(
            field,
            basename,
            entry["valtype"],
            entry.get("dtyp_choices"),
            entry.get("fields") or {},
            _resolve_registry_description(entry),
        )
        return _field_shared_pv(value, self._pv_factory)


class IOCMimicProvider(_KeysContainerMixin):
    """An incrementally-mutable `add()`/`remove()` counterpart to
    `~p4pillon.server.records.StaticRecordProvider`, backed by
    `DynamicRecordFields` (the lazy, registry-driven path) instead of
    eagerly building every "<name>.<FIELD>" sub-PV up front. ::

        from p4p.nt import NTScalar
        from p4pillon.server.thread import SharedPV
        from p4pillon.server.records import IOCMimicProvider, IOCMimicServer

        provider = IOCMimicProvider("example")
        provider.add("EXAMPLE:PV", SharedPV(nt=NTScalar("d"), initial=1.234))

        with IOCMimicServer(providers=[provider]):
            ...

    Unlike `StaticRecordProvider`, this class is not itself a single
    `~p4p.server.StaticProvider`/`~p4p.server.DynamicProvider` -- it holds
    one of each internally (a `StaticProvider` for the base PVs added via
    `add()`, and a `DynamicProvider` wrapping the `DynamicRecordFields`
    registry `add()`/`remove()` maintain), exposed together as `providers`.
    `IOCMimicServer` unpacks that pair automatically, as above. Passing
    `provider` to plain `~p4p.server.Server` instead needs unpacking it
    yourself: ``Server(providers=[*provider.providers])``.

    `add`/`remove` mirror `StaticRecordProvider.add`/`.remove`'s signature and
    behaviour everywhere the lazy path can support it, but a few things
    `StaticRecordProvider` supports work differently or not at all here:

     - DESC tracks the base PV's ``display.description`` automatically for
       *new* connections (each `makeChannel()` re-reads it via a weak
       reference stored by `add()`); `set_desc_record` replaces that with an
       explicit value, again for new connections only -- there's no live
       channel here to `post()` an update to an already-open connection.
     - Every sub-PV is built lazily on first client connection, using
       whichever `pv_factory` this was constructed with -- never matched to
       the base PV's own flavor the way `StaticRecordProvider` does, and a
       `~p4pillon.server.asyncio.SharedPV` `pv_factory` is rejected outright
       (see `DynamicRecordFields`).
     - Sub-PVs don't appear in a plain channel-list query (e.g. the
       `pvlist` tool) -- `DynamicProvider` maintains no enumerable name list.

    `remove()` likewise can't retract a sub-PV channel a client has already
    connected to -- only a registry entry it can stop offering to *new* ones.
    """

    def __init__(
        self,
        name: str | None = None,
        pv_factory: type[_SharedPVBase] | None = None,
    ) -> None:
        self._static = _StaticProvider(name)
        self._registry: dict[str, RegistryEntry] = {}
        # DynamicRecordFields keeps this dict by reference, so add()/remove()
        # mutations are visible to testChannel()/makeChannel() immediately --
        # no separate sync step needed.
        self._dynamic = _anonymous_dynamic_provider(DynamicRecordFields(self._registry, pv_factory))

    @property
    def providers(self) -> tuple[_StaticProvider, _DynamicProvider]:
        """Both providers backing this instance -- spread into
        `~p4p.server.Server`'s `providers=` list, e.g.
        ``Server(providers=[*provider.providers])``.
        """
        return (self._static, self._dynamic)

    def add(
        self,
        name: str,
        pv: _SharedPVBase,
        valtype: str | None = None,
        dtyp_choices: list[str] | None = None,
        fields: RecordFieldOverrides | None = None,
        record_fields: bool = True,
    ) -> None:
        """Add a PV, and (unless `record_fields` is False) register its
        "<name>.<FIELD>" sub-PVs in the registry `DynamicRecordFields`
        builds them from lazily. See `StaticRecordProvider.add` for every
        parameter's meaning.
        """
        fields = fields or {}
        if record_fields and not _should_serve_record_fields(pv, fields):
            # Not record-like and no explicit override: serve the base PV alone,
            # as with record_fields=False (see StaticRecordProvider.add).
            record_fields = False

        if not record_fields:
            self._static.add(name, pv)
            return

        # Validate *before* the static add() -- a failure (e.g. a bad menu
        # choice) must not leave the base PV served with add() having raised.
        valtype, description = _resolve_valtype_and_description(pv, valtype)
        _validate_fields(fields, name, dtyp_choices)

        self._static.add(name, pv)
        self._registry[name] = {
            "valtype": valtype,
            "dtyp_choices": dtyp_choices,
            "fields": fields,
            # 'description' is only the add()-time fallback; 'pv_ref' lets
            # makeChannel() re-read display.description live per connection
            # (see _resolve_registry_description). Weak so the registry never
            # extends the base PV's lifetime beyond the StaticProvider's own
            # strong reference.
            "description": description,
            "pv_ref": weakref.ref(pv),
        }

    def set_desc_record(self, name: str, description: str) -> None:
        """Override DESC/DESC$ for `name` with an explicit value, picked up
        by any *new* connection from this point on (see the class docstring).
        This also stops DESC tracking the base PV's ``display.description``
        for `name` -- the explicit override wins from here onward.

        :raises KeyError: if `name` was never added, or was added with
                          `record_fields=False`.
        """
        entry = self._registry[name]
        entry["description"] = description
        entry.pop("pv_ref", None)

    def remove(self, name: str) -> None:
        """Remove a PV, and stop offering its "<name>.<FIELD>" sub-PVs to
        *new* connections (see the class docstring)."""
        self._registry.pop(name, None)
        self._static.remove(name)

    def _keys(self) -> Collection[str]:
        """Base PV names -- mirrors the internal `StaticProvider`, not the
        "<name>.<FIELD>" registry (see the class docstring: those sub-PVs
        aren't enumerable here, only servable)."""
        return self._static.keys()


def _anonymous_dynamic_provider(handler: DynamicRecordFields) -> _DynamicProvider:
    # DynamicProvider (unlike StaticProvider) requires an explicit name; a
    # random uuid stands in for callers with none (IOCMimicProvider and
    # IOCMimicServer's plain-dict shorthand both build one anonymously).
    return _DynamicProvider(str(uuid.uuid4()), handler)


def _split_field_name(name: str) -> tuple[str, str | None]:
    # (basename, field) for a known "<basename>.<FIELD>" name, else (name, None).
    basename, sep, field = name.rpartition(".")
    if not sep or field not in FIELD_NAMES:
        return name, None
    return basename, field


def _check_pv_factory_is_safe(pv_factory: type[_SharedPVBase]) -> None:
    # makeChannel() runs on the server's I/O thread, never an asyncio event
    # loop's thread, so a pv_factory needing a running loop there (e.g.
    # asyncio.SharedPV, or p4pillon.server.asyncio.SharedPV which subclasses
    # it) can never work here.
    if not isinstance(pv_factory, type):
        return
    from p4p.server.asyncio import SharedPV as _RawAsyncSharedPV

    if issubclass(pv_factory, _RawAsyncSharedPV):
        msg = (
            f"pv_factory={pv_factory.__name__} is not safe for DynamicRecordFields: makeChannel() is "
            "always called by the server's own internal thread, never the thread "
            "running an asyncio event loop, so it can never construct one. Use "
            "p4pillon.server.thread.SharedPV (the default) instead."
        )
        raise TypeError(msg)
