"""Utility function for p4pillon"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from p4p import Value

if TYPE_CHECKING:
    from collections.abc import Callable


def as_raw(value: Any) -> Value:
    """Return the underlying raw `Value` of an NT-wrapped value, tolerating
    values that are not wrapped.

    An NT-typed value (e.g. the `ntwrappercommon` returned by
    `op.value()`/`pv.current()` for a normative type) carries its underlying
    `p4p.Value` on a `.raw` attribute; a hand-built (non-NT) Type is already a
    plain `Value` with no `.raw`, so it is returned unchanged. This never
    raises, unlike a bare `.raw` access.
    """
    return getattr(value, "raw", value)


def time_in_seconds_and_nanoseconds(timestamp: float) -> tuple[int, int]:
    """Convert a timestamp into separate integer seconds and nanoseconds"""
    seconds = int(timestamp // 1)
    nanoseconds = int((timestamp % 1) * 1e9)
    return seconds, nanoseconds


def recurse_values(value1: Value, value2: Value, func: Callable[[Value, Value, str], None], keys=None) -> bool:
    """Recurse through two Values with the same structure and apply a supplied to the leaf nodes"""
    if not keys:
        keys = cast("list[str]", value1.keys())

    for key in keys:
        if isinstance(value1[key], Value) and isinstance(value2[key], Value):
            if not recurse_values(value1[key], value2[key], func):
                return False
        else:
            func(value1, value2, key)

    return True


def overwrite_marked(current: Value, update: Value, fields: list[str] | None = None) -> None:
    """
    Overwrite all of the unmarked fields in one Value with fields from another Value.

    This makes the changes in place rather than returning a copy.
    """

    def overwrite_changed_key(update_leaf: Value, current_leaf: Value, key: str) -> None:
        """
        Given a leaf node in the update Value tree, check whether it is changed and, if so,
        change the matching current leaf to its value
        """
        if update_leaf.changed(key):
            current_leaf[key] = update_leaf[key]

    if not fields:
        fields = cast("list[str]", current.keys())

    recurse_values(update, current, overwrite_changed_key, fields)


def overwrite_unmarked(current: Value, update: Value, fields: list[str] | None = None) -> None:
    """
    Overwrite all of the unmarked fields in one Value with fields from another Value.

    This makes the changes in place rather than returning a copy.
    """

    def overwrite_unchanged_key(update_leaf: Value, current_leaf: Value, key: str) -> None:
        """
        Given a leaf node in the update Value tree, check whether it is unchanged and, if so,
        set it equal to the equivalent leaf node in the current Value tree. Then mark the new
        value for the leaf as unchanged.
        """
        if not update_leaf.changed(key):
            update_leaf[key] = current_leaf[key]
            update_leaf.mark(key, val=False)

    if not fields:
        fields = cast("list[str]", current.keys())

    recurse_values(update, current, overwrite_unchanged_key, fields)
