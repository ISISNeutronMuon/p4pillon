from concurrent.futures import Future

import numpy
import pytest
from p4p.nt import NTNDArray, NTScalar

from p4pillon.server.thread import Handler, SharedPV


class TestThreadHandler:
    """
    Test Handler open(), post() and close() functions called correctly by SharedPV. Note that:
    - TestRPC, TestFirstLast already test onFirstConnect() and onLastDisconnect().
    - TestGPM, TestPVRequestMask already test put().
    - TestRPC, TestRPC2 already test rpc().
    """

    class HandlerTest(Handler):
        def __init__(self):
            self.last_op = "init"

        def open(self, value):
            self.last_op = "open"
            value["value"] = 17

        def post(self, _pv, value):
            self.last_op = "post"
            value["value"] = value["value"] * 2

        def close(self, _pv):
            self.last_op = "close"

    def setup_method(self, _method):
        self.handler = self.HandlerTest()
        self.pv = SharedPV(handler=self.handler, nt=NTScalar("d"))

    def test_open(self):
        # Setup sets the initial value to 5, but the Handler open() overrides
        self.pv.open(5)
        assert self.handler.last_op == "open"
        assert self.pv.current() == 17.0

    def test_post(self):
        self.pv.open(5)
        self.pv.post(13.0)
        assert self.handler.last_op == "post"
        assert self.pv.current() == 26.0

    def test_close(self):
        self.pv.open(5)
        self.pv.close(sync=True)
        assert self.handler.last_op == "close"

    def teardown_method(self, _method):
        self.pv.close()
        del self.handler
        del self.pv


class TestNoDoubleWrapOfInitialValue:
    """Regression tests for `SharedPV.open()`/`.post()` each wrapping `value`
    via `nt.wrap()` themselves before delegating to p4p's own (already
    wrapping) `SharedPV.open()`/`.post()`, which wraps a second time. Harmless
    for `NTScalar`, whose `wrap()` tolerates being fed an already-wrapped
    `Value` -- but `NTNDArray.wrap()` assumes a raw `numpy.ndarray` and raises
    when handed a `Value` on the second pass.
    """

    def test_open_with_ntndarray_does_not_double_wrap(self):
        pv = SharedPV(nt=NTNDArray(), initial=numpy.zeros((4, 4)))
        assert numpy.array_equal(numpy.asarray(pv.current()).flatten(), numpy.zeros(16))

    def test_post_with_ntndarray_does_not_double_wrap(self):
        pv = SharedPV(nt=NTNDArray(), initial=numpy.zeros((4, 4)))
        pv.post(numpy.ones((4, 4)))
        assert numpy.array_equal(numpy.asarray(pv.current()).flatten(), numpy.ones(16))


class TestThreadPostDeferred:
    """``post_deferred`` enqueues a post onto the PV's own work queue and
    returns a `concurrent.futures.Future` carrying its outcome -- the
    thread-flavor counterpart of the asyncio flavor's ``post_deferred``."""

    @staticmethod
    def _open_pv(handler: Handler | None = None) -> SharedPV:
        pv = SharedPV(handler=handler, nt=NTScalar("d"))
        pv.open(0.0)
        return pv

    def test_applies_value(self):
        pv = self._open_pv()
        fut = pv.post_deferred(3.0)
        assert isinstance(fut, Future)
        assert fut.result(timeout=2) is None
        assert pv.current() == 3.0
        pv.close()

    def test_runs_handler(self):
        # TestThreadHandler.HandlerTest.post() doubles the value.
        pv = self._open_pv(handler=TestThreadHandler.HandlerTest())
        pv.post_deferred(21.0).result(timeout=2)
        assert pv.current() == 42.0
        pv.close()

    def test_propagates_exception(self):
        class Boom(Handler):
            def post(self, _pv, _value):
                msg = "boom"
                raise RuntimeError(msg)

        pv = self._open_pv(handler=Boom())
        fut = pv.post_deferred(1.0)
        with pytest.raises(RuntimeError, match="boom"):
            fut.result(timeout=2)
        pv.close()

    def test_fanout_from_handler_no_deadlock(self):
        # The motivating case: a handler on one PV defers a post to *another*
        # PV, without ever nesting the target's lock inside its own.
        target = self._open_pv()
        deferred: list[Future[None]] = []

        class Fanout(Handler):
            def post(self, _pv, value):
                deferred.append(target.post_deferred(value["value"]))

        source = self._open_pv(handler=Fanout())
        source.post(7.0)
        assert deferred, "handler should have deferred a post to the target PV"
        deferred[0].result(timeout=2)
        assert target.current() == 7.0
        source.close()
        target.close()
