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
from p4pillon.nt.identify import is_scalararray
from p4pillon.nthandlers import ComposeableRulesHandler
from p4pillon.rules import (
    AlarmNTEnumRule,
    AlarmRule,
    CalcRule,
    ControlRule,
    TimestampRule,
    ValueAlarmRule,
)
from p4pillon.rules.rules import (
    BaseGatherableRule,
    BaseRule,
    BaseScalarRule,
    ScalarToArrayWrapperRule,
    SupportedNTTypes,
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

    registered_handlers: list[type[BaseRule]] = [
        AlarmRule,
        ControlRule,
        ValueAlarmRule,
        TimestampRule,
        CalcRule,
    ]

    def __init__(
        self,
        *,
        auth_handlers: OrderedDict[str, Handler] | None = None,
        user_handlers: OrderedDict[str, Handler] | None = None,
        handler_constructors: dict[str, Any] | None = None,
        **kwargs,
    ):
        # Create a CompositeHandler. If there is no user supplied handler, and this is not
        # an NT type then it won't do anything. Unfortunately, an empty CompositeHandler
        # will be discarded and won't be passed to the super().__init__
        handler = self._setup_auth_handlers(auth_handlers)

        # We need either `nt` or `initial` in order to determine the type of the
        if "nt" in kwargs or "initial" in kwargs:
            # Get type information
            (nttype, _) = self.get_ntinfo(kwargs)

            if nttype:
                for registered_handler in self.registered_handlers:
                    name, component_handler, kwargs = self.__setup_registered_rule(registered_handler, nttype, **kwargs)
                    if name and component_handler:
                        handler[name] = component_handler

                if handler_constructors and "alarmNTEnum" in handler_constructors:
                    handler["alarmNTEnum"] = ComposeableRulesHandler(
                        AlarmNTEnumRule(handler_constructors["alarmNTEnum"])
                    )

        if user_handlers:
            handler = handler | user_handlers

        if "timestamp" in handler:
            handler.move_to_end("timestamp", last=True)  # Ensure timestamp is last

        kwargs["handler"] = handler

        super().__init__(**kwargs)

    def get_ntinfo(self, kwargs) -> tuple[Type | None, str | None]:
        """
        Based on the arguments passed into __init__ determine the type of the Normative Type if possible.
        Returns a tuple of the Type and ID (str).
        """
        nttype: Type | None = None
        ntstr: str | None = None
        if kwargs.get("nt", None):
            try:
                nttype = kwargs["nt"].type
            except AttributeError as exc:
                raise NotImplementedError("Unable to determine Type of SharedNT") from exc
        else:
            if isinstance(kwargs["initial"], Value):
                nttype = kwargs["initial"].type()

        if nttype:
            ntstr = nttype.getID()

        return nttype, ntstr

    def _setup_auth_handlers(self, auth_handlers) -> CompositeHandler:
        """If an auth_handler has been given then configure a CompositeHandler with it."""
        if auth_handlers:
            handler = CompositeHandler(auth_handlers)
        else:
            handler = CompositeHandler()
        return handler

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

    def __setup_registered_rule(
        self, class_to_instantiate: type[BaseRule], nttype, **kwargs
    ) -> tuple[str | None, ComposeableRulesHandler | None, dict[str, Any]]:
        """The existence of a single function that does everything suggests this is the wrong approach!"""

        # Examine the class member variables to determine how/whether to setup this Rule
        name = class_to_instantiate.name
        supported_nttypes = class_to_instantiate.nttypes
        required_fields = class_to_instantiate.fields
        wrap_for_array = class_to_instantiate.wrap_for_array
        auto_add = class_to_instantiate.add_automatically

        # If we're not relying on the rule to provide enough information to configure itself then
        if not auto_add and name not in kwargs:
            return (name, None, kwargs)

        # Perform tests on whether the rule is applicable to the nttype and/or the fields
        if supported_nttypes:
            if len(supported_nttypes) == 1 and supported_nttypes == [SupportedNTTypes.ALL]:
                pass
            else:
                raise NotImplementedError("We're not yet testing for NT type!")

        if required_fields:
            for required_field in required_fields:
                if required_field not in nttype:
                    return (name, None, kwargs)

        # See if there's an attempt to pass arguments to the constructor of this Rule
        args = {}
        if name:
            args = kwargs.pop(name, {})

        # We're clear to instantiate the Rule - it's needed!
        instance = class_to_instantiate(**args)

        # Check if we need special handling for array data
        if wrap_for_array and is_scalararray(nttype):
            assert isinstance(instance, BaseScalarRule | BaseGatherableRule)
            composed_instance = ComposeableRulesHandler(ScalarToArrayWrapperRule(instance))
        else:
            composed_instance = ComposeableRulesHandler(instance)

        return (name, composed_instance, kwargs)
