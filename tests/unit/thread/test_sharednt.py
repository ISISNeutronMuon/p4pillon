from collections import OrderedDict

import pytest

from p4pillon.nt import NTEnum, NTScalar
from p4pillon.server.raw import Handler
from p4pillon.thread.sharednt import SharedNT


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
