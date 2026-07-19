"""
Rules for timeStamp fields of Normative Types.
"""

import logging
import time
from typing import ClassVar

from p4p import Value

from p4pillon.utils import time_in_seconds_and_nanoseconds

from .rules import BaseRule, RulesFlow, SupportedNTTypes, check_applicable_init

logger = logging.getLogger(__name__)


class TimestampRule(BaseRule):
    """Set current timestamp unless provided with an alternative value"""

    name = "timestamp"
    nttypes: ClassVar[list[SupportedNTTypes] | None] = [SupportedNTTypes.ALL]
    fields: ClassVar[list[str] | None] = ["timeStamp"]
    run_last: ClassVar[bool] = True  # timeStamp must be stamped after all other rules/handlers

    type = SupportedNTTypes.ALL

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
        return "timeStamp" in newpvstate

    @check_applicable_init
    def init_rule(self, newpvstate: Value) -> RulesFlow:
        """Update the timeStamp of a PV"""

        seconds, nanoseconds = time_in_seconds_and_nanoseconds(time.time())
        # Stamp the current time only into a timeStamp component the caller did
        # not set themselves; a caller-provided timeStamp is preserved. This
        # relies on the changed-set faithfully reflecting the caller's intent:
        # CompositeHandler.put posts the raw client Value (not the unwrapped
        # op.value()), so timeStamp is only marked changed here when the client
        # actually set it, not as a re-wrap artefact.
        if "timeStamp.secondsPastEpoch" not in newpvstate.changedSet():
            logger.debug("using secondsPastEpoch from time.time()")
            newpvstate["timeStamp.secondsPastEpoch"] = seconds
        if "timeStamp.nanoseconds" not in newpvstate.changedSet():
            newpvstate["timeStamp.nanoseconds"] = nanoseconds
            logger.debug("using nanoseconds from time.time()")

        return RulesFlow.CONTINUE
