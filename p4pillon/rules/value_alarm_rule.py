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
    cycles. This rule follows base: see :meth:`contributed_severity`.

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

        severity, message, status = self.__verdict(newpvstate)
        contributed = self.contributed_severity(newpvstate)

        # As in base: the highest severity contributed this cycle wins, and on a tie
        # the earlier contributor keeps its message. Whatever supplied the value got
        # there first, so its alarm survives a limit verdict of equal severity.
        if contributed and contributed >= severity:
            logger.debug("\tupdate supplied severity %i; leaving the alarm alone", contributed)
            return RulesFlow.CONTINUE

        self.__set_status(newpvstate, status)

        if severity:
            newpvstate["alarm.severity"] = severity
            newpvstate["alarm.message"] = message
            logger.debug("Setting to severity %i with message '%s'", severity, message)
            return RulesFlow.CONTINUE

        # If we made it here then there are no alarms or warnings and we need to indicate that
        # possibly by resetting any existing ones
        alarms_changed = False
        if newpvstate["alarm.severity"]:
            newpvstate["alarm.severity"] = 0
            alarms_changed = True
        if newpvstate["alarm.message"]:
            newpvstate["alarm.message"] = ""
            alarms_changed = True

        if alarms_changed:
            logger.debug(
                "Setting to severity %i with message '%s'",
                newpvstate["alarm.severity"],
                newpvstate["alarm.message"],
            )
        else:
            logger.debug("Made no automatic changes to alarm state.")

        return RulesFlow.CONTINUE

    @staticmethod
    def contributed_severity(pvstate: Value) -> int:
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
    def __verdict(cls, pvstate: Value) -> tuple[int, str, AlarmStatus | None]:
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
    def __set_status(cls, pvstate: Value, status: AlarmStatus | None) -> None:
        """Apply the verdict's status, undoing the rule's own previous status if any.

        ``alarm.status`` otherwise belongs to whatever raised the condition, so the
        rule only ever writes the one status it sets itself.
        """
        if status is not None:
            pvstate["alarm.status"] = status
        elif pvstate["alarm.status"] == AlarmStatus.UNDEFINED_STATUS:
            pvstate["alarm.status"] = AlarmStatus.NO_STATUS

    def gather_init(self, gathered_value: Value) -> None:
        if not self.contributed_severity(gathered_value):
            gathered_value["alarm.severity"] = AlarmSeverity.NO_ALARM
            gathered_value["alarm.message"] = ""
            self.__set_status(gathered_value, None)

    def gather(self, scalar_value: Value, gathered_value: Value) -> None:
        # Strictly greater, so the first element at the winning severity supplies the
        # message -- base's rule (recGblSetSevrVMsg writes only when nsev < new_sevr).
        # Status travels with the severity it was raised alongside, as base's nsta does.
        if scalar_value["alarm.severity"] > gathered_value["alarm.severity"]:
            gathered_value["alarm.severity"] = scalar_value["alarm.severity"]
            gathered_value["alarm.message"] = scalar_value["alarm.message"]
            gathered_value["alarm.status"] = scalar_value["alarm.status"]
