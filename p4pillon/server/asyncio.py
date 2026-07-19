"""Asyncio-flavored `SharedPV` with open()/post()/close() handler support:
`p4p.server.asyncio.SharedPV` composed with
`~p4pillon.server.raw.HandlerHooksMixin` (see that module's docstring).
"""

import asyncio
from concurrent.futures import Future
from contextlib import AbstractContextManager
from typing import Any

from p4p.server.asyncio import SharedPV as _AsyncioSharedPV

from p4pillon.server.raw import Handler, HandlerHooksMixin

__all__ = ("Handler", "SharedPV")


class SharedPV(HandlerHooksMixin, _AsyncioSharedPV):
    """`p4p.server.asyncio.SharedPV` plus the open()/post()/close() handler
    callbacks -- see `~p4pillon.server.raw.HandlerHooksMixin` for their
    semantics. The callbacks run synchronously and may not be coroutines
    (unlike put()/rpc(), which p4p schedules on the event loop).

    **Threading:** serialization here comes from event-loop affinity rather
    than cross-thread locking: put/rpc handlers run on the PV's event loop,
    so open() and post() must be called from that loop too (a call from any
    other thread raises `RuntimeError`; use `post_deferred` instead). A
    cross-thread lock could block the event loop, and a coroutine put
    handler would escape it at its first ``await`` anyway. close() is not
    affinity-checked (shutdown paths legitimately run off-loop); the mixin's
    ``_hook_lock`` is what keeps an off-loop close hook from overlapping an
    on-loop open/post hook.
    """

    # Set by p4p.server.asyncio.SharedPV.__init__ before any open() can run.
    loop: asyncio.AbstractEventLoop

    def _assert_loop_affinity(self, what: str) -> None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not self.loop:
            msg = (
                f"{what}() on an asyncio SharedPV must be called from its own event loop; "
                "use post_deferred() from other threads"
            )
            raise RuntimeError(msg)

    def _hook_guard(self, what: str) -> AbstractContextManager[Any]:
        """As `HandlerHooksMixin._hook_guard`, plus the affinity check: open()
        and post() must run on the PV's event loop. close() is exempt --
        shutdown paths legitimately run off-loop."""
        if what != "close":
            self._assert_loop_affinity(what)
        return self._hook_lock

    def post_deferred(self, value: Any, **kwargs: Any) -> Future[None]:
        """Defer a `post`: marshal it onto the PV's event loop, returning a
        `concurrent.futures.Future` that resolves once it has run there;
        wrapping and handler exceptions propagate through it.

        This is both the off-loop escape hatch (open()/post() called from any
        other thread raise; this is how you post from one) and the
        flavor-neutral name a handler uses to defer a post -- e.g. to fan a
        change out to another PV without nesting its lock. On this flavor the
        two coincide: marshalling onto the loop *is* the deferral. The thread
        flavor provides a matching `~p4pillon.server.thread.SharedPV.post_deferred`
        backed by its work queue, so a handler can defer a post the same way
        regardless of flavor.
        """
        # post() is synchronous, so a plain callback suffices -- no need for
        # the coroutine + Task that run_coroutine_threadsafe would allocate
        # per post on this (by design, high-frequency) path. The shared Future
        # plumbing lives in HandlerHooksMixin._deferred_post.
        return self._deferred_post(self.loop.call_soon_threadsafe, value, kwargs)
