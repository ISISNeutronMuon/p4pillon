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


def _with_order(item: Any, order: int | None) -> Any:
    # p4p.server.Server's providers= entries are either a bare provider or a
    # (provider, order) tuple -- reattach whichever `order` this entry came
    # in with (or none) to each provider it expands to.
    return (item, order) if order is not None else item


def _dynamic_fields_provider(provider: Any) -> _DynamicProvider | None:
    # Builds the *additional* DynamicRecordFields-backed provider for a
    # plain-dict entry's "<name>.<FIELD>" sub-PVs (see the class docstring
    # below). Anything that isn't a plain dict needs no such extra provider.
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
    inferred from the base PV, DESC seeded as a one-time snapshot of
    `display.description` (with no way to reach the registry built here
    afterward to call `set_description`, unlike `IOCRecordProvider`), and no
    `dtyp_choices`/`fields` overrides. See `DynamicRecordFields` and
    `IOCRecordProvider`'s docstrings for the rest of the lazy path's
    limitations (sub-PV flavor, `pvlist` visibility, etc.), which apply here
    too.

    An `IOCRecordProvider` instance can also be passed directly, same as a
    plain dict or a `StaticRecordProvider`: `IOCRecordServer` unpacks it into
    its `.providers` pair automatically, so ``providers=[base, pvs]`` works
    the same as ``providers=[*base.providers, pvs]``.

    For DESC updates after add(), per-PV overrides, matching sub-PV flavor to
    an asyncio base PV, or `pvlist` visibility, build a `StaticRecordProvider`
    explicitly and pass that instead of a dict. Entries that aren't a plain
    dict or an `IOCRecordProvider` are passed through to `~p4p.server.Server`
    unchanged, with no extra "<name>.<FIELD>" handling added.
    """

    def __init__(self, providers: list[Any], isolate: bool = False, **kws: Any) -> None:
        # Referenced only to keep each DynamicProvider built here alive for
        # the Server's lifetime -- Server itself only does that for the
        # plain StaticProviders it builds from a bare dict, not for provider
        # instances we hand it ourselves.
        self._field_providers: list[_DynamicProvider] = []
        wrapped: list[Any] = []
        for entry in providers:
            provider, order = entry if isinstance(entry, tuple) else (entry, None)
            sub_providers = getattr(provider, "providers", None)
            if isinstance(sub_providers, tuple):
                # Already backed by its own provider pair (e.g.
                # IOCRecordProvider's static + DynamicRecordFields pair) --
                # unpack rather than treating it as a single provider (it
                # isn't one) or a dict (it has no .items()).
                wrapped.extend(_with_order(sub_provider, order) for sub_provider in sub_providers)
                continue
            wrapped.append(_with_order(provider, order))
            fields_provider = _dynamic_fields_provider(provider)
            if fields_provider is not None:
                self._field_providers.append(fields_provider)
                wrapped.append(_with_order(fields_provider, order))
        super().__init__(wrapped, isolate=isolate, **kws)
