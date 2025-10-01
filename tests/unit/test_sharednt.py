"""
Tests of SharedNT that don't need a concurrency model to be specified.
"""

from collections import OrderedDict

import pytest
from p4p import Type, Value

from p4pillon.nt import NTEnum, NTScalar
from p4pillon.server.raw import Handler
from p4pillon.server.thread import SharedPV
from p4pillon.sharednt import SharedNT


@pytest.mark.parametrize(
    "pvtype, expected_handlername",
    [
        ("d", ["control", "alarm", "alarm_limit", "timestamp"]),
        ("ad", ["control", "alarm", "alarm_limit", "timestamp"]),
        ("i", ["control", "alarm", "alarm_limit", "timestamp"]),
        ("ai", ["control", "alarm", "alarm_limit", "timestamp"]),
    ],
)
def testntscalar_create(pvtype, expected_handlername):
    testpv = SharedNT(
        nt=NTScalar(pvtype),
    )

    assert len(testpv.handler) == 4
    assert list(testpv.handler.keys()) == expected_handlername


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
        nt=NTScalar(pvtype),
        auth_handlers=OrderedDict({"pre1": Handler(), "pre2": Handler()}),
        user_handlers=OrderedDict({"post1": Handler(), "post2": Handler()}),
    )

    assert len(testpv.handler) == 8
    assert list(testpv.handler.keys()) == ["pre1", "pre2", *expected_handlername, "post1", "post2", "timestamp"]


def testntenum_create():
    testpv = SharedNT(nt=NTEnum(), initial={"index": 0, "choices": ["OFF", "ON"]})

    assert len(testpv.handler) == 3
    assert list(testpv.handler.keys()) == ["alarm", "alarmNTEnum", "timestamp"]


def testntenum_create_with_handlers():
    testpv = SharedNT(
        nt=NTEnum(),
        initial={"index": 0, "choices": ["OFF", "ON"]},
        auth_handlers=OrderedDict({"pre1": Handler(), "pre2": Handler()}),
        user_handlers=OrderedDict({"post1": Handler(), "post2": Handler()}),
    )

    assert len(testpv.handler) == 7
    assert list(testpv.handler.keys()) == ["pre1", "pre2", "alarm", "alarmNTEnum", "post1", "post2", "timestamp"]


@pytest.mark.filterwarnings("ignore")  # Ignore "RuntimeError: Empty SharedPV" warning
def testbadnt():
    with pytest.raises(NotImplementedError):
        SharedNT(nt=bool)


def test_init_with_ntscalar():
    testpv = SharedNT(initial=NTScalar("d").wrap(13.4))

    assert len(testpv.handler) == 4
    print(testpv.handler.keys())
    assert list(testpv.handler.keys()) == ["control", "alarm", "alarm_limit", "timestamp"]


@pytest.mark.xfail(reason="Still implementing handling for this case")
def test_init_with_value():
    type_for_test = Type(
        [
            ("value", "d"),
            ("alarm", ("S", "alarm_t", [("severity", "i"), ("status", "i"), ("message", "s")])),
            ("timeStamp", ("S", "time_t", [("secondsPastEpoch", "l"), ("nanoseconds", "i"), ("userTag", "i")])),
        ]
    )  # This is an NTScalar of type double with alarm and timeStamp but missing the expected id

    value_for_test = Value(type_for_test, {"value": 42})

    testpv = SharedPV(value_for_test)

    assert len(testpv.handler) == 4
    assert list(testpv.handler.keys()) == ["control", "alarm", "alarm_limit", "timestamp"]
