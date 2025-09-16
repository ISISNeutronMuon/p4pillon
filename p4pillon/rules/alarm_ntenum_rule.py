"""
This rule is not part of the Normative Type specification. It provides an interface for
 alarms for NTEnums.
"""

from p4p import Value

from p4pillon.definitions import AlarmDict, AlarmSeverity, AlarmStatus
from p4pillon.rules.rules import RulesFlow, check_applicable_init

from .alarm_rule import AlarmRule


class AlarmNTEnumRule(AlarmRule):
    """
    Uses a dictionary to map NTEnum values to severity, status, and message.
    """

    def __init__(self, alarms: dict[str, AlarmDict] | None = None):
        super().__init__()

        if alarms:
            self.alarms = alarms
        else:
            self.alarms: dict[str, AlarmDict] = {}

        self.default_severity = AlarmSeverity.UNDEFINED_ALARM
        self.default_status = AlarmStatus.NO_STATUS
        self.default_message = "No alarm message set."

    @check_applicable_init
    def init_rule(self, newpvstate: Value) -> RulesFlow:
        alarm_choice = newpvstate["value.choices"][newpvstate["value.index"]]

        alarm = self.alarms.get(alarm_choice, None)
        if alarm:
            newpvstate["alarm.severity"] = alarm.get("severity", self.default_severity)
            newpvstate["alarm.status"] = alarm.get("status", self.default_severity)
            newpvstate["alarm.message"] = alarm.get("message", self.default_message)
        else:
            newpvstate["alarm.severity"] = AlarmSeverity.NO_ALARM
            newpvstate["alarm.status"] = AlarmStatus.NO_STATUS
            newpvstate["alarm.message"] = ""

        return RulesFlow.CONTINUE
