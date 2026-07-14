"""Shared internal helpers for `.static`/`.dynamic`'s record providers."""

from collections.abc import Collection, Iterator

__all__ = ()


class _KeysContainerMixin:
    """Implements `__contains__`/`__iter__`/`__len__` against `_keys()`, for
    providers whose only enumeration primitive is a `.keys()`-like call --
    p4p's `StaticProvider` (which both `StaticRecordProvider` and
    `IOCRecordProvider` are backed by) exposes no dunders of its own.
    """

    def _keys(self) -> Collection[str]:
        raise NotImplementedError

    def __contains__(self, name: str) -> bool:
        return name in self._keys()

    def __iter__(self) -> Iterator[str]:
        return iter(self._keys())

    def __len__(self) -> int:
        return len(self._keys())
