"""`IOCMimicServer`: a `~p4p.server.Server` whose plain ``{name: pv}`` dict
shorthand also serves "<name>.<FIELD>" sub-PVs, via `.dynamic`'s lazy,
registry-driven `DynamicRecordFields` -- not `.static`'s eager
`StaticRecordProvider`, which this module has no dependency on at all (a plain
dict's base PVs are served by whatever `~p4p.server.StaticProvider`
`~p4p.server.Server` itself builds for it). See the
`p4pillon.server.records` package docstring for the overall rationale.
"""

import weakref
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from p4p.server import DynamicProvider as _DynamicProvider
from p4p.server import Server as _Server

from .dynamic import DynamicRecordFields, IOCMimicProvider, _make_field_provider
from .fields import RegistryEntry, _resolve_valtype_and_description, _should_serve_record_fields

if TYPE_CHECKING:
    from p4p.server.raw import SharedPV as _SharedPVBase

__all__ = ("IOCMimicServer",)

_T = TypeVar("_T")


def _with_order(item: _T, order: int | None) -> tuple[_T, int] | _T:
    # p4p.server.Server's providers= entries are a bare provider or a
    # (provider, order) tuple -- reattach `order` (if any) to each provider
    # this entry expands to.
    return (item, order) if order is not None else item


def _dynamic_fields_provider(provider: object) -> _DynamicProvider | None:
    # Builds the extra DynamicRecordFields provider for a plain-dict entry's
    # "<name>.<FIELD>" sub-PVs (see the class docstring); non-dict entries
    # need none.
    if not isinstance(provider, Mapping):
        return None
    # isinstance only narrows to a bare Mapping; the key/value types are our
    # documented contract (class docstring), not runtime-checkable.
    mapping = cast("Mapping[str, _SharedPVBase]", provider)
    registry: dict[str, RegistryEntry] = {}
    for name, pv in mapping.items():
        if not _should_serve_record_fields(pv, None):
            # Not record-like: the base PV is still served (by Server's own
            # StaticProvider for the dict), just with no sub-PVs, as an IOC
            # serves a Q:group. This path has no fields= override, so unlike
            # the two add() methods it can only skip, never opt one in.
            continue
        valtype, description = _resolve_valtype_and_description(pv, None)
        # 'pv_ref' lets DESC track the base PV's display.description live for
        # new connections; 'description' remains as the fallback snapshot.
        # See RegistryEntry's docstring.
        registry[name] = {"valtype": valtype, "description": description, "pv_ref": weakref.ref(pv)}
    # No record-like entries -> no field provider to add at all.
    return _make_field_provider(DynamicRecordFields(registry)) if registry else None


def _expand_providers(providers: list[Any]) -> tuple[list[Any], list[Any]]:
    # Expand an IOCMimicServer providers= list into the flat list
    # p4p.server.Server takes, plus the objects the caller must keep alive for
    # the Server's lifetime -- Server does that itself only for the
    # StaticProvider it builds from a bare dict, not for the field providers we
    # build nor for an IOCMimicProvider we take apart. Without it, a caller
    # dropping their provider leaves the base PVs working (the C++ Server holds
    # the StaticProvider) while every sub-PV silently stops resolving.
    # Split out of __init__ so the expansion -- especially each entry's
    # resulting provider *order* -- is testable without starting a server.
    # A field provider is always appended bare, never as a (provider, order)
    # tuple: it carries _FIELD_PROVIDER_ORDER as its own `order` attribute,
    # and p4p.server.Server prefers a tuple's order to that attribute -- so
    # reattaching the entry's order to the field half would undo it.
    wrapped: list[Any] = []
    keep_alive: list[Any] = []
    for entry in providers:
        provider, order = entry if isinstance(entry, tuple) else (entry, None)
        if isinstance(provider, IOCMimicProvider):
            # Backed by its own static + DynamicRecordFields provider pair
            # -- unpack it rather than treat it as one provider or a dict.
            # An isinstance check, not duck typing on a `.providers`
            # attribute: any other provider that happens to carry one must
            # be passed through to p4p.server.Server untouched.
            static_provider, fields_provider = provider.providers
            wrapped.append(_with_order(static_provider, order))
            wrapped.append(fields_provider)
            # The whole IOCMimicProvider, not just the half p4p would
            # otherwise drop: that also pins its StaticProvider, its registry,
            # and the base PVs the registry's weak 'pv_ref's point at.
            keep_alive.append(provider)
            continue
        wrapped.append(_with_order(provider, order))
        fields_provider = _dynamic_fields_provider(provider)
        if fields_provider is not None:
            keep_alive.append(fields_provider)
            wrapped.append(fields_provider)
    return wrapped, keep_alive


class IOCMimicServer(_Server):
    """A `~p4p.server.Server` for which a plain ``{name: pv}`` dict in
    `providers=` also gets its "<name>.<FIELD>" sub-PVs served -- via
    `DynamicRecordFields` (the lazy, registry-driven path), rather than plain
    p4p's `~p4p.server.StaticProvider` (base PVs only, no sub-PVs). ::

        from p4p.nt import NTScalar
        from p4pillon.server.thread import SharedPV
        from p4pillon.server.records import IOCMimicServer

        names = [f"DEV:PV{i:02d}" for i in range(12)]
        pvs = {name: SharedPV(nt=NTScalar('d'), initial=0.0) for name in names}

        with IOCMimicServer(providers=[pvs]):
            ...  # "DEV:PV00.RTYP", "DEV:PV00.SCAN", etc. are now servable too

    Each dict entry's sub-PVs get `DynamicRecordFields`'s defaults: `valtype`
    inferred from the base PV, DESC tracking the base PV's
    `display.description` automatically for new connections (re-read per
    connection via a weak reference, so a later ``pv.post()`` changing it is
    reflected -- there is no `set_desc_record` here, unlike
    `IOCMimicProvider`), and no `dtyp_choices`/`fields` overrides. See
    `DynamicRecordFields` and `IOCMimicProvider`'s docstrings for the rest of
    the lazy path's limitations (sub-PV flavor, `pvlist` visibility, etc.),
    which apply here too.

    An `IOCMimicProvider` instance can also be passed directly, same as a
    plain dict or a `StaticRecordProvider`: `IOCMimicServer` unpacks it into
    its `.providers` pair automatically, so ``providers=[base, pvs]`` works
    the same as ``providers=[*base.providers, pvs]``.

    For explicit DESC overrides, per-PV `fields` overrides, matching sub-PV
    flavor to an asyncio base PV, or `pvlist` visibility, build a
    `StaticRecordProvider` explicitly and pass that instead of a dict. Entries that aren't a plain
    dict or an `IOCMimicProvider` are passed through to `~p4p.server.Server`
    unchanged, with no extra "<name>.<FIELD>" handling added.
    """

    def __init__(self, providers: list[Any], isolate: bool = False, **kws: Any) -> None:
        # **kws is forwarded verbatim to Server.__init__; its signature isn't ours to narrow.
        # self._keep_alive is where _expand_providers' second return value has to live:
        # for the Server's lifetime, since nothing else references those objects then.
        wrapped, self._keep_alive = _expand_providers(providers)
        super().__init__(wrapped, isolate=isolate, **kws)
