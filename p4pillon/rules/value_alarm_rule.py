"""
Rules for the valueAlarm fields of NTScalar and NTScalarArray Normative Types.
"""

import logging
import operator

from p4p import Value

from p4pillon.definitions import AlarmSeverity

from .rules import BaseGatherableRule, RulesFlow, check_applicable_init

logger = logging.getLogger(__name__)


class ValueAlarmRule(BaseGatherableRule):
    """
    Rule to check whether valueAlarm limits have been triggered, changing
    alarm.severity and alarm.message appropriately.

    TODO: Implement hysteresis
    """

    @property
    def _name(self) -> str:
        return "valueAlarm"

    @property
    def _fields(self) -> list[str]:
        return ["alarm", "valueAlarm"]

    @check_applicable_init
    def init_rule(self, newpvstate: Value) -> RulesFlow:
        """Evaluate alarm value limits"""
        # TODO: Apply the rule for hysteresis. Unfortunately I don't understand the
        # explanation in the Normative Types specification...
        logger.debug("Evaluating %s.init_rule", self._name)

        # Check if valueAlarms are present and active!
        if not newpvstate["valueAlarm.active"]:
            # TODO: This is wrong! If valueAlarm was active and then made inactive
            #       the alarm will not be cleared
            logger.debug("\tvalueAlarm not active")
            return RulesFlow.CONTINUE

        try:
            # The order of these tests is defined in the Normative Types document
            if self.__alarm_state_check(newpvstate, "highAlarm"):
                return RulesFlow.CONTINUE
            if self.__alarm_state_check(newpvstate, "lowAlarm"):
                return RulesFlow.CONTINUE
            if self.__alarm_state_check(newpvstate, "highWarning"):
                return RulesFlow.CONTINUE
            if self.__alarm_state_check(newpvstate, "lowWarning"):
                return RulesFlow.CONTINUE
        except SyntaxError:
            # TODO: Need more specific error than SyntaxError and to decide
            # if continue is the correct behaviour
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

    @classmethod
    def __alarm_state_check(cls, pvstate: Value, alarm_type: str, op=None) -> bool:
        """Check whether the PV should be in an alarm state"""
        if not op:
            if alarm_type.startswith("low"):
                op = operator.le
            elif alarm_type.startswith("high"):
                op = operator.ge
            else:
                raise SyntaxError(f"CheckAlarms/alarmStateCheck: do not know how to handle {alarm_type}")

        severity = pvstate[f"valueAlarm.{alarm_type}Severity"]
        if op(pvstate["value"], pvstate[f"valueAlarm.{alarm_type}Limit"]) and severity:
            pvstate["alarm.severity"] = severity

            # TODO: Understand this commented out code!
            #       I think it's to handle the case of an INVALID alarm or manually
            #       set alarm message?
            # if not pvstate.changed("alarm.message"):
            #     pvstate["alarm.message"] = alarm_type
            pvstate["alarm.message"] = alarm_type

            logger.debug(
                "Setting to severity %i with message '%s'",
                severity,
                pvstate["alarm.message"],
            )

            return True

        return False

    def gather_init(self, gathered_value: Value) -> None:
        if (
            not gathered_value.changed("alarm.severity")
            or gathered_value["alarm.severity"] != AlarmSeverity.INVALID_ALARM
        ):
            gathered_value["alarm.severity"] = AlarmSeverity.NO_ALARM
            gathered_value["alarm.message"] = ""

    def gather(self, scalar_value: Value, gathered_value: Value) -> None:
        if scalar_value["alarm.severity"] > gathered_value["alarm.severity"]:
            gathered_value["alarm.severity"] = scalar_value["alarm.severity"]
            gathered_value["alarm.message"] = scalar_value["alarm.message"]
