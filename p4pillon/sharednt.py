"""
Wrapper to SharedPV in p4p to automatically create
"""

from __future__ import annotations

import logging
from abc import ABC
from collections import OrderedDict
from typing import Any

from p4p import Type, Value

from p4pillon.composite_handler import CompositeHandler
from p4pillon.nt.specs import alarm_typespec, control_typespec, timestamp_typespec, valuealarm_typespec
from p4pillon.nthandlers import ComposeableRulesHandler
from p4pillon.rules import (
    AlarmNTEnumRule,
    AlarmRule,
    CalcRule,
    ControlRule,
    ScalarToArrayWrapperRule,
    TimestampRule,
    ValueAlarmRule,
)
from p4pillon.server.raw import Handler, SharedPV

logger = logging.getLogger(__name__)


def is_type_subset(fullset: Type, subset: Type) -> bool:
    """Check if the subset is a part of the fullset."""

    # For now we only support looking one level deep
    test = all(x in fullset.keys() for x in subset.keys())
    if test:
        pass
    else:
        return False

    return True


class SharedNT(SharedPV, ABC):
    """
    SharedNT is a wrapper around SharedPV that automatically adds handler
    functionality to support Normative Type logic.
    """

    def __init__(
        self,
        *,
        auth_handlers: OrderedDict[str, Handler] | None = None,
        user_handlers: OrderedDict[str, Handler] | None = None,
        handler_constructors: dict[str, Any] | None = None,
        **kwargs,
    ):
        # Check if there is a handler specified in the kwargs, and if not override it
        # with an NT handler.

        # Create a CompositeHandler. If there is no user supplied handler, and this is not
        # an NT type then it won't do anything. But it will still represent a stable interface

        if auth_handlers:
            handler = CompositeHandler(auth_handlers)
        else:
            handler = CompositeHandler()

        if "nt" in kwargs or "initial" in kwargs:
            # Get type information
            nttype: Type | None = None
            if kwargs.get("nt", None):
                try:
                    nttype = kwargs["nt"].type
                except AttributeError as exc:
                    raise NotImplementedError("Unable to determine Type of SharedNT") from exc
            else:
                if isinstance(kwargs["initial"], Value):
                    nttype = kwargs["initial"].type()

            if nttype:
                # Check if array
                ntarray = False
                if "a" in nttype["value"]:
                    ntarray = True

                # check for alarm
                if is_type_subset(nttype, Type(alarm_typespec)):
                    handler["alarm"] = ComposeableRulesHandler(AlarmRule())

                # Check for control
                if is_type_subset(nttype, Type(control_typespec)):
                    if ntarray:
                        handler["control"] = ComposeableRulesHandler(ScalarToArrayWrapperRule(ControlRule()))
                    else:
                        handler["control"] = ComposeableRulesHandler(ControlRule())

                # alarmLimit for control
                if is_type_subset(nttype, Type(alarm_typespec + valuealarm_typespec)):
                    if ntarray:
                        handler["alarm_limit"] = ComposeableRulesHandler(ScalarToArrayWrapperRule(ValueAlarmRule()))
                    else:
                        handler["alarm_limit"] = ComposeableRulesHandler(ValueAlarmRule())

                # Special cases
                if "calc" in kwargs:
                    if ntarray:
                        raise NotImplementedError("Arrays not yet supported for Calcs")
                    else:
                        handler["calc"] = ComposeableRulesHandler(CalcRule(**kwargs))
                    kwargs.pop(
                        "calc"
                    )  # Removing this from kwargs as it shouldn't be passed to super().__init__(**kwargs)

                if handler_constructors and "alarmNTEnum" in handler_constructors:
                    handler["alarmNTEnum"] = ComposeableRulesHandler(
                        AlarmNTEnumRule(handler_constructors["alarmNTEnum"])
                    )

                # Check for timestamp
                if is_type_subset(nttype, Type(timestamp_typespec)):
                    handler["timestamp"] = ComposeableRulesHandler(TimestampRule())

        if user_handlers:
            handler = handler | user_handlers
            handler.move_to_end("timestamp", last=True)  # Ensure timestamp is last

        kwargs["handler"] = handler

        super().__init__(**kwargs)

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
