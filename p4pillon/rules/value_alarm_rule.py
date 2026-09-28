"""
Rules for the valueAlarm fields of NTScalar and NTScalarArray Normative Types.
"""

import logging
import math
import operator
from collections.abc import Callable
from typing import Any, ClassVar

from p4p import Value

from p4pillon.definitions import AlarmSeverity, AlarmStatus

from .rules import BaseGatherableRule, RulesFlow, check_applicable_init

logger = logging.getLogger(__name__)


class ValueAlarmRule(BaseGatherableRule):
    """
    Rule to check whether valueAlarm limits have been triggered, changing
    alarm.severity and alarm.message appropriately.

    The Normative Types specification gives the check order and the comparisons,
    but is silent on how the result combines with an alarm already carried by the
    update. The canonical implementation is EPICS base record support (pvxs/QSRV
    only mirrors record metadata into ``valueAlarm``; it performs no checks of its
    own), and base *maximises*: ``recGblSetSevrVMsg`` writes only when
    ``prec->nsev < new_sevr``, so the highest severity contributed during a
    processing cycle wins and the first contributor at that severity keeps the
    message. ``recGblResetAlarms`` then zeroes ``nsev``, so nothing latches across
    cycles. This rule follows base: see :meth:`incoming_severity`.

    TODO: Implement hysteresis. Base does it with ``LALM``, which holds the *limit
    value* that was latched, not the previous severity::

        val >= alev || (lalm == alev && val >= alev - hyst)      # aiRecord.c

    so hysteresis widens only the limit that is currently latched, applies to all
    four limits, and never delays *entering* an alarm state. p4pillon has nowhere
    to keep ``LALM``: it can be reconstructed from ``alarm.message`` (which names
    the latched limit) plus that limit's current value, but only while the limits
    themselves do not move in the same post. Arrays are worse -- base has one
    ``LALM`` per record, so an array needs one per element and
    ``ScalarToArrayWrapperRule`` carries no per-element state at all. Decide where
    that state lives before implementing this.
    """

    name = "alarm_limit"
    fields: ClassVar[list[str] | None] = ["alarm", "valueAlarm"]
    wrap_for_array = True

    #: The limit checks in the order the Normative Types specification requires,
    #: each paired with the comparison it makes against the value.
    LIMIT_CHECKS: ClassVar[tuple[tuple[str, Callable[[Any, Any], bool]], ...]] = (
        ("highAlarm", operator.ge),
        ("lowAlarm", operator.le),
        ("highWarning", operator.ge),
        ("lowWarning", operator.le),
    )

    #: ``alarm.message`` for an undefined (NaN) value, after base's UDF_ALARM.
    UDF_MESSAGE = "UDF"

    @check_applicable_init
    def init_rule(self, newpvstate: Value) -> RulesFlow:
        """Evaluate alarm value limits"""
        logger.debug("Evaluating %s.init_rule", self.name)

        limit_severity, limit_message, status = self.__alarm_from_limits(newpvstate)
        incoming_severity = self.incoming_severity(newpvstate)

        # Maximise against what the update brought with it, as base does; see the
        # class docstring. Whatever supplied the value contributed first, so on a tie
        # its alarm keeps the message.
        if incoming_severity and incoming_severity >= limit_severity:
            logger.debug("\tupdate supplied severity %i; leaving the alarm alone", incoming_severity)
            return RulesFlow.CONTINUE

        self.__set_status(newpvstate, status)

        if limit_severity:
            newpvstate["alarm.severity"] = limit_severity
            newpvstate["alarm.message"] = limit_message
            logger.debug("Setting to severity %i with message '%s'", limit_severity, limit_message)
            return RulesFlow.CONTINUE

        # If we made it here then there are no alarms or warnings and we need to indicate that
        # possibly by resetting any existing ones
        if not self.__clear_alarm(newpvstate):
            logger.debug("Made no automatic changes to alarm state.")

        return RulesFlow.CONTINUE

    @staticmethod
    def incoming_severity(pvstate: Value) -> int:
        """The alarm severity this update brought with it, if any.

        This is base's ``prec->nsev``: the severity contributed during the current
        processing cycle, which the limit verdict is then maximised against. Only
        an alarm arriving *with* the update counts -- one left over from a previous
        update (present but unmarked, because ``overwrite_unmarked`` filled it in)
        is base's ``prec->sevr`` from the last cycle and makes no assertion about
        the new value.
        """
        return int(pvstate["alarm.severity"]) if pvstate.changed("alarm.severity") else AlarmSeverity.NO_ALARM

    @classmethod
    def __alarm_from_limits(cls, pvstate: Value) -> tuple[int, str, AlarmStatus | None]:
        """What this rule alone makes of the value.

        Returns the severity, the message, and the status to set -- ``None`` where
        the rule has no opinion on the status, which is the usual case. A severity
        of ``NO_ALARM`` means the caller should clear any alarm this rule left
        behind earlier.
        """
        value = pvstate["value"]
        if isinstance(value, float) and math.isnan(value):
            # An undefined value. Base tests this before, and independently of, the
            # limits (aiRecord.c sets udf = isnan(val), and checkAlarms returns
            # UDF_ALARM at severity UDFS -- INVALID_ALARM by default -- straight
            # away). The Normative Types specification says nothing about NaN.
            logger.debug("\tvalue is NaN: undefined")
            return AlarmSeverity.INVALID_ALARM, cls.UDF_MESSAGE, AlarmStatus.UNDEFINED_STATUS

        if not pvstate["valueAlarm.active"]:
            # The value is no longer being checked, so any alarm this rule raised
            # while it was being checked is stale and is cleared by the caller.
            logger.debug("\tvalueAlarm not active")
            return AlarmSeverity.NO_ALARM, "", None

        for alarm_type, op in cls.LIMIT_CHECKS:
            severity = pvstate[f"valueAlarm.{alarm_type}Severity"]
            if severity and op(value, pvstate[f"valueAlarm.{alarm_type}Limit"]):
                return int(severity), alarm_type, None

        return AlarmSeverity.NO_ALARM, "", None

    @classmethod
    def __clear_alarm(cls, pvstate: Value) -> bool:
        """Clear any alarm this rule raised earlier, reporting whether anything moved.

        Both writes are guarded, because assigning to a p4p ``Value`` marks the field
        changed even when the value is identical. On the array path ``_apply_gather``
        copies the marked fields back onto the array, so an unconditional write would
        re-post the alarm to every monitoring client on every update, whether or not
        the alarm state moved.
        """
        cleared = False
        if pvstate["alarm.severity"] != AlarmSeverity.NO_ALARM:
            logger.debug("\tclearing severity %i", pvstate["alarm.severity"])
            pvstate["alarm.severity"] = AlarmSeverity.NO_ALARM
            cleared = True
        if pvstate["alarm.message"]:
            logger.debug("\tclearing message '%s'", pvstate["alarm.message"])
            pvstate["alarm.message"] = ""
            cleared = True
        return cleared

    @classmethod
    def __set_status(cls, pvstate: Value, status: AlarmStatus | None) -> None:
        """Apply the verdict's status, undoing the rule's own previous status if any.

        ``alarm.status`` otherwise belongs to whatever raised the condition, so the
        rule only ever writes the one status it sets itself.
        """
        if status is not None:
            logger.debug("\tsetting status %s", status.name)
            pvstate["alarm.status"] = status
        elif pvstate["alarm.status"] == AlarmStatus.UNDEFINED_STATUS:
            logger.debug("\tclearing status %s", AlarmStatus.UNDEFINED_STATUS.name)
            pvstate["alarm.status"] = AlarmStatus.NO_STATUS

    def gather_init(self, gathered_value: Value) -> None:
        """Clear the accumulator so each element's verdict can be maximised into it."""
        if self.incoming_severity(gathered_value):
            return

        self.__clear_alarm(gathered_value)
        self.__set_status(gathered_value, None)

    def gather(self, scalar_value: Value, gathered_value: Value) -> None:
        # Strictly greater, so the first element at the winning severity supplies the
        # message -- the same maximisation the class docstring describes. Status
        # travels with the severity it was raised alongside, as base's nsta does.
        if scalar_value["alarm.severity"] > gathered_value["alarm.severity"]:
            gathered_value["alarm.severity"] = scalar_value["alarm.severity"]
            gathered_value["alarm.message"] = scalar_value["alarm.message"]
            gathered_value["alarm.status"] = scalar_value["alarm.status"]
