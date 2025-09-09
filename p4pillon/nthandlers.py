"""Handler for NTScalar (so far)"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable

from p4p import Value
from p4p.server import ServerOperation

from p4pillon.composite_handler import AbortHandlerException
from p4pillon.server.raw import Handler, SharedPV
from p4pillon.utils import overwrite_unmarked

from .rules import (
    AlarmRule,
    BaseRule,
    ControlRule,
    ReadOnlyRule,
    RulesFlow,
    ScalarToArrayWrapperRule,
    TimestampRule,
    ValueAlarmRule,
)

logger = logging.getLogger(__name__)


class BaseRulesHandler(Handler):
    """
    Base class for handlers used to implement Normative Type handling.
    """

    def __init__(self) -> None:
        super().__init__()

        # Name is used purely for logging. Because the name of the PV is stored by
        # the Server and not the PV object associated with this handler we can't
        # determine the name until the first put operation
        self._name: str | None = None  # Used purely for logging
        self.rules: OrderedDict[str, BaseRule] = OrderedDict({"timestamp": TimestampRule()})

    def __getitem__(self, rule_name: str) -> BaseRule | None:
        """Allow access to the rules so that parameters such as read_only may be set"""
        return self.rules.get(rule_name)

    def open(self, value: Value) -> None:
        """Handler call by an open operation."""
        self._apply_rules(lambda x: x.init_rule(value))

    def post(self, pv: SharedPV, value: Value) -> None:
        """Handler call by a post operation, requires support from SharedPV derived class"""
        logger.debug("In handler post()")

        try:
            pv_value = pv.current().raw
        except AttributeError:
            pv_value = pv.current()

        overwrite_unmarked(pv_value, value)

        self._apply_rules(lambda x: x.post_rule(pv_value, value))

    def put(self, pv: SharedPV, op: ServerOperation) -> None:
        """
        Handler triggered by put operations. Note that this has additional information
        about the source of the put such as the IP address of the caller.
        """
        logger.debug("In handler put()")

        # Maybe risky to do the try except in this form, but presumably the
        # types of pv and op will match?
        try:
            pv_value = pv.current().raw
            op_value = op.value().raw
        except AttributeError:
            pv_value = pv.current()
            op_value = op.value()

        overwrite_unmarked(pv_value, op_value)

        rules_flow = self._apply_rules(lambda x: x.put_rule(pv_value, op_value, op))
        if rules_flow != RulesFlow.ABORT:
            pv.post(value=op.value())
            op.done()
        else:
            op.done(error=rules_flow.error)

    def _apply_rules(self, apply_rule: Callable[[BaseRule], RulesFlow]) -> RulesFlow:
        """
        Apply the rules. Primarily this does the basic handling of the RulesFlow.
        """

        for rule_name, rule in self.rules.items():
            logger.debug("Applying rule %s", rule_name)

            rule_flow = apply_rule(rule)

            # Originally a more elegant match (rule_flow): but we need
            # to support versions of Python prior to 3.10
            if rule_flow == RulesFlow.CONTINUE:
                pass
            elif rule_flow == RulesFlow.ABORT:
                logger.debug("Rule %s triggered handler abort", rule_name)
                return rule_flow
            elif rule_flow == RulesFlow.TERMINATE:
                logger.debug("Rule %s triggered handler terminate", rule_name)
                if "timestamp" in self.rules:
                    rule_flow = apply_rule(self.rules["timestamp"])
                return rule_flow
            elif rule_flow == RulesFlow.TERMINATE_WO_TIMESTAMP:
                logger.debug("Rule %s triggered handler terminate without timestamp", rule_name)
                return rule_flow
            else:
                logger.error("Rule %s returned unhandled return type", rule_name)
                raise TypeError(f"Rule {rule_name} returned unhandled return type {type(rule_flow)}")

        return RulesFlow.CONTINUE

    def set_read_only(self, read_only: bool = True, read_only_rule: BaseRule = ReadOnlyRule()):
        """
        Make this PV read only.
        If read_only == False then the PV is made writable
        A rule to replace the default ReadOnlyRule implementation may be passed in
        """
        if read_only:
            # Switch on the read-only rule and make sure it's the first rule
            self.rules["read_only"] = read_only_rule
            self.rules.move_to_end("read_only", last=False)
        else:
            # Switch off the read-only rule by deleting it
            self.rules.pop("read_only", None)


class ComposeableRulesHandler(Handler):
    """
    Convert the Rules interface to a simple Handler interface.
    """

    def __init__(self, rule: BaseRule) -> None:
        super().__init__()
        self.rule = rule

    def open(self, value: Value) -> None:
        """Handler call by an open operation."""
        logger.debug("In handler open()")
        self.rule.init_rule(value)

    def post(self, pv: SharedPV, value: Value) -> None:
        """Handler call by a post operation, requires support from SharedPV derived class"""
        logger.debug("In handler post()")

        try:
            pv_value = pv.current().raw
        except AttributeError:
            pv_value = pv.current()

        overwrite_unmarked(pv_value, value)

        self.rule.post_rule(pv_value, value)

    def put(self, pv: SharedPV, op: ServerOperation) -> None:
        """
        Handler triggered by put operations. Note that this has additional information
        about the source of the put such as the IP address of the caller.
        """
        logger.debug("In handler put()")

        # Maybe risky to do the try except in this form, but presumably the
        # types of pv and op will match?
        try:
            pv_value = pv.current().raw
            op_value = op.value().raw
        except AttributeError:
            pv_value = pv.current()
            op_value = op.value()

        overwrite_unmarked(pv_value, op_value)

        rules_flow = self.rule.put_rule(pv_value, op_value, op)
        if rules_flow == RulesFlow.ABORT:
            raise AbortHandlerException(rules_flow.error)

    @property
    def read_only(self) -> bool:
        """
        Set rule as resd_only.
        """
        return self.rule.read_only

    @read_only.setter
    def read_only(self, read_only: bool):
        self.rule.read_only = read_only


class NTScalarRulesHandler(BaseRulesHandler):
    """
    Rules handler for NTScalar PVs.
    """

    def __init__(self) -> None:
        super().__init__()

        self.rules["control"] = ControlRule()
        self.rules["alarm"] = AlarmRule()
        self.rules["alarm_limit"] = ValueAlarmRule()
        self.rules.move_to_end("timestamp")


class NTScalarArrayRulesHandler(BaseRulesHandler):
    """
    Rules handler for NTScalarArray PVs.
    """

    def __init__(self) -> None:
        super().__init__()

        self.rules["control"] = ScalarToArrayWrapperRule(ControlRule())
        self.rules["alarm"] = AlarmRule()  # ScalarToArrayWrapperRule unnecessary - no access to values
        self.rules["alarm_limit"] = ScalarToArrayWrapperRule(ValueAlarmRule())
        self.rules.move_to_end("timestamp")


class NTEnumRulesHandler(BaseRulesHandler):
    """
    Rules handler for NTScalarArray PVs.
    """
