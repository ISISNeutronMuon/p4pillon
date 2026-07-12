"""`DynamicRecordFields`/`IOCRecordProvider`: the lazy, registry-driven
path, building each "<name>.<FIELD>" sub-PV on demand as clients connect
rather than eagerly for every record up front. See `.static` for the eager
`StaticRecordProvider` alternative, and the `p4pillon.server.records` package
docstring for the overall rationale.
"""

import uuid

from p4p.server import DynamicProvider as _DynamicProvider
from p4p.server import StaticProvider as _StaticProvider
from p4p.server.raw import SharedPV as _SharedPVBase

from .fields import (
    FIELD_NAMES,
    RecordFieldOverrides,
    RegistryEntry,
    _build_one_field,
    _check_rtyp_inferrable,
    _field_applies,
    _field_shared_pv,
    _resolve_valtype_and_description,
    _validate_fields,
)

__all__ = ("DynamicRecordFields", "IOCRecordProvider")


class DynamicRecordFields:
    """A `~p4p.server.DynamicProvider` handler serving "<name>.<FIELD>" for base PV
    names known to a `registry`, building each field PV lazily on demand rather than
    eagerly for every record up front (unlike `~p4pillon.server.records.StaticRecordProvider`). ::

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
        registry: dict[str, RegistryEntry],
        pv_factory: type[_SharedPVBase] | None = None,
    ) -> None:
        if pv_factory is not None:
            _check_pv_factory_is_safe(pv_factory)
        for name, entry in registry.items():
            _validate_fields(entry.get("fields") or {}, name)
        self._registry: dict[str, RegistryEntry] = registry
        self._pv_factory: type[_SharedPVBase] | None = pv_factory

    def testChannel(self, name: str) -> bool:
        basename, field = _split_field_name(name)
        if field is None:
            return False
        entry = self._registry.get(basename)
        if entry is None:
            return False
        return _field_applies(field, entry["valtype"])

    def makeChannel(self, name: str, peer: str) -> _SharedPVBase | None:
        basename, field = _split_field_name(name)
        if field is None:
            return None
        entry = self._registry.get(basename)
        if entry is None or not _field_applies(field, entry["valtype"]):
            return None
        value = _build_one_field(
            field,
            basename,
            entry["valtype"],
            entry.get("dtyp_choices"),
            entry.get("fields") or {},
            entry.get("description") or "",
        )
        return _field_shared_pv(value, self._pv_factory)


class IOCRecordProvider:
    """An incrementally-mutable `add()`/`remove()` counterpart to
    `~p4pillon.server.records.StaticRecordProvider`, backed by
    `DynamicRecordFields` (the lazy, registry-driven path) instead of
    eagerly building every "<name>.<FIELD>" sub-PV up front. ::

        from p4p.nt import NTScalar
        from p4pillon.server.thread import SharedPV
        from p4pillon.server.records import IOCRecordProvider, IOCRecordServer

        provider = IOCRecordProvider("example")
        provider.add("EXAMPLE:PV", SharedPV(nt=NTScalar("d"), initial=1.234))

        with IOCRecordServer(providers=[provider]):
            ...

    Unlike `StaticRecordProvider`, this class is not itself a single
    `~p4p.server.StaticProvider`/`~p4p.server.DynamicProvider` -- it holds
    one of each internally (a `StaticProvider` for the base PVs added via
    `add()`, and a `DynamicProvider` wrapping the `DynamicRecordFields`
    registry `add()`/`remove()` maintain), exposed together as `providers`.
    `IOCRecordServer` unpacks that pair automatically, as above. Passing
    `provider` to plain `~p4p.server.Server` instead needs unpacking it
    yourself: ``Server(providers=[*provider.providers])``.

    `add`/`remove` mirror `StaticRecordProvider.add`/`.remove`'s signature and
    behaviour everywhere the lazy path can support it, but a few things
    `StaticRecordProvider` supports work differently or not at all here:

     - `set_description` only updates the snapshot new connections see --
       there's no live channel here to `post()` an update to an
       already-open connection.
     - Every sub-PV is built lazily on first client connection, using
       whichever `pv_factory` this was constructed with -- never matched to
       the base PV's own flavor the way `StaticRecordProvider` matches
       ``type(pv)``, and a `~p4pillon.server.asyncio.SharedPV` `pv_factory`
       is rejected outright (see `DynamicRecordFields`).
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
        # DynamicRecordFields stores this dict by reference, so add()/remove()
        # mutating self._registry is exactly what testChannel()/makeChannel()
        # see on the next client connection -- no separate sync step needed.
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
        self._static.add(name, pv)
        if not record_fields:
            return

        valtype, description = _resolve_valtype_and_description(pv, valtype)

        fields = fields or {}
        _validate_fields(fields, name)
        if fields.get("RTYP") is None:
            _check_rtyp_inferrable(pv)

        self._registry[name] = {
            "valtype": valtype,
            "dtyp_choices": dtyp_choices,
            "fields": fields,
            "description": description,
        }

    def set_description(self, name: str, description: str) -> None:
        """Update the DESC/DESC$ snapshot for `name`, picked up by any *new*
        connection from this point on (see the class docstring).

        :raises KeyError: if `name` was never added, or was added with
                          `record_fields=False`.
        """
        self._registry[name]["description"] = description

    def remove(self, name: str) -> None:
        """Remove a PV, and stop offering its "<name>.<FIELD>" sub-PVs to
        *new* connections (see the class docstring)."""
        self._registry.pop(name, None)
        self._static.remove(name)


def _anonymous_dynamic_provider(handler: DynamicRecordFields) -> _DynamicProvider:
    # Unlike StaticProvider, DynamicProvider requires an explicit name -- a
    # random uuid stands in wherever the caller has none of its own to give
    # it (both IOCRecordProvider and IOCRecordServer's plain-dict shorthand
    # build one of these anonymously).
    return _DynamicProvider(str(uuid.uuid4()), handler)


def _split_field_name(name: str) -> tuple[str, str | None]:
    # Returns (basename, field) if `name` is "<basename>.<FIELD>" for a
    # known field, else (name, None).
    basename, sep, field = name.rpartition(".")
    if not sep or field not in FIELD_NAMES:
        return name, None
    return basename, field


def _check_pv_factory_is_safe(pv_factory: type[_SharedPVBase]) -> None:
    # makeChannel() always runs on the server's own I/O thread, never the
    # thread running an asyncio event loop, so a pv_factory requiring a
    # running loop on the calling thread (e.g. asyncio.SharedPV) can never
    # work here. Detected via the `_requires_running_loop` trait rather than
    # naming asyncio.SharedPV directly, so any future loop-requiring flavor
    # is caught the same way.
    if isinstance(pv_factory, type) and getattr(pv_factory, "_requires_running_loop", False):
        raise ValueError(
            f"pv_factory={pv_factory.__name__} is not safe for DynamicRecordFields: makeChannel() is "
            "always called by the server's own internal thread, never the thread "
            "running an asyncio event loop, so it can never construct one. Use "
            "p4pillon.server.thread.SharedPV (the default) instead."
        )
