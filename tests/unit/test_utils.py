from p4p import Type, Value

from p4pillon.utils import overwrite_unmarked, time_in_seconds_and_nanoseconds


def test_time_in_seconds_and_nanoseconds():
    seconds, nanoseconds = time_in_seconds_and_nanoseconds(123.456)
    assert seconds == 123
    assert nanoseconds == 456000000


# A small structure with two scalar leaves and a nested sub-structure, enough to
# exercise backfilling, mark preservation, partial sub-structure marking, and the
# ``fields`` restriction of overwrite_unmarked.
_TEST_TYPE = Type(
    [
        ("a", "i"),
        ("b", "i"),
        ("nested", ("S", None, [("x", "i"), ("y", "i")])),
    ]
)


def _current() -> Value:
    return Value(_TEST_TYPE, {"a": 100, "b": 200, "nested": {"x": 300, "y": 400}})


def _update() -> Value:
    update = Value(_TEST_TYPE, {"a": 1, "b": 2, "nested": {"x": 3, "y": 4}})
    update.unmark()
    return update


def test_overwrite_unmarked_backfills_unchanged_and_keeps_changed():
    """An unchanged leaf takes ``current``'s (differing) value and stays unmarked;
    a changed leaf keeps ``update``'s value and its mark."""
    current = _current()
    update = _update()
    update.mark("a")  # 'a' changed, 'b' left unchanged

    overwrite_unmarked(current, update)

    # Changed leaf: keeps update's value and its mark.
    assert update["a"] == 1
    assert update.changed("a") is True

    # Unchanged leaf: backfilled from current (a genuinely different value) and
    # left marked unchanged so it is not re-transmitted.
    assert update["b"] == 200
    assert update.changed("b") is False

    assert update.changedSet(expand=True) == {"a"}


def test_overwrite_unmarked_partial_substructure():
    """Within a sub-structure only the marked leaf is preserved; the unmarked
    sibling is backfilled from current."""
    current = _current()
    update = _update()
    update.mark("nested.x")

    overwrite_unmarked(current, update)

    assert update["nested.x"] == 3
    assert update["nested.y"] == 400
    assert update.changedSet(expand=True) == {"nested.x"}


def test_overwrite_unmarked_fields_restriction():
    """With ``fields`` given, only listed top-level fields are backfilled; an
    excluded field keeps update's own value and is never touched."""
    current = _current()
    update = _update()  # nothing marked changed

    overwrite_unmarked(current, update, fields=["a", "nested"])

    # Listed fields backfilled from current.
    assert update["a"] == 100
    assert update["nested.x"] == 300
    assert update["nested.y"] == 400

    # Excluded field keeps update's original value, untouched.
    assert update["b"] == 2

    # Nothing was marked changed and nothing should have become changed.
    assert update.changedSet(expand=True) == set()
