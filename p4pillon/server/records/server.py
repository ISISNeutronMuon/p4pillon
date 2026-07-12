"""`IOCRecordServer`: a `~p4p.server.Server` whose plain ``{name: pv}`` dict
shorthand also serves "<name>.<FIELD>" sub-PVs, via `.dynamic`'s lazy,
registry-driven `DynamicRecordFields` -- not `.static`'s eager
`StaticRecordProvider`, which this module has no dependency on at all (a plain
dict's base PVs are served by whatever `~p4p.server.StaticProvider`
`~p4p.server.Server` itself builds for it). See the
`p4pillon.server.records` package docstring for the overall rationale.
"""

from typing import Any

from p4p.server import DynamicProvider as _DynamicProvider
from p4p.server import Server as _Server

from .dynamic import DynamicRecordFields, _anonymous_dynamic_provider
from .fields import RegistryEntry, _resolve_valtype_and_description

__all__ = ("IOCRecordServer",)


def _dynamic_fields_provider(provider: Any) -> _DynamicProvider | None:
    # Builds the *additional* DynamicRecordFields-backed provider for a
    # plain-dict entry's "<name>.<FIELD>" sub-PVs (see the class docstring
    # below for the rationale and what's inferred). Anything that isn't a
    # plain dict needs no such extra provider -- returns `None`.
    if not hasattr(provider, "items"):
        return None
    registry: dict[str, RegistryEntry] = {}
    for name, pv in provider.items():
        valtype, description = _resolve_valtype_and_description(pv, None)
        registry[name] = {"valtype": valtype, "description": description}
    return _anonymous_dynamic_provider(DynamicRecordFields(registry))


class IOCRecordServer(_Server):
    """A `~p4p.server.Server` for which a plain ``{name: pv}`` dict in
    `providers=` also gets its "<name>.<FIELD>" sub-PVs served -- via
    `DynamicRecordFields` (the lazy, registry-driven path), rather than plain
    p4p's `~p4p.server.StaticProvider` (base PVs only, no sub-PVs). ::

        from p4p.nt import NTScalar
        from p4pillon.server.thread import SharedPV
        from p4pillon.server.records import IOCRecordServer

        names = [f"DEV:PV{i:02d}" for i in range(12)]
        pvs = {name: SharedPV(nt=NTScalar('d'), initial=0.0) for name in names}

        with IOCRecordServer(providers=[pvs]):
            ...  # "DEV:PV00.RTYP", "DEV:PV00.SCAN", etc. are now servable too

    Each dict entry's sub-PVs get `DynamicRecordFields`'s defaults: `valtype`
    inferred from the base PV the same way `StaticRecordProvider.add()` would
    (see `~p4pillon.server.records.fields._infer_valtype_of_pv`), DESC seeded
    as a one-time snapshot of the base PV's `display.description` (there's no
    way to reach the `DynamicRecordFields` registry built here afterward to
    call `set_description` on it, unlike `IOCRecordProvider`), and no
    `dtyp_choices`/`fields` overrides. Every sub-PV is also built lazily,
    on first client connection, as a plain `~p4pillon.server.thread.SharedPV`
    regardless of the dict's own PV flavor -- unlike `StaticRecordProvider`,
    whose eagerly-built sub-PVs match the base PV's own flavor exactly,
    `DynamicRecordFields` cannot build `~p4pillon.server.asyncio.SharedPV`
    sub-PVs at all (`makeChannel()` always runs on the server's own I/O
    thread, never the thread running an asyncio event loop). Each dict's
    sub-PVs also don't appear in a plain channel-list query (e.g. the
    `pvlist` tool), since a `~p4p.server.DynamicProvider` -- unlike
    `StaticRecordProvider`'s `~p4p.server.StaticProvider` -- maintains no
    enumerable list of the names it can serve.

    For DESC updates after add(), per-PV overrides, matching sub-PV flavor to
    an asyncio base PV, or `pvlist` visibility, build a `StaticRecordProvider`
    explicitly (see its own docstring) and pass that instead of a dict;
    entries that aren't a plain dict (a provider name string, or an
    already-constructed provider instance, including a `StaticRecordProvider`)
    are passed through to `~p4p.server.Server` unchanged, with no extra
    "<name>.<FIELD>" handling added.
    """

    def __init__(self, providers: list[Any], isolate: bool = False, **kws: Any) -> None:
        # Referenced only to keep each DynamicProvider built here alive for
        # the Server's lifetime -- p4p.server.Server itself only does this
        # for the plain StaticProviders *it* builds from a bare dict (the
        # base PVs), not for provider instances we hand it ourselves (which
        # is what _dynamic_fields_provider's output is, from
        # p4p.server.Server's point of view).
        self._field_providers: list[_DynamicProvider] = []
        wrapped: list[Any] = []
        for entry in providers:
            provider, order = entry if isinstance(entry, tuple) else (entry, None)
            wrapped.append((provider, order) if order is not None else provider)
            fields_provider = _dynamic_fields_provider(provider)
            if fields_provider is not None:
                self._field_providers.append(fields_provider)
                wrapped.append((fields_provider, order) if order is not None else fields_provider)
        super().__init__(wrapped, isolate=isolate, **kws)
