"""
Composite Handler allows multiple standard handlers to be combined into a single handler.

And ordered dictionary is used to make the component handlers accessible by name.
The ordered dictionary also controls the order in which the handlers are called.
"""

from __future__ import annotations

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
    """Composite Handler for combining multiple component handlers into a single handler."""

    def __init__(self, *args, **kwargs):
        OrderedDict.__init__(self, *args, **kwargs)
        Handler.__init__(self)

        self.read_only = False

    def open(self, value: Value):
        """Open all handlers in the composite handler."""
        for handler in self.values():
            handler.open(value)

    def put(self, pv: SharedPV, op: ServerOperation):
        if self.read_only:
            errmsg = "This PV is read-only"
            op.done(error=errmsg)
            return

        errmsg = None

        for handler in self.values():
            try:
                handler.put(pv, op)
            except AbortHandlerError as e:  # noqa: PERF203 -- per-item error handling around I/O, breaks on first failure
                errmsg = e.message
                break

        if errmsg is None:
            pv.post(op.value())
            op.done()
        else:
            op.done(error=errmsg)

    def post(self, pv: SharedPV, value: Value):
        for handler in self.values():
            handler.post(pv, value)

    def rpc(self, pv: SharedPV, op: ServerOperation):
        errmsg = None

        for handler in self.values():
            try:
                handler.rpc(pv, op)
            except AbortHandlerError as e:  # noqa: PERF203 -- per-item error handling around I/O, breaks on first failure
                errmsg = e.message
                break

        op.done(error=errmsg)

    def on_first_connect(self, pv: SharedPV):
        """Called when the first client connects to the PV."""
        for handler in self.values():
            handler.onFirstConnect(pv)

    def onFirstConnect(self, pv: Value):  # noqa: N802 - mandated by the p4p Handler protocol
        self.on_first_connect(pv)

    def on_last_disconnect(self, pv: SharedPV):
        """Called when the last client channel is closed."""
        for handler in self.values():
            handler.onLastDisconnect(pv)

    def onLastDisconnect(self, pv: Value):  # noqa: N802 - mandated by the p4p Handler protocol
        self.on_last_disconnect(pv)

    def close(self, pv: SharedPV):
        for handler in self.values():
            handler.close(pv)
