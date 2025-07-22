"""
Composite Handler allows multiple standard handlers to be combined into a single handler.

And ordered dictionary is used to make the component handlers accessible by name.
The ordered dictionary also controls the order in which the handlers are called.
"""

from __future__ import annotations

from collections import OrderedDict

from p4p import Value
from p4p.server import ServerOperation
from p4p.server.raw import Handler, SharedPV


class HandlerException(Exception):
    """Exception raised for errors in the handler operations."""


class AbortHandlerException(HandlerException):
    """Exception raised to abort the current operation in the handler."""

    def __init__(self, message: str = "Operation aborted"):
        super().__init__(message)
        self.message = message


class CompositeHandler(Handler):
    """Composite Handler for combining multiple component handlers into a single handler."""

    def __init__(self, handlers: OrderedDict[str, Handler] | None = None):
        """Initialize the CompositeHandler with an optional list of handlers."""
        super().__init__()
        self.handlers = handlers

    def __getitem__(self, name: str) -> Handler | None:
        if self.handlers:
            return self.handlers[name]

        return None

    def open(self, value: Value):
        """Open all handlers in the composite handler."""
        if self.handlers:
            for handler in self.handlers.values():
                handler.open(value)

    def put(self, pv: SharedPV, op: ServerOperation):
        errmsg = None

        if self.handlers:
            for handler in self.handlers.values():
                try:
                    handler.put(pv, op)
                except AbortHandlerException as e:
                    errmsg = e.message
                    break

        op.done(error=errmsg)

    def post(self, pv: SharedPV, value: Value):
        if self.handlers:
            for handler in self.handlers.values():
                handler.post(pv, value)

    def rpc(self, pv: SharedPV, op: ServerOperation):
        errmsg = None

        if self.handlers:
            for handler in self.handlers.values():
                try:
                    handler.rpc(pv, op)
                except AbortHandlerException as e:
                    errmsg = e.message
                    break

        op.done(error=errmsg)

    def on_first_connect(self, pv: SharedPV):
        """Called when the first client connects to the PV."""
        if self.handlers:
            for handler in self.handlers.values():
                handler.onFirstConnect(pv)

    def onFirstConnect(self, pv: Value):
        self.on_first_connect(pv)

    def on_last_connect(self, pv: SharedPV):
        """Called when the last client channel is closed."""
        if self.handlers:
            for handler in self.handlers.values():
                handler.onFirstConnect(pv)

    def onLastDisconnect(self, pv: Value):
        self.on_last_connect(pv)

    def close(self, pv: SharedPV):
        if self.handlers:
            for handler in self.handlers.values():
                handler.close(pv)
