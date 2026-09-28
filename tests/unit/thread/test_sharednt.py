import pytest
from p4p.server.thread import SharedPV as ThreadSharedPV

from p4pillon.nt import NTEnum, NTScalar
from p4pillon.server.raw import (
    HandlerHooksMixin,  # carries the open()/post()/close() handler-hook support every SharedNT flavor needs
)
from p4pillon.thread.sharednt import SharedNT


@pytest.mark.parametrize(
    ("pvtype", "expected_handlername"),
    [
        ("d", ["control", "alarm", "alarm_limit", "timestamp"]),
        ("ad", ["control", "alarm", "alarm_limit", "timestamp"]),
        ("i", ["control", "alarm", "alarm_limit", "timestamp"]),
        ("ai", ["control", "alarm", "alarm_limit", "timestamp"]),
    ],
)
def testntscalar_thread_create(pvtype, expected_handlername):
    testpv = SharedNT(
        nt=NTScalar(pvtype, control=True, valueAlarm=True),
    )

    assert set(testpv.handler.keys()) == set(expected_handlername)
    assert len(testpv.handler) == len(expected_handlername)
    assert issubclass(SharedNT, HandlerHooksMixin)
    assert issubclass(SharedNT, ThreadSharedPV)


def testntenum_thread_create():
    testpv = SharedNT(nt=NTEnum(), initial={"index": 0, "choices": ["OFF", "ON"]}, alarmNTEnum={})

    assert len(testpv.handler) == 3
    assert list(testpv.handler.keys()) == ["alarm", "alarmNTEnum", "timestamp"]
    assert issubclass(SharedNT, HandlerHooksMixin)
    assert issubclass(SharedNT, ThreadSharedPV)
