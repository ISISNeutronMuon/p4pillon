"""
Tests of SharedNT that don't need a concurrency model to be specified.
"""

from collections import OrderedDict

import pytest
from p4p import Type, Value

from p4pillon.nt import NTEnum, NTScalar
from p4pillon.server.raw import Handler, SharedPV
from p4pillon.sharednt import SharedNT


@pytest.mark.parametrize(
    "pvtype, expected_handlername",
    [
        ("d", ["control", "alarm", "timestamp"]),
        ("ad", ["control", "alarm", "timestamp"]),
        ("i", ["control", "alarm", "timestamp"]),
        ("ai", ["control", "alarm", "timestamp"]),
    ],
)
def testntscalar_create1(pvtype, expected_handlername):
    testpv = SharedNT(
        nt=NTScalar(pvtype, control=True),
    )

    assert set(testpv.handler.keys()) == set(expected_handlername)
    assert len(testpv.handler) == len(expected_handlername)
    assert list(testpv.handler.keys())[-1] == "timestamp"


@pytest.mark.parametrize(
    "pvtype, expected_handlername",
    [
        ("d", ["alarm", "alarm_limit", "timestamp"]),
        ("ad", ["alarm", "alarm_limit", "timestamp"]),
        ("i", ["alarm", "alarm_limit", "timestamp"]),
        ("ai", ["alarm", "alarm_limit", "timestamp"]),
    ],
)
def testntscalar_create2(pvtype, expected_handlername):
    testpv = SharedNT(
        nt=NTScalar(pvtype, valueAlarm=True),
    )

    assert set(testpv.handler.keys()) == set(expected_handlername)
    assert len(testpv.handler) == len(expected_handlername)
    assert list(testpv.handler.keys())[-1] == "timestamp"


@pytest.mark.parametrize(
    "pvtype, expected_handlername",
    [
        ("d", ["control", "alarm", "alarm_limit", "timestamp"]),
        ("ad", ["control", "alarm", "alarm_limit", "timestamp"]),
        ("i", ["control", "alarm", "alarm_limit", "timestamp"]),
        ("ai", ["control", "alarm", "alarm_limit", "timestamp"]),
    ],
)
def testntscalar_create3(pvtype, expected_handlername):
    testpv = SharedNT(
        nt=NTScalar(pvtype, control=True, valueAlarm=True),
    )

    assert set(testpv.handler.keys()) == set(expected_handlername)
    assert len(testpv.handler) == len(expected_handlername)
    assert list(testpv.handler.keys())[-1] == "timestamp"


@pytest.mark.parametrize(
    "pvtype, expected_handlername",
    [
        (
            "d",
            [
                "control",
                "alarm",
                "alarm_limit",
            ],
        ),
        (
            "ad",
            [
                "control",
                "alarm",
                "alarm_limit",
            ],
        ),
        (
            "i",
            [
                "control",
                "alarm",
                "alarm_limit",
            ],
        ),
        (
            "ai",
            [
                "control",
                "alarm",
                "alarm_limit",
            ],
        ),
    ],
)
def testntscalar_create_with_handlers(pvtype, expected_handlername):
    testpv = SharedNT(
        nt=NTScalar(pvtype, control=True, valueAlarm=True),
        auth_handlers=OrderedDict({"pre1": Handler(), "pre2": Handler()}),
        user_handlers=OrderedDict({"post1": Handler(), "post2": Handler()}),
    )

    assert set(testpv.handler.keys()) == set(["pre1", "pre2", *expected_handlername, "post1", "post2", "timestamp"])
    assert list(testpv.handler.keys())[:2] == ["pre1", "pre2"]
    assert list(testpv.handler.keys())[-3:-1] == ["post1", "post2"]
    assert len(testpv.handler) == 2 + len(expected_handlername) + 2 + 1
    assert list(testpv.handler.keys())[-1] == "timestamp"


def testntenum_create():
    testpv = SharedNT(
        nt=NTEnum(), initial={"index": 0, "choices": ["OFF", "ON"]}, handler_constructors={"alarmNTEnum": {}}
    )

    assert set(testpv.handler.keys()) == set(["alarm", "alarmNTEnum", "timestamp"])
    assert list(testpv.handler.keys())[-1] == "timestamp"


def testntenum_create_with_handlers():
    testpv = SharedNT(
        nt=NTEnum(),
        initial={"index": 0, "choices": ["OFF", "ON"]},
        auth_handlers=OrderedDict({"pre1": Handler(), "pre2": Handler()}),
        user_handlers=OrderedDict({"post1": Handler(), "post2": Handler()}),
        handler_constructors={"alarmNTEnum": {}},
    )

    assert list(testpv.handler.keys()) == ["pre1", "pre2", "alarm", "alarmNTEnum", "post1", "post2", "timestamp"]


@pytest.mark.filterwarnings("ignore")  # Ignore "RuntimeError: Empty SharedPV" warning
def testbadnt():
    with pytest.raises(NotImplementedError):
        SharedNT(nt=bool)


def test_init_with_ntscalar():
    testpv = SharedNT(initial=NTScalar("d").wrap(13.4))

    assert list(testpv.handler.keys()) == ["alarm", "timestamp"]


def test_init_with_value():
    type_for_test = Type(
        [
            ("value", "d"),
            ("alarm", ("S", "alarm_t", [("severity", "i"), ("status", "i"), ("message", "s")])),
            ("timeStamp", ("S", "time_t", [("secondsPastEpoch", "l"), ("nanoseconds", "i"), ("userTag", "i")])),
        ],
        id="epics:nt/NTScalar",
    )  # This is an NTScalar of type double with alarm and timeStamp

    value_for_test = Value(type_for_test, {"value": 42})

    testpv = SharedNT(initial=value_for_test)

    assert set(testpv.handler.keys()) == set(["alarm", "timestamp"])
    assert len(testpv.handler) == 2
    assert list(testpv.handler.keys())[-1] == "timestamp"


def test_init_with_value_noid():
    type_for_test = Type(
        [
            ("value", "d"),
            ("alarm", ("S", "alarm_t", [("severity", "i"), ("status", "i"), ("message", "s")])),
            ("timeStamp", ("S", "time_t", [("secondsPastEpoch", "l"), ("nanoseconds", "i"), ("userTag", "i")])),
        ],
    )  # This is an NTScalar of type double with alarm and timeStamp

    value_for_test = Value(type_for_test, {"value": 42})

    testpv = SharedNT(initial=value_for_test)

    assert set(testpv.handler.keys()) == set(["alarm", "timestamp"])
    assert len(testpv.handler) == 2
    assert list(testpv.handler.keys())[-1] == "timestamp"


def test_value_only():
    """Test what happens when we have a bare value NTScalar"""

    type_for_test = Type([("value", "d")], id="epics:nt/NTScalar")  # This is a bare NTScalar of type double
    value_for_test = Value(type_for_test, {"value": 42})

    testpv = SharedNT(initial=value_for_test)

    assert isinstance(testpv.handler, SharedPV._DummyHandler)  # pylint: disable=W0212


class TestControl:
    """Integration test case for validating control limit behaviour on a variety
    of PV types"""

    @pytest.mark.parametrize(
        "pvtype, init_val, expected_val",
        [
            ("d", -10, -9.0),
            ("d", 0, 0.0),
            ("d", 10, 9.0),
            ("i", -10, -9),
            ("i", 0, 0),
            ("i", 10, 9),
            ("ad", [-10, 10, 0], [-9, 9, 0]),
            ("ai", [-10, 10, 0], [-9, 9, 0]),
        ],
    )
    def test_basic_control_logic(self, pvtype, init_val, expected_val):
        sharednt = SharedNT(
            nt=NTScalar(pvtype, control=True),
            initial={"value": init_val, "control.limitHigh": 9, "control.limitLow": -9, "control.minStep": 1},
        )

        if not isinstance(init_val, list):
            assert sharednt.current() == expected_val
        else:
            assert (sharednt.current() == expected_val).all()
