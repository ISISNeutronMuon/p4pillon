from p4p.nt import NTEnum, NTScalar

from p4pillon.utils import mark_all, time_in_seconds_and_nanoseconds


def test_time_in_seconds_and_nanoseconds():
    seconds, nanoseconds = time_in_seconds_and_nanoseconds(123.456)
    assert seconds == 123
    assert nanoseconds == 456000000


def test_mark_all_reaches_into_substructures():
    # wrap() marks 'value' alone, so alarm/timeStamp would never go on the
    # wire. Value.mark() with no argument marks only the root -- mark_all has
    # to walk the top-level fields for the children to come with them.
    value = NTScalar("s").wrap("ai")
    assert value.changedSet() == {"value"}

    assert mark_all(value) is value  # marks in place, returns the same Value
    assert value.changedSet(expand=True) >= {
        "value",
        "alarm.severity",
        "alarm.status",
        "alarm.message",
        "timeStamp.secondsPastEpoch",
        "timeStamp.nanoseconds",
        "timeStamp.userTag",
    }


def test_mark_all_marks_a_structured_value_field():
    # An NTEnum's "value" is itself a substructure, not a leaf.
    marked = mark_all(NTEnum().wrap("OFF", choices=["OFF", "ON"])).changedSet(expand=True)
    assert marked >= {"value.index", "value.choices", "alarm.message"}
