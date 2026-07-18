"""Spike tests for the handler-dispatch serialization work (Options 2+5 of
the dispatch analysis).

Option 2 (thread flavor): a per-PV re-entrant lock in HandlerHooksMixin,
plus an ``_exec()`` override, serializes caller-thread open()/post()/close()
hooks against executor-side put/rpc handler execution.

Option 5: CompositeHandler owns its own re-entrant lock, covering the case
Option 2 cannot -- one handler instance shared across several PVs (whose
per-PV locks are distinct).

Asyncio flavor: serialization comes from event-loop affinity instead --
post()/open() off the loop thread raise, and post_deferred() marshals a
post onto the loop.
"""

import asyncio
import threading
import time
from contextlib import nullcontext
from typing import Any

import pytest
from p4p.nt import NTScalar

from p4pillon.composite_handler import CompositeHandler
from p4pillon.server.asyncio import SharedPV as AsyncioSharedPV
from p4pillon.server.raw import Handler
from p4pillon.server.thread import SharedPV as ThreadSharedPV


class MutexProbe:
    """Records a violation whenever two guarded sections overlap in time.

    ``enter()`` tries a non-blocking acquire of an internal lock: if another
    thread is currently inside ``enter()``, the acquire fails and the overlap
    is counted. The short sleep widens the window so genuine races are
    caught reliably rather than by luck.
    """

    def __init__(self) -> None:
        self._busy = threading.Lock()
        self.violations = 0
        self.calls = 0

    def enter(self) -> None:
        self.calls += 1
        if not self._busy.acquire(blocking=False):
            self.violations += 1
            return
        try:
            time.sleep(0.0002)
        finally:
            self._busy.release()


# Load shape for _run_post_vs_worker_load; the serialization test asserts
# every one of these entries reached the probe.
_N_POSTERS, _N_POSTS, _N_WORKER = 4, 25, 100


def _run_post_vs_worker_load(*, neutered: bool = False) -> MutexProbe:
    """Hammer one thread-flavor PV with post() hooks from foreign threads
    while feeding callables (standing in for put/rpc handler executions)
    onto its worker queue; return the probe both paths funnel through.

    With ``neutered=True`` the PV's ``_hook_lock`` is replaced by a
    `nullcontext`, removing the serialization under test. The serialization
    test and the probe-power tests share this one load, so the differential
    guarantee (same load, lock present vs absent) holds by construction.
    """
    probe = MutexProbe()

    class ProbeHandler:
        def post(self, pv: Any, value: Any) -> None:
            probe.enter()

    pv = ThreadSharedPV(handler=ProbeHandler(), nt=NTScalar("d"), initial=0.0)
    if neutered:
        pv._hook_lock = nullcontext()  # type: ignore[assignment]

    def poster() -> None:
        for i in range(_N_POSTS):
            pv.post(float(i))

    posters = [threading.Thread(target=poster) for _ in range(_N_POSTERS)]
    for t in posters:
        t.start()
    for _ in range(_N_WORKER):
        pv._exec(None, probe.enter)
    for t in posters:
        t.join()
    pv.close(sync=True)  # drain the work queue
    return probe


class TestThreadFlavorSerialization:
    """Option 2: per-PV lock + _exec override in p4pillon.server.thread.SharedPV."""

    def test_foreign_thread_posts_serialize_against_worker_callables(self):
        """post() hooks on foreign threads and callables on the PV's worker
        queue must never overlap. Both funnel through the same critical
        section (the probe); the counts prove every entry ran and none
        overlapped."""
        probe = _run_post_vs_worker_load()

        assert probe.violations == 0
        assert probe.calls == _N_POSTERS * _N_POSTS + _N_WORKER

    def test_worker_side_post_is_reentrant_not_deadlocked(self):
        """A put handler calling pv.post() runs post() on the worker thread
        while _exec already holds the PV lock -- the RLock must re-enter,
        not deadlock."""
        pv = ThreadSharedPV(handler=object(), nt=NTScalar("d"), initial=0.0)
        done = threading.Event()

        def worker_side() -> None:
            pv.post(1.0)  # what a put handler does after applying rules
            done.set()

        pv._exec(None, worker_side)
        assert done.wait(5.0), "worker-side post() deadlocked against the PV lock"
        assert pv.current() == 1.0
        pv.close(sync=True)

    def test_worker_side_read_modify_write_is_atomic(self):
        """current()+post() read-modify-write from worker-side callables must
        not lose increments to concurrent foreign-thread RMWs done under the
        same PV lock via _exec."""
        pv = ThreadSharedPV(handler=object(), nt=NTScalar("i"), initial=0)

        n_feeders, n_increments = 4, 25

        def increment() -> None:
            pv.post(pv.current() + 1)

        def feeder() -> None:
            for _ in range(n_increments):
                pv._exec(None, increment)

        feeders = [threading.Thread(target=feeder) for _ in range(n_feeders)]
        for t in feeders:
            t.start()
        for t in feeders:
            t.join()
        # close(sync=True) closes the C-level PV *before* draining the queue,
        # so drain explicitly first with the queue's own barrier.
        pv._queue.sync(timeout=10.0)

        assert pv.current() == n_feeders * n_increments
        pv.close(sync=True)


class TestCompositeHandlerSharedAcrossPVs:
    """Option 5: the handler-scoped lock covers what per-PV locks cannot."""

    def test_shared_composite_handler_serializes_across_pvs(self):
        """One CompositeHandler on two PVs: each PV's own lock is distinct,
        so only the handler's internal lock can stop rule executions for
        PV-A and PV-B overlapping."""
        probe = MutexProbe()

        class ProbeRule(Handler):
            def post(self, pv: Any, value: Any) -> None:
                probe.enter()

        shared = CompositeHandler()
        shared["probe"] = ProbeRule()

        pv_a = ThreadSharedPV(handler=shared, nt=NTScalar("d"), initial=0.0)
        pv_b = ThreadSharedPV(handler=shared, nt=NTScalar("d"), initial=0.0)

        n_posts = 50

        def poster(pv: ThreadSharedPV) -> None:
            for i in range(n_posts):
                pv.post(float(i))

        threads = [threading.Thread(target=poster, args=(pv,)) for pv in (pv_a, pv_b) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        pv_a.close(sync=True)
        pv_b.close(sync=True)

        assert probe.violations == 0
        # 2 open() calls fire no post hook; every post accounted for.
        assert probe.calls == 4 * n_posts


class TestAsyncioFlavorAffinity:
    """Asyncio flavor: loop affinity enforced, post_deferred() as the escape hatch."""

    async def test_post_on_loop_thread_is_allowed(self):
        pv = AsyncioSharedPV(nt=NTScalar("d"), initial=1.0)
        pv.post(2.0)
        assert pv.current() == 2.0

    async def test_post_from_foreign_thread_raises(self):
        pv = AsyncioSharedPV(nt=NTScalar("d"), initial=1.0)
        caught: list[BaseException] = []

        def worker() -> None:
            try:
                pv.post(2.0)
            except RuntimeError as exc:
                caught.append(exc)

        await asyncio.get_running_loop().run_in_executor(None, worker)
        assert caught, "foreign-thread post() should have raised RuntimeError"
        assert "post_deferred" in str(caught[0])
        assert pv.current() == 1.0  # the rejected post must not have stored

    async def test_post_deferred_from_foreign_thread(self):
        pv = AsyncioSharedPV(nt=NTScalar("d"), initial=1.0)

        def worker() -> None:
            pv.post_deferred(3.0).result(timeout=5.0)

        await asyncio.get_running_loop().run_in_executor(None, worker)
        assert pv.current() == 3.0

    async def test_post_deferred_propagates_exceptions_to_caller(self):
        """Wrap/rule failures must reach a waiting foreign-thread caller via
        the Future, preserving the 'poster sees the exception' semantics of
        the synchronous post() path."""
        pv = AsyncioSharedPV(nt=NTScalar("d"), initial=1.0)

        def worker() -> None:
            fut = pv.post_deferred(object())  # unwrappable -> ValueError
            with pytest.raises(ValueError, match="Unable to wrap"):
                fut.result(timeout=5.0)

        await asyncio.get_running_loop().run_in_executor(None, worker)
        assert pv.current() == 1.0


class TestProbePower:
    """Differential (mutation-style) check: prove the MutexProbe load actually
    has the power to catch the race the per-PV lock fixes. The deterministic
    half -- the real lock observing zero overlaps on the same load -- is
    `TestThreadFlavorSerialization.test_foreign_thread_posts_serialize_against_worker_callables`;
    both call `_run_post_vs_worker_load`, so "same load" holds by
    construction. If a refactor accidentally removed the probe's power (e.g.
    the sleep window vanished), the neutered run would stop finding
    violations and this guard would fail."""

    def test_probe_detects_race_when_lock_removed(self):
        """Neuter ``_hook_lock`` and the load must observe overlaps, proving
        the probe (and the serialization tests that rely on it) has real
        power. A comfortable margin keeps this off the flaky edge: with
        4 posters plus 100 worker callables racing through a ~0.2 ms window
        the count runs into the dozens-to-hundreds, so a threshold well above
        1 stays reliable while still failing loudly if the power is lost."""
        assert _run_post_vs_worker_load(neutered=True).violations > 20
