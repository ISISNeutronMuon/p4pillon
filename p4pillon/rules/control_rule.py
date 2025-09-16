"""
Rules for the control and control_t fields of Normative Types.
"""

import logging
from typing import SupportsFloat as Numeric

from p4p import Value

from .rules import BaseScalarRule, RulesFlow, check_applicable_init, check_applicable_post

logger = logging.getLogger(__name__)


class ControlRule(BaseScalarRule):
    """
    Apply rules implied by Normative Type control field.
    These include a minimum value change (control.minStep) and upper
    and lower limits for values (control.limitHigh and control.limitLow)
    """

    @property
    def _name(self) -> str:
        return "control"

    @property
    def _fields(self) -> list[str]:
        return ["control"]

    @check_applicable_init
    def init_rule(self, newpvstate: Value) -> RulesFlow:
        """Check whether a value should be clipped by the control limits

        NOTE: newpvstate from a put is a combination of the old and new state

        Returns None if no change should be made and the value is valid

        TODO: see if this can be separated out into a function like the
        min_step_violated to work better with arrays

        """
        logger.debug("Evaluating control.init rule")

        # Check lower and upper control limits
        if newpvstate["value"] < newpvstate["control.limitLow"]:
            newpvstate["value"] = newpvstate["control.limitLow"]
            logger.debug(
                "Lower control limit exceeded, changing value to %s",
                newpvstate["value"],
            )
            return RulesFlow.CONTINUE

        if newpvstate["value"] > newpvstate["control.limitHigh"]:
            newpvstate["value"] = newpvstate["control.limitHigh"]
            logger.debug(
                "Upper control limit exceeded, changing value to %s",
                newpvstate["value"],
            )
            return RulesFlow.CONTINUE

        return RulesFlow.CONTINUE

    @check_applicable_post
    def post_rule(self, oldpvstate: Value, newpvstate: Value) -> RulesFlow:
        logger.debug("Evaluating control.post rule")
        # Check minimum step first - if the check for the minimum step fails then we continue
        # and ignore the actual evaluation of the limits
        if __class__.min_step_violated(
            newpvstate["value"],
            oldpvstate["value"],
            newpvstate["control.minStep"],
        ):
            logger.debug("<minStep")
            newpvstate["value"] = oldpvstate["value"]

        # if the min step isn't violated, we continue and evaluate the limits themselves
        # on the value
        return self.init_rule(newpvstate)

    @classmethod
    def min_step_violated(cls, new_val, old_val, min_step) -> Numeric:
        """Check whether the new value is too small to pass a minStep threshold"""
        if old_val is None or min_step is None:
            return False

        return abs(new_val - old_val) < min_step
