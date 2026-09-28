from concurrent.futures import Future

import numpy
import pytest
from p4p._p4p import SharedPV as _RawSharedPV
from p4p.nt import NTNDArray, NTScalar
from p4p.server.thread import SharedPV as _PlainSharedPV

from p4pillon.server.raw import InitialUpdate, apply_initial_update
from p4pillon.server.thread import Handler, SharedPV

# Leaves that NTScalar('d').wrap() leaves unmarked and which are strings, so a
# Java org.epics.pva client sees them as null rather than zero-filled -- the
# leaves that make the EPICS Archiver Appliance throw. See `InitialUpdate`.
_NULLABLE_LEAVES = frozenset({"alarm.message", "display.description", "display.units"})


def _stored_mask(pv) -> set[str]:
    """The PV's stored change mask -- what a client's first update carries.
    Read via the raw base class: ``pv.current()`` unwraps to a plain float."""
    return set(_RawSharedPV.current(pv).changedSet(expand=True))


def _pv(**kwargs) -> SharedPV:
    """An already-open PV with every leaf `_NULLABLE_LEAVES` names."""
    return SharedPV(nt=NTScalar("d", display=True, valueAlarm=True), initial={"value": 1.0}, **kwargs)


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


class TestInitialUpdate:
    """``initial_update=`` decides whether a PV's first update carries the
    complete structure (as a real IOC's does) or only the fields marked since
    `open()` (p4p's own behaviour). See `InitialUpdate`."""

    def test_complete_marks_every_leaf(self):
        pv = _pv(initial_update=InitialUpdate.COMPLETE)
        mask = _stored_mask(pv)
        assert mask >= _NULLABLE_LEAVES
        assert "valueAlarm.highAlarmLimit" in mask
        pv.close()

    def test_as_posted_marks_only_what_was_posted(self):
        pv = _pv(initial_update=InitialUpdate.AS_POSTED)
        assert _stored_mask(pv) == {"value"}
        pv.close()

    def test_default_is_the_default(self):
        # No initial_update= at all: DEFAULT, and DEFAULT means p4p's behaviour
        # outside p4pillon.server.records.
        pv = _pv()
        assert _stored_mask(pv) == {"value"}
        pv.close()

    def test_handler_open_hook_sees_the_unwidened_mask(self):
        # Load-bearing ordering: marking before the hook would make every
        # rule's is_applicable() see the whole structure as changed and fire
        # at open.
        seen: list[set[str]] = []

        class Recorder(Handler):
            def open(self, value):
                seen.append(set(value.changedSet(expand=True)))

        pv = _pv(handler=Recorder(), initial_update=InitialUpdate.COMPLETE)
        assert seen == [{"value"}]
        assert _stored_mask(pv) >= _NULLABLE_LEAVES
        pv.close()

    def test_survives_close_and_reopen(self):
        pv = _pv(initial_update=InitialUpdate.COMPLETE)
        pv.close()
        pv.open({"value": 2.0})
        assert _stored_mask(pv) >= _NULLABLE_LEAVES
        pv.close()


class TestApplyInitialUpdate:
    """`apply_initial_update` is the seam a provider calls to resolve a PV left
    on `~InitialUpdate.DEFAULT`. It must work *retroactively*: a PV built with
    ``initial=`` is already open, with its mask already fixed, before any
    provider sees it."""

    def test_widens_an_already_open_default_pv(self):
        pv = _pv()
        assert _stored_mask(pv) == {"value"}
        apply_initial_update(pv, InitialUpdate.COMPLETE)
        assert _stored_mask(pv) >= _NULLABLE_LEAVES
        pv.close()

    def test_leaves_an_explicit_as_posted_pv_alone(self):
        # The caller's choice outranks the server's.
        pv = _pv(initial_update=InitialUpdate.AS_POSTED)
        apply_initial_update(pv, InitialUpdate.COMPLETE)
        assert _stored_mask(pv) == {"value"}
        pv.close()

    def test_is_durable_not_just_retroactive(self):
        pv = _pv()
        apply_initial_update(pv, InitialUpdate.COMPLETE)
        pv.close()
        pv.open({"value": 2.0})
        assert _stored_mask(pv) >= _NULLABLE_LEAVES
        pv.close()

    def test_works_on_a_plain_p4p_shared_pv(self):
        # No HandlerHooksMixin: no _initial_update to set and no _hook_lock to
        # take, but the retroactive widening must still apply.
        pv = _PlainSharedPV(nt=NTScalar("d", display=True, valueAlarm=True), initial=1.0)
        apply_initial_update(pv, InitialUpdate.COMPLETE)
        assert _stored_mask(pv) >= _NULLABLE_LEAVES
        pv.close()

    def test_no_op_on_a_closed_pv(self):
        pv = SharedPV(nt=NTScalar("d", display=True, valueAlarm=True))
        apply_initial_update(pv, InitialUpdate.COMPLETE)  # must not raise
        assert not pv.isOpen()
        pv.open({"value": 1.0})
        assert _stored_mask(pv) >= _NULLABLE_LEAVES
        pv.close()

    def test_default_mode_is_a_no_op(self):
        pv = _pv()
        apply_initial_update(pv, InitialUpdate.DEFAULT)
        assert _stored_mask(pv) == {"value"}
        pv.close()

    def test_does_not_run_the_post_handler(self):
        # The widening corrects the wire format; it is not a value change, so
        # no rule should re-stamp it or re-evaluate an alarm for it.
        posts: list[object] = []

        class Recorder(Handler):
            def post(self, _pv, value):
                posts.append(value)

        pv = _pv(handler=Recorder())
        apply_initial_update(pv, InitialUpdate.COMPLETE)
        assert posts == []
        pv.close()
