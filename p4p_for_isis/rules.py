"""
Classes to define rules for handler put and PV post operations.
The RulesFlow and BaseRule classes are interfaces. The classes below those
are implementations of the logic of Normative Type
"""

# TODO: Consider adding Authentication class / callback for puts

from abc import ABC, abstractmethod
import logging
import operator
import time

from enum import Enum, auto
from typing import List, SupportsFloat as Numeric  # Hack to type hint number types

from p4p import Value
from p4p.server import ServerOperation
from p4p.server.thread import SharedPV

from p4p_for_isis.utils import time_in_seconds_and_nanoseconds

logger = logging.getLogger(__name__)


class RulesFlow(Enum):
    """
    Used by the BaseRulesHandler to control whether to continue or stop
    evaluation of rules in the defined sequence. It may also be used to
    set an error message if rule evaluation is aborted.
    """

    CONTINUE = auto()  # Continue rules processing
    TERMINATE = auto()  # Do not process more rules but apply timestamp and complete
    TERMINATE_WO_TIMESTAMP = auto()  # Do not process further rules; do not apply timestamp rule
    ABORT = auto()  # Stop rules processing and abort put

    def __init__(self, _) -> None:
        # We include an error string so that we can indicate why an ABORT
        # has been triggered
        self.error: str = ""

    def set_errormsg(self, errormsg: str):
        """
        Set an error message to explain an ABORT
        This function returns the class instance so it may be used in lambdas
        """
        self.error = errormsg

        return self


class BaseRule(ABC):
    """
    Rules to apply to a PV
    Most rules only require evaluation agains the new PV state, e.g.
    whether to apply a control limit, update a timestamp, trigger an
    alarm etc. But some rules need to compare against the previous
    state of the PV, e.g. slew limits, control.minStep, etc.
    """

    # Two members must be implemented by derived classes:
    # - _name is a human-readable name for the rule used in error and debug messages
    # - _fields is a list of the fields with the PV structure that this rule manages
    #           and at this time is used mainly by readonly rules

    @property
    @abstractmethod
    def _name(self) -> str:
        raise NotImplementedError

    # Often we want to make the fields associated with a rule readonly for put
    # operations, e.g. a put operation should not be able to change the limits
    # of a valueAlarm rule. The combination of listing fields controlled by the
    # rule and having a readonly flag allows this to be automatically handled by
    # this base class's put_rule()
    read_only: bool = False

    @property
    @abstractmethod
    def _fields(self) -> List[str]:
        raise NotImplementedError

    def init_rule(self, newpvstate: Value) -> RulesFlow:
        """
        Rule that only needs to consider the potential future state of a PV.
        Consider if this rule could apply to a newly initialised PV.
        """
        logger.debug("Evaluating %s.init_rule", self._name)

        return RulesFlow.CONTINUE

    def post_rule(self, oldpvstate: Value, newpvstate: Value) -> RulesFlow:
        """
        Rule that needs to consider the current and potential future state of a PV.
        Usually this will involve a post where the oldpvstate is actually the current
        state of the PV, and the newpvstate represents the changes that we would
        like to apply. This rule is often also triggered in a similar manner by a
        put in which case the newpvstate derives from the ServerOperation.
        """
        logger.debug("Evaluating %s.post_rule", self._name)

        return self.init_rule(newpvstate)

    def put_rule(self, pv: SharedPV, op: ServerOperation) -> RulesFlow:
        """
        Rule with access to ServerOperation information, i.e. triggered by a
        handler put. These may perform authentication / authorisation style
        operations
        """
        logger.debug("Evaluating %s.put_rule", self._name)
        oldpvstate: Value = pv.current().raw
        newpvstate: Value = op.value().raw

        if self.read_only:
            # Mark all fields of the newpvstate (i.e. op) as unchanged.
            # This will effectively make the field read-only while allowing
            # subsequent rules to trigger and work as usual
            for field in self._fields:
                newpvstate.mark(field, False)

        return self.post_rule(oldpvstate, newpvstate)


class ReadOnlyRule(BaseRule):
    """A rule which rejects all attempts to put values"""

    _name = "read_only"
    _fields = None

    def put_rule(self, pv: SharedPV, op: ServerOperation) -> RulesFlow:
        return RulesFlow(RulesFlow.ABORT).set_errormsg("read-only")


class AlarmRule(BaseRule):
    """
    This class exists only to allow the alarm field, i.e. severity and
    message to be made read-only for put operations
    """

    _name = "alarm"
    _fields = ["alarm"]


class TimestampRule(BaseRule):
    """Set current timestamp unless provided with an alternative value"""

    _name = "timestamp"
    _fields = ["timestamp"]

    def init_rule(self, newpvstate: Value) -> RulesFlow:
        """Update the timeStamp of a PV"""

        logger.debug("Generating timeStamp from time.time()")
        timestamp = time.time()
        seconds, nanoseconds = time_in_seconds_and_nanoseconds(timestamp)

        newpvstate["timeStamp.secondsPastEpoch"] = seconds
        newpvstate["timeStamp.nanoseconds"] = nanoseconds

        return RulesFlow.CONTINUE


class ControlRule(BaseRule):
    """
    Apply rules implied by Normative Type control field.
    These include a minimum value change (control.minStep) and upper
    and lower limits for values (control.limitHigh and control.limitLow)
    """

    _name = "control"
    _fields = "control"

    def init_rule(self, newpvstate: Value) -> RulesFlow:
        """Check whether a value should be clipped by the control limits

        NOTE: newpvstate from a put is a combination of the old and new state

        Returns None if no change should be made and the value is valid

        TODO: see if this can be separated out into a function like the
        min_step_violated to work better with arrays

        """

        if "control" not in newpvstate:
            logger.debug("control not present in structure")
            return RulesFlow.CONTINUE

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

    def post_rule(self, oldpvstate: Value, newpvstate: Value) -> RulesFlow:
        """Helper function for decoupling rule for easier testing"""

        # Check if there are any controls!
        if "control" not in newpvstate:
            logger.debug("control not present in structure")
            return RulesFlow.CONTINUE

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


class ValueAlarmRule(BaseRule):
    """
    Rule to check whether valueAlarm limits have been triggered, changing
    alarm.severity and alarm.message appropriately.

    TODO: Implement hysteresis
    """

    _name = "valueAlarm"
    _fields = ["valueAlarm"]

    def init_rule(self, newpvstate: Value) -> RulesFlow:
        """Evaluate alarm value limits"""
        # TODO: Apply the rule for hysteresis. Unfortunately I don't understand the
        # explanation in the Normative Types specification...

        logger.debug("Evaluating %s.init_rule", self._name)

        if "valueAlarm" not in newpvstate:
            logger.debug("valueAlarm not present in structure")
            return RulesFlow.CONTINUE

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
