import asyncio

import numpy
import pytest
import pytest_asyncio
from p4p._p4p import SharedPV as _RawSharedPV
from p4p.nt import NTNDArray, NTScalar

from p4pillon.server.asyncio import Handler, SharedPV
from p4pillon.server.raw import InitialUpdate, apply_initial_update

_NULLABLE_LEAVES = frozenset({"alarm.message", "display.description", "display.units"})


class TestAsyncioHandler:
    """
    Test Handler open(), post() and close() functions called correctly by SharedPV. Note that:
    - TestRPC, TestFirstLast already test onFirstConnect() and onLastDisconnect().
    - TestGPM, TestPVRequestMask already test put().
    - TestRPC, TestRPC2 already test rpc().

    SharedPV construction requires a running event loop, so setup/teardown is an
    async fixture rather than setup_method/teardown_method.
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

    @pytest_asyncio.fixture(autouse=True)
    async def setup(self):
        self.handler = self.HandlerTest()
        self.pv = SharedPV(handler=self.handler, nt=NTScalar("d"))
        yield
        self.pv.close()
        del self.handler
        del self.pv

    async def test_open(self):
        # Setup sets the initial value to 5, but the Handler open() overrides
        self.pv.open(5)
        assert self.handler.last_op == "open"
        assert self.pv.current() == 17.0

    async def test_post(self):
        self.pv.open(5)
        self.pv.post(13.0)
        assert self.handler.last_op == "post"
        assert self.pv.current() == 26.0

    async def test_close(self):
        self.pv.open(5)
        await self.pv.close(sync=True)
        assert self.handler.last_op == "close"


class TestNoDoubleWrapOfInitialValue:
    """Regression tests for `SharedPV.open()`/`.post()` each wrapping `value`
    via `nt.wrap()` themselves before delegating to p4p's own (already
    wrapping) `SharedPV.open()`/`.post()`, which wraps a second time. Harmless
    for `NTScalar`, whose `wrap()` tolerates being fed an already-wrapped
    `Value` -- but `NTNDArray.wrap()` assumes a raw `numpy.ndarray` and raises
    when handed a `Value` on the second pass.

    SharedPV construction requires a running event loop, so these are async tests.
    """

    async def test_open_with_ntndarray_does_not_double_wrap(self):
        pv = SharedPV(nt=NTNDArray(), initial=numpy.zeros((4, 4)))
        assert numpy.array_equal(numpy.asarray(pv.current()).flatten(), numpy.zeros(16))
        pv.close()

    async def test_post_with_ntndarray_does_not_double_wrap(self):
        pv = SharedPV(nt=NTNDArray(), initial=numpy.zeros((4, 4)))
        pv.post(numpy.ones((4, 4)))
        assert numpy.array_equal(numpy.asarray(pv.current()).flatten(), numpy.ones(16))
        pv.close()


class TestAsyncioPostDeferred:
    """On the asyncio flavor ``post_deferred`` marshals the post onto the PV's
    loop, returning a `concurrent.futures.Future`. It is both the off-loop
    escape hatch and the flavor-neutral name for deferring a post (e.g. a
    fan-out to another PV)."""

    async def test_applies_value_on_loop(self):
        pv = SharedPV(nt=NTScalar("d"))
        pv.open(0.0)
        # Called on the loop, the post is scheduled for the next iteration;
        # awaiting the Future yields control so it can run.
        await asyncio.wrap_future(pv.post_deferred(4.0))
        assert pv.current() == 4.0
        pv.close()

    async def test_propagates_exception(self):
        class Boom(Handler):
            def post(self, _pv, _value):
                msg = "boom"
                raise RuntimeError(msg)

        pv = SharedPV(handler=Boom(), nt=NTScalar("d"))
        pv.open(0.0)
        with pytest.raises(RuntimeError, match="boom"):
            await asyncio.wrap_future(pv.post_deferred(1.0))
        pv.close()


class TestInitialUpdate:
    """The asyncio flavor's half of the `InitialUpdate` tests -- see
    ``test_sharedpv_thread.py`` for the shared behaviour. What is flavor-specific
    here is that `apply_initial_update` must work *off* the event loop: a
    provider's ``add()`` legitimately runs on another thread, and this flavor's
    `_hook_guard` raises there."""

    @staticmethod
    def _pv(**kwargs) -> SharedPV:
        return SharedPV(nt=NTScalar("d", display=True, valueAlarm=True), initial={"value": 1.0}, **kwargs)

    @staticmethod
    def _stored_mask(pv) -> set[str]:
        return set(_RawSharedPV.current(pv).changedSet(expand=True))

    async def test_complete_marks_every_leaf(self):
        pv = self._pv(initial_update=InitialUpdate.COMPLETE)
        assert self._stored_mask(pv) >= _NULLABLE_LEAVES
        pv.close()

    async def test_default_marks_only_what_was_posted(self):
        pv = self._pv()
        assert self._stored_mask(pv) == {"value"}
        pv.close()

    async def test_apply_initial_update_from_a_non_loop_thread(self):
        pv = self._pv()
        # A plain pv.post() here would raise: _hook_guard asserts event-loop
        # affinity for anything but "close". apply_initial_update takes
        # _hook_lock directly, so it doesn't.
        await asyncio.to_thread(apply_initial_update, pv, InitialUpdate.COMPLETE)
        assert self._stored_mask(pv) >= _NULLABLE_LEAVES
        pv.close()

    async def test_post_from_a_non_loop_thread_still_raises(self):
        # Guards the test above against passing for the wrong reason -- if
        # off-loop posting became legal, it would prove nothing.
        pv = self._pv()
        with pytest.raises(RuntimeError):
            await asyncio.to_thread(pv.post, 2.0)
        pv.close()
