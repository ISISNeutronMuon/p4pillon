"""
Composite Handler allows multiple standard handlers to be combined into a single handler.

And ordered dictionary is used to make the component handlers accessible by name.
The ordered dictionary also controls the order in which the handlers are called.
"""

from __future__ import annotations

from collections import OrderedDict

from p4p import Value
from p4p.server import ServerOperation

from p4pillon.server.raw import Handler, SharedPV


class HandlerException(Exception):
    """Exception raised for errors in the handler operations."""


class AbortHandlerException(HandlerException):
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
        for _name, handler in self.items():
            handler.open(value)

    def put(self, pv: SharedPV, op: ServerOperation):
        if self.read_only:
            errmsg = "This PV is read-only"
            op.done(error=errmsg)
            return

        errmsg = None

        for _name, handler in self.items():
            try:
                handler.put(pv, op)
            except AbortHandlerException as e:
                errmsg = e.message
                break

        if errmsg is None:
            pv.post(op.value())
            op.done()
        else:
            op.done(error=errmsg)

    def post(self, pv: SharedPV, value: Value):
        for _name, handler in self.items():
            handler.post(pv, value)

    def rpc(self, pv: SharedPV, op: ServerOperation):
        errmsg = None

        for handler in self.values():
            try:
                handler.rpc(pv, op)
            except AbortHandlerException as e:
                errmsg = e.message
                break

        op.done(error=errmsg)

    def on_first_connect(self, pv: SharedPV):
        """Called when the first client connects to the PV."""
        for handler in self.values():
            handler.onFirstConnect(pv)

    def onFirstConnect(self, pv: Value):
        self.on_first_connect(pv)

    def on_last_connect(self, pv: SharedPV):
        """Called when the last client channel is closed."""
        for handler in self.values():
            handler.onFirstConnect(pv)

    def onLastDisconnect(self, pv: Value):
        self.on_last_connect(pv)

    def close(self, pv: SharedPV):
        for handler in self.values():
            handler.close(pv)
