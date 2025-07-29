from collections import OrderedDict

import pytest
from p4p.nt import NTEnum, NTScalar
from p4p.server.raw import Handler

from p4p_ext.thread.sharednt import SharedNT


@pytest.mark.parametrize(
    "pvtype, expected_handlername",
    [("d", "NTScalar"), ("ad", "NTScalarArray"), ("i", "NTScalar"), ("ai", "NTScalarArray")],
)
def testntscalar_create(pvtype, expected_handlername):
    testpv = SharedNT(
        nt=NTScalar(pvtype),
    )

    assert len(testpv.handlers) == 1
    assert list(testpv.handlers.keys()) == [expected_handlername]


@pytest.mark.parametrize(
    "pvtype, expected_handlername",
    [("d", "NTScalar"), ("ad", "NTScalarArray"), ("i", "NTScalar"), ("ai", "NTScalarArray")],
)
def testntscalar_create_with_handlers(pvtype, expected_handlername):
    testpv = SharedNT(
        nt=NTScalar(pvtype),
        pre_nthandlers=OrderedDict({"pre1": Handler(), "pre2": Handler()}),
        post_nthandlers=OrderedDict({"post1": Handler(), "post2": Handler()}),
    )

    assert len(testpv.handlers) == 5
    assert list(testpv.handlers.keys()) == ["pre1", "pre2", expected_handlername, "post1", "post2"]


def testntenum_create():
    testpv = SharedNT(nt=NTEnum(), initial={"index": 0, "choices": ["OFF", "ON"]})

    assert len(testpv.handlers) == 1
    assert list(testpv.handlers.keys()) == ["NTEnum"]


def testntenum_create_with_handlers():
    testpv = SharedNT(
        nt=NTEnum(),
        initial={"index": 0, "choices": ["OFF", "ON"]},
        pre_nthandlers=OrderedDict({"pre1": Handler(), "pre2": Handler()}),
        post_nthandlers=OrderedDict({"post1": Handler(), "post2": Handler()}),
    )

    assert len(testpv.handlers) == 5
    assert list(testpv.handlers.keys()) == ["pre1", "pre2", "NTEnum", "post1", "post2"]


@pytest.mark.filterwarnings("ignore")  # Ignore "RuntimeError: Empty SharedPV" warning
def testbadnt():
    with pytest.raises(NotImplementedError):
        SharedNT(nt=bool)
