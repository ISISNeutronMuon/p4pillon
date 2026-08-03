"""Utility function for p4pillon"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from p4p import Value

if TYPE_CHECKING:
    from collections.abc import Callable


def time_in_seconds_and_nanoseconds(timestamp: float) -> tuple[int, int]:
    """Convert a timestamp into separate integer seconds and nanoseconds"""
    seconds = int(timestamp // 1)
    nanoseconds = int((timestamp % 1) * 1e9)
    return seconds, nanoseconds


def mark_all(value: Value) -> Value:
    """Mark every field of a Value as changed, in place, and return it.

    pvAccess only puts *marked* fields on the wire, and a SharedPV's stored
    change mask is the union of everything marked since open() -- so a field
    that is never marked is never sent to a client at all. Clients that
    zero-fill what they did not receive (pvxs, p4p) hide this; the Java
    ``org.epics.pva`` client leaves an untransmitted string as null, which is
    what makes the EPICS Archiver Appliance throw an NPE on ``alarm.message``.
    A real IOC sends the complete structure on a first get/monitor update.

    Use this on a value that is `open()`-ed once and not subsequently
    `post()`-ed, where nothing else will ever widen the mask -- the record
    field sub-PVs of `p4pillon.server.records` are the case this exists for.
    It is not for ordinary posts: narrowing an update to its genuinely
    changed fields (see `overwrite_unmarked`) is what keeps monitor deltas
    small.

    `~p4p.Value.mark` with no field name marks only the root, hence the loop;
    marking a top-level substructure marks its children too.
    """
    for fieldname in value:
        value.mark(fieldname)
    return value


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
