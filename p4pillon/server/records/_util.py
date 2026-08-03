"""Shared internal helpers for `.static`/`.dynamic`'s record providers."""

from collections.abc import Collection, Iterator
from typing import TYPE_CHECKING

__all__ = ()


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
