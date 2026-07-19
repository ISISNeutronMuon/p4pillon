"""Thread-flavored `SharedPV` with open()/post()/close() handler support:
`p4p.server.thread.SharedPV` composed with
`~p4pillon.server.raw.HandlerHooksMixin` (see that module's docstring).
"""

from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

from p4p.server.thread import SharedPV as _ThreadSharedPV
from p4p.util import WorkQueue

from p4pillon.server.raw import Handler, HandlerHooksMixin

__all__ = ("Handler", "SharedPV")


class SharedPV(HandlerHooksMixin, _ThreadSharedPV):
    """`p4p.server.thread.SharedPV` plus the open()/post()/close() handler
    callbacks -- see `~p4pillon.server.raw.HandlerHooksMixin` for their
    semantics and locking. Because the C-extension store also happens under
    the per-PV lock, a read-modify-write against ``pv.current()`` from
    inside a handler is atomic.
    """

    # Set by p4p.server.thread.SharedPV.__init__ (the PV's own work queue).
    _queue: WorkQueue

    def post_deferred(self, value: Any, **kwargs: Any) -> Future[None]:
        """Enqueue a `post` onto this PV's own work queue, returning a
        `concurrent.futures.Future` that resolves once it has run there;
        wrapping and handler exceptions propagate through it.

        Unlike `post`, which runs synchronously on the caller's thread and
        holds ``_hook_lock`` across the whole hook, ``post_deferred`` hands
        the work to the queue. That lets a handler fan a change out to
        *another* PV (``other.post_deferred(v)``) without nesting that PV's
        lock inside its own -- the lock order forbidden by
        `~p4pillon.server.raw.HandlerHooksMixin` -- and keeps a failure in
        the deferred post from aborting the caller's own post: it surfaces on
        the returned Future instead.

        This is the thread-flavor counterpart of the asyncio flavor's
        `~p4pillon.server.asyncio.SharedPV.post_deferred` (there, marshalling
        onto the event loop); both return a `concurrent.futures.Future`, so a
        handler can defer a post the same way regardless of flavor.
        """
        # post() is synchronous, so a plain queued callback suffices; the
        # shared Future plumbing (routing every exception to the Future rather
        # than letting the queue's _on_queue log-and-swallow it) lives in
        # HandlerHooksMixin._deferred_post.
        return self._deferred_post(self._queue.push, value, kwargs)

    def _exec(self, op: Any, fn: Callable[..., Any], *args: Any) -> None:
        """Run ``fn`` on the PV's work queue under ``_hook_lock``, so
        executor-side handlers serialize with the open()/post()/close() hooks.

        ``_run_locked`` is a bound method rather than a closure: _exec is the
        dispatch funnel for every put/rpc, and the base class already packs
        extra args into the queued partial."""
        super()._exec(op, self._run_locked, fn, *args)

    def _run_locked(self, fn: Callable[..., Any], *args: Any) -> None:
        with self._hook_lock:
            fn(*args)
