import pytest

from p4pillon.nt import NTEnum, NTScalar
from p4pillon.server.thread import SharedPV
from p4pillon.thread.sharednt import SharedNT


@pytest.mark.xfail(reason="Not sure? Maybe the monkey-patching?")
@pytest.mark.parametrize(
    "pvtype, expected_handlername",
    [
        ("d", ["control", "alarm", "alarm_limit", "timestamp"]),
        ("ad", ["control", "alarm", "alarm_limit", "timestamp"]),
        ("i", ["control", "alarm", "alarm_limit", "timestamp"]),
        ("ai", ["control", "alarm", "alarm_limit", "timestamp"]),
    ],
)
def testntscalar_thread_create(pvtype, expected_handlername):
    testpv = SharedNT(
        nt=NTScalar(pvtype),
    )

    assert len(testpv.handler) == 4
    assert list(testpv.handler.keys()) == expected_handlername
    assert issubclass(SharedNT, SharedPV)


@pytest.mark.xfail(reason="Not sure? Maybe the monkey-patching?")
def testntenum_thread_create():
    testpv = SharedNT(nt=NTEnum(), initial={"index": 0, "choices": ["OFF", "ON"]})

    assert len(testpv.handler) == 3
    assert list(testpv.handler.keys()) == ["alarm", "alarmNTEnum", "timestamp"]
    assert issubclass(SharedNT, SharedPV)
