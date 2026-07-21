"""Utility function for p4pillon"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from p4p import Value


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


def overwrite_marked(current: Value, update: Value, fields: list[str] | None = None) -> None:
    """
    Overwrite the changed (marked) fields in one Value with fields from another Value.

    Every leaf field marked as changed in ``update`` is copied into ``current``. If
    ``fields`` is given, only leaves whose top-level field is in ``fields`` are copied.
    This makes the changes in place rather than returning a copy.
    """
    # ``changedSet(expand=True)`` walks the tree in C and returns only the changed
    # leaf paths, so we iterate over just the fields we copy rather than recursing
    # through every leaf in Python.
    changed = update.changedSet(expand=True)
    if fields:
        allowed = set(fields)
        changed = {name for name in changed if name.split(".", 1)[0] in allowed}

    for name in changed:
        current[name] = update[name]


def overwrite_unmarked(current: Value, update: Value, fields: list[str] | None = None) -> None:
    """
    Fill in the fields the caller did not change so ``update`` is a complete value.

    ``update`` is typically a partial post/put: only the changed fields are marked,
    and the rest are left at a default. This copies every unmarked (unchanged) field
    across from ``current`` -- the present PV state -- so downstream rules see a whole,
    consistent value. The copied-in fields stay marked unchanged, so they are not
    re-advertised; the changed fields keep their incoming values and marks. The update
    is modified in place.

    If ``fields`` is given, only those top-level fields are filled in.
    """
    # Rather than walk every unchanged leaf in Python, start from ``current`` (which
    # already holds every value) and overlay just the leaves ``update`` marked as
    # changed. The bulk copy of each top-level field happens in C, and the only
    # per-leaf Python work is over the (small) changed set.
    changed = update.changedSet(expand=True)
    saved = {name: update[name] for name in changed}

    keys = fields if fields else cast("list[str]", current.keys())
    for key in keys:
        update[key] = current[key]

    update.unmark()
    for name in changed:
        update[name] = saved[name]
