"""
Rules for timeStamp fields of Normative Types.
"""

import logging
import time

from p4p import Value

from p4pillon.utils import time_in_seconds_and_nanoseconds

from .rules import BaseRule, RulesFlow, check_applicable_init

logger = logging.getLogger(__name__)


class TimestampRule(BaseRule):
    """Set current timestamp unless provided with an alternative value"""

    @property
    def _name(self) -> str:
        return "timestamp"

    @property
    def _fields(self) -> list[str]:
        return ["timeStamp"]

    def is_applicable(self, newpvstate: Value) -> bool:
        """
        Override the base class's rule because timeStamp changes are triggered
        by changes to any field and not just to the timeStamp field
        """
        # If nothing at all has changed then don't update the timeStamp
        # TODO: Check if this is expected behaviour for Normative Types
        if not newpvstate.changedSet():
            return False

        # Check if there is a timeStamp field to update!
        if "timeStamp" not in newpvstate.keys():
            return False

        return True

    @check_applicable_init
    def init_rule(self, newpvstate: Value) -> RulesFlow:
        """Update the timeStamp of a PV"""

        seconds, nanoseconds = time_in_seconds_and_nanoseconds(time.time())
        # TODO: there's a bug in the _wrap which means that timestamps are always marked as changed
        #       Fix this when that bug is fixed.
        # if "timeStamp.secondsPastEpoch" not in newpvstate.changedSet():
        if True:
            logger.debug("using secondsPastEpoch from time.time()")
            newpvstate["timeStamp.secondsPastEpoch"] = seconds
        # if "timeStamp.nanoseconds" not in newpvstate.changedSet():
        if True:
            newpvstate["timeStamp.nanoseconds"] = nanoseconds
            logger.debug("using nanoseconds from time.time()")

        return RulesFlow.CONTINUE
