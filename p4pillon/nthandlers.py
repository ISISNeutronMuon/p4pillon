"""Handler for NTScalar (so far)"""

from __future__ import annotations

import logging

from p4p import Value
from p4p.server import ServerOperation

from p4pillon.composite_handler import AbortHandlerException
from p4pillon.rules import BaseRule, RulesFlow
from p4pillon.server.raw import Handler, SharedPV
from p4pillon.utils import overwrite_unmarked

logger = logging.getLogger(__name__)


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
