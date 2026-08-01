"""
Wrapper to SharedPV in p4p to automatically create
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

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
)
from p4pillon.server.raw import Handler, SharedPV

if TYPE_CHECKING:
    from collections import OrderedDict

logger = logging.getLogger(__name__)

_HANDLER_DECORATORS_UNSUPPORTED_MSG = "Handler decorators are not currently compatible with multiple handlers."


def is_type_subset(fullset: Type, subset: Type) -> bool:
    """Check if the subset is a part of the fullset."""

    # For now we only support looking one level deep
    test = all(x in fullset for x in subset)
    if test:
        pass
    else:
        return False

    return True


class SharedNTMixin:
    """
    SharedNTMixin adds handler functionality to support Normative Type logic
    on top of a SharedPV.

    A mixin rather than a concrete SharedPV subclass: each concurrency
    flavour (thread/asyncio) needs to combine this logic with its own real
    SharedPV base, e.g. ``class SharedNT(SharedNTMixin, _SharedPV): pass`` —
    patching an attribute onto one shared class after the fact doesn't
    change its base, so the base has to be chosen via inheritance instead.
    """

    # Deliberately mutable: it is the documented extension point for registering
    # additional rules (see examples/custom_rule/public/imatch_alarm.py). ClassVar
    # marks it as class-level, and does not prevent that.
    registered_handlers: ClassVar[list[type[BaseRule]]] = [
        AlarmRule,
        ControlRule,
        AlarmNTEnumRule,
        ValueAlarmRule,
        TimestampRule,
        CalcRule,
    ]

    def __init__(
        self,
        *,
        auth_handlers: OrderedDict[str, Handler] | None = None,
        user_handlers: OrderedDict[str, Handler] | None = None,
        registered_handlers: list[type[BaseRule]] | None = None,
        **kwargs,
    ):
        if registered_handlers:
            self.registered_handlers = registered_handlers

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

        if user_handlers:
            handler = handler | user_handlers

        # Move run_last rules (e.g. timestamp) to the end so they see the fully
        # processed value, after both the NT rules and any user handlers.
        for registered_handler in self.registered_handlers:
            if registered_handler.run_last and registered_handler.name in handler:
                handler.move_to_end(registered_handler.name, last=True)

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
                msg = "Unable to determine Type of SharedNT"
                raise NotImplementedError(msg) from exc
        else:
            if isinstance(kwargs["initial"], Value):
                nttype = kwargs["initial"].type()

        if nttype:
            ntstr = nttype.getID()

        return nttype, ntstr

    def _setup_auth_handlers(self, auth_handlers) -> CompositeHandler:
        """If an auth_handler has been given then configure a CompositeHandler with it."""
        return CompositeHandler(auth_handlers) if auth_handlers else CompositeHandler()

    @property
    def handler(self) -> CompositeHandler:
        return self._handler

    @handler.setter
    def handler(self, value: CompositeHandler):
        self._handler = value

    ## Disable handler decorators until we have a solid design.
    # Re-enable when / if possible

    @property
    def onFirstConnect(self):  # noqa: N802 - mandated by the p4p Handler protocol
        raise NotImplementedError(_HANDLER_DECORATORS_UNSUPPORTED_MSG)

    @property
    def onLastDisconnect(self):  # noqa: N802 - mandated by the p4p Handler protocol
        raise NotImplementedError(_HANDLER_DECORATORS_UNSUPPORTED_MSG)

    @property
    def on_open(self):
        raise NotImplementedError(_HANDLER_DECORATORS_UNSUPPORTED_MSG)

    @property
    def on_post(self):
        raise NotImplementedError(_HANDLER_DECORATORS_UNSUPPORTED_MSG)

    @property
    def put(self):
        raise NotImplementedError(_HANDLER_DECORATORS_UNSUPPORTED_MSG)

    @property
    def rpc(self):
        raise NotImplementedError(_HANDLER_DECORATORS_UNSUPPORTED_MSG)

    @property
    def on_close(self):
        raise NotImplementedError(_HANDLER_DECORATORS_UNSUPPORTED_MSG)

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
        """Instantiate and wrap a registered rule if it applies to this PV.

        Returns ``(name, handler, kwargs)``. ``handler`` is None when the rule
        does not apply to this PV, in which case ``kwargs`` is unchanged.
        """
        name = class_to_instantiate.name

        # Opt-in rules (add_automatically=False) are only added when the caller
        # supplies configuration for them under their name.
        if not class_to_instantiate.add_automatically and name not in kwargs:
            return (name, None, kwargs)

        # Intrinsic applicability (Type and required fields) is owned by the rule.
        if not class_to_instantiate.applies_to(nttype):
            return (name, None, kwargs)

        # Pull any constructor arguments passed under the rule's name, build the
        # rule, and adapt it to the Handler interface.
        args = kwargs.pop(name, {}) if name else {}
        instance = class_to_instantiate(**args)
        composed_instance = self.__compose_rule_handler(instance, nttype)

        return (name, composed_instance, kwargs)

    def __compose_rule_handler(self, instance: BaseRule, nttype: Type) -> ComposeableRulesHandler:
        """Adapt a rule instance to a `ComposeableRulesHandler`, inserting the
        scalar->array adapter when the rule opts in via ``wrap_for_array`` and
        the PV is an NTScalarArray."""
        if instance.wrap_for_array and is_scalararray(nttype):
            assert isinstance(instance, BaseScalarRule | BaseGatherableRule)  # noqa: S101
            return ComposeableRulesHandler(ScalarToArrayWrapperRule(instance))
        return ComposeableRulesHandler(instance)


class SharedNT(SharedNTMixin, SharedPV):
    """Default (non-flavoured) SharedNT, backed by p4pillon's raw SharedPV."""
