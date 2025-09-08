"""
Wrapper to SharedPV in p4p to automatically create
"""

from __future__ import annotations

import logging
from collections import OrderedDict

from p4pillon.composite_handler import CompositeHandler
from p4pillon.nt import NTBase, NTEnum, NTScalar
from p4pillon.nthandlers import ComposeableRulesHandler
from p4pillon.rules import (
    AlarmRule,
    ControlRule,
    ScalarToArrayWrapperRule,
    TimestampRule,
    ValueAlarmRule,
)
from p4pillon.server.raw import Handler
from p4pillon.server.thread import SharedPV

logger = logging.getLogger(__name__)


class SharedNT(SharedPV):
    """
    SharedNT is a wrapper around SharedPV that automatically adds handler
    functionality to support Normative Type logic.
    """

    def __init__(
        self,
        auth_handlers: OrderedDict[str, Handler] | None = None,
        user_handlers: OrderedDict[str, Handler] | None = None,
        **kws,
    ):
        # Check if there is a handler specified in the kws, and if not override it
        # with an NT handler.

        # Create a CompositeHandler. If there is no user supplied handler, and this is not
        # an NT type then it won't do anything. But it will still represent a stable interface

        if auth_handlers:
            handler = CompositeHandler(auth_handlers)
        else:
            handler = CompositeHandler()

        if "nt" in kws:
            nt: NTBase = kws["nt"]

            match nt:
                case NTScalar():
                    nttype_str: str = nt.type.getID()
                    if nttype_str.startswith("epics:nt/NTScalarArray"):
                        handler["control"] = ComposeableRulesHandler(ScalarToArrayWrapperRule(ControlRule()))
                        handler["alarm"] = ComposeableRulesHandler(
                            AlarmRule()
                        )  # ScalarToArrayWrapperRule unnecessary - no access to values
                        handler["alarm_limit"] = ComposeableRulesHandler(ScalarToArrayWrapperRule(ValueAlarmRule()))
                        handler["timestamp"] = ComposeableRulesHandler(TimestampRule())
                    elif nttype_str.startswith("epics:nt/NTScalar"):
                        handler["control"] = ComposeableRulesHandler(ControlRule())
                        handler["alarm"] = ComposeableRulesHandler(AlarmRule())
                        handler["alarm_limit"] = ComposeableRulesHandler(ValueAlarmRule())
                        handler["timestamp"] = ComposeableRulesHandler(TimestampRule())
                    else:
                        raise TypeError(f"Unrecognised NT type: {nttype_str}")
                case NTEnum():
                    handler["timestamp"] = ComposeableRulesHandler(TimestampRule())
                case _:
                    raise NotImplementedError(f"SharedNT does not support type: {nt.__class__.__name__}")

        if user_handlers:
            handler = handler | user_handlers
            handler.move_to_end("timestamp", last=True)  # Ensure timestamp is last

        kws["handler"] = handler

        super().__init__(**kws)

    @property
    def handler(self) -> CompositeHandler:
        return self._handler

    @handler.setter
    def handler(self, value: CompositeHandler):
        self._handler = value

    ## Disable handler decorators until we have a solid design.
    # Re-enable when / if possible

    @property
    def onFirstConnect(self):
        raise NotImplementedError("Handler decorators are not currently compatible with multiple handlers.")

    @property
    def onLastDisconnect(self):
        raise NotImplementedError("Handler decorators are not currently compatible with multiple handlers.")

    @property
    def on_open(self):
        raise NotImplementedError("Handler decorators are not currently compatible with multiple handlers.")

    @property
    def on_post(self):
        raise NotImplementedError("Handler decorators are not currently compatible with multiple handlers.")

    @property
    def put(self):
        raise NotImplementedError("Handler decorators are not currently compatible with multiple handlers.")

    @property
    def rpc(self):
        raise NotImplementedError("Handler decorators are not currently compatible with multiple handlers.")

    @property
    def on_close(self):
        raise NotImplementedError("Handler decorators are not currently compatible with multiple handlers.")

    ## Alternative PEP 8 comaptible handler decorators
    # @property
    # def on_first_connect(self):
    #     """Turn a function into an ISISHandler onFirstConnect() method."""

    #     def decorate(fn):
    #         self._handler.onFirstConnect = fn
    #         return fn

    #     return decorate

    # @property
    # def on_last_disconnect(self):
    #     """Turn a function into an ISISHandler onLastDisconnect() method."""

    #     def decorate(fn):
    #         self._handler.onLastDisconnect = fn
    #         return fn

    #     return decorate

    # @property
    # def on_put(self):
    #     """Turn a function into an ISISHandler put() method."""

    #     def decorate(fn):
    #         self._handler.put = fn
    #         return fn

    #     return decorate

    # @property
    # def on_rpc(self):
    #     """Turn a function into an ISISHandler rpc() method."""

    #     def decorate(fn):
    #         self._handler.rpc = fn
    #         return fn

    #     return decorate

    # @property
    # def on_post(self):
    #     """Turn a function into an ISISHandler post() method."""

    #     def decorate(fn):
    #         self._handler.post = fn
    #         return fn

    #     return decorate
