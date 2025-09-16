"""
Wrapper to SharedPV in p4p to automatically create
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any

from p4p import Value

from p4pillon.composite_handler import CompositeHandler
from p4pillon.nthandlers import ComposeableRulesHandler
from p4pillon.rules import (
    AlarmNTEnumRule,
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
        handler_constructors: dict[str, Any] | None = None,
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

        if "nt" in kws or "initial" in kws:
            nttype_str: str = ""
            if kws.get("nt", None):
                try:
                    nttype_str = kws["nt"].type.getID()
                except AttributeError:
                    nttype_str = f"{type(kws['nt'])}"
            else:
                if isinstance(kws["initial"], Value):
                    nttype_str = kws["initial"].getID()

            match nttype_str:
                case s if s.startswith("epics:nt/NTScalar"):
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
                case s if s.startswith("epics:nt/NTEnum"):
                    handler["alarm"] = ComposeableRulesHandler(AlarmRule())

                    alarm_ntenum_constructor = None
                    if handler_constructors:
                        alarm_ntenum_constructor = handler_constructors.get("alarmNTEnum", None)
                    handler["alarmNTEnum"] = ComposeableRulesHandler(AlarmNTEnumRule(alarm_ntenum_constructor))
                    handler["timestamp"] = ComposeableRulesHandler(TimestampRule())
                case _:
                    if not nttype_str:
                        nttype_str = "Unknown"
                    raise NotImplementedError(f"SharedNT does not support type: {nttype_str}")

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
