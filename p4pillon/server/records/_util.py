"""Shared internal helpers for `.static`/`.dynamic`/`.server`'s record providers."""

from collections.abc import Collection, Iterator
from typing import TYPE_CHECKING

from p4pillon.server.raw import InitialUpdate, apply_initial_update

if TYPE_CHECKING:
    from p4p.server.raw import SharedPV as _SharedPVBase

__all__ = ()


def _apply_ioc_initial_update(pv: "_SharedPVBase") -> None:
    """Give `pv` an IOC's first-update wire behaviour, unless its owner asked
    for something else.

    Everything in `p4pillon.server.records` exists to mimic an IOC, and a real
    IOC sends the complete structure on a first get/monitor update rather than
    only the fields that happen to have been marked -- so every entry point
    here resolves a PV left on `~p4pillon.server.raw.InitialUpdate.DEFAULT` to
    `~p4pillon.server.raw.InitialUpdate.COMPLETE`. A PV constructed with an
    explicit ``initial_update=`` keeps it.

    Applied to every base PV served, record-like or not: two record providers
    differing on the wire would be a bug report of its own, and the fix is
    about the wire format, not about record fields.
    """
    apply_initial_update(pv, InitialUpdate.COMPLETE)


class _KeysContainerMixin:
    """Implements `__contains__`/`__iter__`/`__len__` against `keys()`, for
    providers whose only enumeration primitive is a `.keys()`-like call --
    p4p's `StaticProvider` (which both `StaticRecordProvider` and
    `IOCMimicProvider` are backed by) exposes no dunders of its own.

    `keys()` is the mixin's requirement on the class it's mixed into, not
    something it provides: `StaticRecordProvider` inherits one from
    `~p4p.server.StaticProvider`, `IOCMimicProvider` defines its own. Hence
    the declaration below being `TYPE_CHECKING`-only -- a real method here
    would sit ahead of `StaticProvider` in the MRO and shadow the inherited
    one.
    """

    if TYPE_CHECKING:

        def keys(self) -> Collection[str]: ...

    def __contains__(self, name: str) -> bool:
        return name in self.keys()

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def __len__(self) -> int:
        return len(self.keys())
