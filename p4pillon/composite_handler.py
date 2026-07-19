"""
Composite Handler allows multiple standard handlers to be combined into a single handler.

And ordered dictionary is used to make the component handlers accessible by name.
The ordered dictionary also controls the order in which the handlers are called.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import TYPE_CHECKING

from p4pillon.server.raw import Handler, SharedPV

if TYPE_CHECKING:
    from p4p import Value
    from p4p.server import ServerOperation


class HandlerError(Exception):
    """Exception raised for errors in the handler operations."""


class AbortHandlerError(HandlerError):
    """Exception raised to abort the current operation in the handler."""

    def __init__(self, message: str = "Operation aborted"):
        super().__init__(message)
        self.message = message


class CompositeHandler(Handler, OrderedDict):
    """Composite Handler for combining multiple component handlers into a single handler.

    A re-entrant lock serializes the component handlers. The per-PV lock in
    `~p4pillon.server.raw.HandlerHooksMixin` only covers one PV, so this
    handler-scoped lock is what protects component state when the same
    CompositeHandler instance is shared across several PVs.

    Lock ordering: a PV's lock is always acquired before this one, so
    component handlers must never call *another* PV's open()/post()/close()
    while this lock is held. Posting back to the *same* PV (as put() does)
    is safe: both locks are re-entrant.
    """

    def __init__(self, *args, **kwargs):
        OrderedDict.__init__(self, *args, **kwargs)
        Handler.__init__(self)

        self.read_only = False
        self._lock = threading.RLock()

    def _dispatch(self, hook: str, *args) -> None:
        """Call ``hook`` on every component handler, serialized by the handler lock."""
        with self._lock:
            for handler in self.values():
                getattr(handler, hook)(*args)

    def _dispatch_abortable(self, hook: str, pv: SharedPV, op: ServerOperation) -> str | None:
        """As `_dispatch`, but stop at the first `AbortHandlerError` and
        return its message (None if no handler aborted)."""
        with self._lock:
            return self._dispatch_abortable_locked(hook, pv, op)

    def _dispatch_abortable_locked(self, hook: str, pv: SharedPV, op: ServerOperation) -> str | None:
        """`_dispatch_abortable`'s body, assuming the handler lock is already
        held -- `put` calls this directly under the lock it already holds
        across the following `pv.post()`, avoiding a redundant re-entry."""
        for handler in self.values():
            try:
                getattr(handler, hook)(pv, op)
            except AbortHandlerError as e:  # noqa: PERF203 -- per-item error handling, breaks on first failure
                return e.message
        return None

    def open(self, value: Value):
        """Open all handlers in the composite handler."""
        self._dispatch("open", value)

    def put(self, pv: SharedPV, op: ServerOperation):
        if self.read_only:
            op.done(error="This PV is read-only")
            return

        with self._lock:
            errmsg = self._dispatch_abortable_locked("put", pv, op)

            # pv.post() safely re-enters this lock; it must stay inside so
            # the handler rules and the store are one atomic unit.
            if errmsg is None:
                pv.post(op.value())

        # op.done() touches no handler state, so it runs outside the lock.
        # error=None is the success case, matching rpc() below.
        op.done(error=errmsg)

    def post(self, pv: SharedPV, value: Value):
        self._dispatch("post", pv, value)

    def rpc(self, pv: SharedPV, op: ServerOperation):
        op.done(error=self._dispatch_abortable("rpc", pv, op))

    def on_first_connect(self, pv: SharedPV):
        """Called when the first client connects to the PV."""
        self._dispatch("onFirstConnect", pv)

    def onFirstConnect(self, pv: Value):  # noqa: N802 - mandated by the p4p Handler protocol
        self.on_first_connect(pv)

    def on_last_disconnect(self, pv: SharedPV):
        """Called when the last client channel is closed."""
        self._dispatch("onLastDisconnect", pv)

    def onLastDisconnect(self, pv: Value):  # noqa: N802 - mandated by the p4p Handler protocol
        self.on_last_disconnect(pv)

    def close(self, pv: SharedPV):
        self._dispatch("close", pv)
