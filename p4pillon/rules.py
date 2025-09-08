"""
Classes to define rules for handler put and PV post operations.
The RulesFlow and BaseRule classes are interfaces. The classes below those
are implementations of the logic of Normative Type
"""

# TODO: Consider adding Authentication class / callback for puts
from __future__ import annotations

import itertools
import logging
import operator
import time
from abc import ABC, abstractmethod
from copy import deepcopy
from enum import IntEnum, auto
from functools import wraps
from typing import Any  # Hack to type hint number types
from typing import SupportsFloat as Numeric

from p4p import Type, Value
from p4p.server import ServerOperation
from p4p.server.raw import ServOpWrap, SharedPV

from p4pillon.definitions import AlarmSeverity
from p4pillon.utils import overwrite_marked, time_in_seconds_and_nanoseconds

logger = logging.getLogger(__name__)


class RulesFlow(IntEnum):
    """
    Used by the BaseRulesHandler to control whether to continue or stop
    evaluation of rules in the defined sequence. It may also be used to
    set an error message if rule evaluation is aborted.
    """

    CONTINUE = auto()  #: Continue rules processing
    TERMINATE = auto()  #: Do not process more rules but apply timestamp and complete
    TERMINATE_WO_TIMESTAMP = auto()  #: Do not process further rules; do not apply timestamp rule
    ABORT = auto()  #: Stop rules processing and abort put

    def __init__(self, _) -> None:
        # We include an error string so that we can indicate why an ABORT
        # has been triggered
        self.error: str = ""

    def set_errormsg(self, errormsg: str) -> RulesFlow:
        """
        Set an error message to explain an ABORT.
        This function returns the class instance so it may be used in lambdas
        """
        self.error = errormsg

        return self


def check_applicable_init(func):
    """
    Decorator for `BaseRule::init_rule`. Checks `is_applicable()`
    and returns RulesFlow.CONTINUE if not True
    """

    @wraps(func)
    def wrapped_function(self: BaseRule, *args, **kwargs):
        if not self.is_applicable(args[0]):
            logger.debug("Rule %s.%s is not applicable", self._name, func.__name__)  # pylint: disable=protected-access
            return RulesFlow.CONTINUE

        return func(self, *args, **kwargs)

    return wrapped_function


def check_applicable_post(func):
    """
    Decorator for `BaseRule::post_rule`. Checks `is_applicable()`
    and returns RulesFlow.CONTINUE if not True
    """

    @wraps(func)
    def wrapped_function(self: BaseRule, currentstate: Value, newpvstate: Value):
        if not self.is_applicable(newpvstate):
            logger.debug("Rule %s.%s is not applicable", self._name, func.__name__)  # pylint: disable=protected-access
            return RulesFlow.CONTINUE

        return func(self, currentstate, newpvstate)

    return wrapped_function


def check_applicable_put(func):
    """
    Decorator for `BaseRule::put_rule`. Checks `is_applicable()`
    and returns RulesFlow.CONTINUE if not True
    """

    @wraps(func)
    def wrapped_function(self: BaseRule, *args, **kwargs):
        if not self.is_applicable(args[1].value().raw):
            logger.debug("Rule %s.%s is not applicable", self._name, func.__name__)  # pylint: disable=protected-access
            return RulesFlow.CONTINUE

        return func(self, *args, **kwargs)

    return wrapped_function


def check_applicable(func):
    """
    Decorator for `BaseRule::*_rule`. Checks `is_applicable()`
    and returns RulesFlow.CONTINUE if not True
    """

    @wraps(func)
    def wrapped_function(self: BaseRule, *args, **kwargs):
        # Determine whether we're being applied to either:
        # - init_rule (1 argument)
        # - post_rule (2 arguments, second argument is a Value)
        # - put_rule (2 arguments, second argument is a ServerOperation)
        if len(args) == 1:
            newpvstate = args[0]
        elif len(args) == 2:
            if isinstance(args[1], Value):
                newpvstate = args[1]
            elif isinstance(args[1], ServOpWrap):
                newpvstate = args[1].value().raw
            else:
                raise TypeError("Type of second argument must be either Value or ServerOperation, is", type(args[1]))

        else:
            raise TypeError(f"Expected 1 or 2 arguments, received {len(args)}")

        # Then check if applicable and if not return a CONTINUE to short-circuit this rule
        if not self.is_applicable(newpvstate):
            logger.debug("Rule %s.%s is not applicable", self._name, func.__name__)  # pylint: disable=protected-access
            return RulesFlow.CONTINUE

        # Actually wrap the function we're decorating!
        return func(self, *args, **kwargs)

    return wrapped_function


class BaseRule(ABC):
    """
    Rules to apply to a PV.
    Most rules only require evaluation against the new PV state, e.g. whether to apply a control
    limit, update a timestamp, trigger an alarm etc. This may be done by the `init_rule()`.
    Other rules need to compare against the previous state of the PV, e.g. slew limits,
    control.minStep, etc. This may be done by the `post_rule()`. And some rules need to know
    who is making the request (for authorisation purposes). The may be done by the `put_rule()`
    """

    # Two members must be implemented by derived classes:
    # - _name is a human-readable name for the rule used in error and debug messages
    # - _fields is a list of the fields within the PV structure that this rule manages
    #           and at this time is used mainly by readonly rules

    @property
    @abstractmethod
    def _name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def _fields(self) -> list[str]:
        raise NotImplementedError

    # Often we want to make the fields associated with a rule readonly for put
    # operations, e.g. a put operation should not be able to change the limits
    # of a valueAlarm rule. The combination of listing fields controlled by the
    # rule and having a readonly flag allows this to be automatically handled by
    # this base class's put_rule()
    read_only: bool = False

    # TODO: Consider using lru_cache but be aware of https://rednafi.com/python/lru_cache_on_methods/
    def is_applicable(self, newpvstate: Value) -> bool:
        """Test whether the Rule should be applied."""

        # _fields is None indicates the rule always applies
        if self._fields is None:
            return True

        # Next check that all the fields required are present
        if not set(self._fields).issubset(newpvstate.keys()):
            return False

        # Then check if any of the fields required are changed
        # If they aren't changed then the rule shouldn't have anything to do!
        test_fields = deepcopy(self._fields)
        if "value" not in test_fields:
            test_fields.append("value")

        if not any(newpvstate.changed(x) for x in test_fields):
            return False

        return True

    @check_applicable_init
    def init_rule(self, newpvstate: Value) -> RulesFlow:  # pylint: disable=unused-argument
        """
        Rule that only needs to consider the potential future state of a PV.
        Consider implementing if this rule could apply to a newly initialised PV.
        """
        logger.debug("Evaluating %s.init_rule", self._name)

        return RulesFlow.CONTINUE

    @check_applicable_post
    def post_rule(self, oldpvstate: Value, newpvstate: Value) -> RulesFlow:  # pylint: disable=unused-argument
        """
        Rule that needs to consider the current and potential future state of a PV.
        Usually this will involve a post where the oldpvstate is actually the current
        state of the PV, and the newpvstate represents the changes that we would
        like to apply. This rule is often also triggered in a similar manner by a
        put in which case the newpvstate derives from the ServerOperation.
        """
        logger.debug("Evaluating %s.post_rule", self._name)

        return self.init_rule(newpvstate)

    @check_applicable_put
    def put_rule(self, pv: SharedPV, op: ServerOperation) -> RulesFlow:
        """
        Rule with access to ServerOperation information, i.e. triggered by a
        handler put. These may perform authentication / authorisation style
        operations
        """

        # oldpvstate: Value = pv.current().raw
        newpvstate: Value = op.value().raw

        logger.debug("Evaluating %s.put_rule", self._name)

        if self.read_only:
            # Mark all fields of the newpvstate (i.e. op) as unchanged.
            # This will effectively make the field read-only while allowing
            # subsequent rules to trigger and work as usual
            for field in self._fields:
                # We need to rollback the changes by making the fields that shouldn't
                # be changed equal their oldstate and marking them as unchanged.
                # The first step stops issues with evaluating rules against the newstate.
                # The second step prevents changes being made.
                for changed_field in newpvstate.changedSet():
                    if changed_field.startswith(field):
                        newpvstate[changed_field] = pv.current().raw[changed_field]
                        newpvstate.mark(changed_field, False)

        return RulesFlow.CONTINUE
        # return self.post_rule(oldpvstate, newpvstate)


class BaseScalarRule(BaseRule, ABC):
    """
    Rule to be applied to NTScalarArrays
    """


class BaseGatherableRule(BaseScalarRule, ABC):
    """
    A rule usually applicable to NTScalars must be made Gatherable if when run sequentially on an
    array the correct output of a Rule must be determined by both the current Value and the
    previous value
    """

    def gather_init(self, gathered_value: Value) -> None:
        """A gather may be optionally initialised."""

    @abstractmethod
    def gather(self, scalar_value: Value, gathered_value: Value) -> None:
        """
        Gather information from multiple individual applications of a Rule
        across the elements of a NTScalarArray.
        """


class BaseArrayRule(BaseRule, ABC):
    """
    Rule to be applied to NTScalarArrays
    """


class ReadOnlyRule(BaseScalarRule):
    """A rule which rejects all attempts to put values"""

    @property
    def _name(self) -> str:
        return "read_only"

    @property
    def _fields(self) -> list[str]:
        return []

    def put_rule(self, pv: SharedPV, op: ServerOperation) -> RulesFlow:
        return RulesFlow(RulesFlow.ABORT).set_errormsg("read-only")


class AlarmRule(BaseRule):
    """
    This class exists only to allow the alarm field, i.e. severity and
    message to be made read-only for put operations
    """

    @property
    def _name(self) -> str:
        return "alarm"

    @property
    def _fields(self) -> list[str]:
        return ["alarm"]


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


class ScalarToArrayWrapperRule(BaseArrayRule):
    """
    Wrap a rule designed to be applied to an NTScalar so that it works with
    NTScalarArrays.
    """

    @property
    def _name(self) -> str:
        return self._wrap_name

    @property
    def _fields(self) -> list[str]:
        return self._wrap_fields

    def __init__(self, to_wrap: BaseScalarRule | BaseGatherableRule) -> None:
        super().__init__()

        self._wrapped = to_wrap

        self._wrap_name = to_wrap._name
        self._wrap_fields = to_wrap._fields

    def _get_value_id(self, arrayval: Value) -> str:
        return arrayval.type().aspy()[1]  # id of the structure, probably "epics:nt/NTScalarArray:1.0"

    def _change_array_type_to_scalar_type(self, arrayval: Value) -> list:
        """
        Return the id and type of an NTScalarArray Value, changing the type of the
        value field to be a scalar.
        """

        # The type of the scalar is essentially the same as the array with
        # the value type modified. Extracting the type info of the input value
        # and then making a change to it is surprisingly complicated!
        val_aspy = arrayval.type().aspy()
        val_type = dict(val_aspy[2])  # extract the actual structure recipe
        val_type["value"] = val_type["value"][1:]  # change the value type to a scalar
        val_type = list(val_type.items())  # back to a list

        return val_type

    def _value_without_value(self, arrayval: Value, index: int | None = None) -> dict[str, Any]:
        # It would be straightforward to use arrayval.todict() but the value
        # could potentially be very large. So we use a more indirect way of
        # constructing it by iterating through the keys
        val_keys: list = arrayval.keys()
        val_keys.remove("value")

        val_dict = {}
        for val_key in val_keys:
            val_dict[val_key] = arrayval.todict(val_key)

        # We don't always have a value if changes are being made to other parts of
        # the structure, e.g. control limits

        if index and "value" in arrayval and len(arrayval["value"]) >= index:
            val_dict["value"] = arrayval["value"][index]
        else:
            # TODO: Default value isn't 0 for strings!
            # val_dict["value"] = 0
            pass

        return val_dict

    def scalarise(self, arrayval: Value, index: int | None = None) -> Value:
        """
        Convert the NTScalarArray into an NTScalar with the value of the
        index element in the array. If no index is provided a default value
        will be set.
        """

        # Constuct the new scalar value. This will have everything marked as changed
        val_id = self._get_value_id(arrayval)
        val_type = self._change_array_type_to_scalar_type(arrayval)
        val_dict = self._value_without_value(arrayval, index)
        value = Value(Type(val_type, id=val_id), val_dict)

        # Fix the changedSet so it matches that of the array passed in
        value.unmark()
        changed_set = arrayval.changedSet()
        for changed in changed_set:
            value.mark(changed)

        return value

    def _apply_gather(self, array_value: Value, scalar_value):
        if all(x in array_value.keys() for x in self._fields):
            overwrite_marked(array_value, scalar_value, self._fields)

    @check_applicable_init
    def init_rule(self, newpvstate: Value) -> RulesFlow:
        # Convert the new Value into scalar versions
        scalared_new_state = self.scalarise(newpvstate)

        gathered_value = self.scalarise(newpvstate)
        if isinstance(self._wrapped, BaseGatherableRule):
            self._wrapped.gather_init(gathered_value)

        # Loop through the array values applying the rules to each individual value
        newvals = []  # Use Ajit's trick to bypass the readonly value
        net_rule_flow = RulesFlow.CONTINUE
        for new_value in newpvstate["value"]:
            scalared_new_state["value"] = new_value

            rule_flow = self._wrapped.init_rule(scalared_new_state)
            if rule_flow == RulesFlow.ABORT:
                return RulesFlow.ABORT

            if rule_flow > net_rule_flow:  # Set the overall state to the worst we have encountered!
                net_rule_flow = rule_flow

            if isinstance(self._wrapped, BaseGatherableRule):
                self._wrapped.gather(scalared_new_state, gathered_value)

            newvals.append(scalared_new_state["value"])

        # Apply what was gathered
        newpvstate["value"] = newvals
        self._apply_gather(newpvstate, gathered_value)

        return net_rule_flow

    # NOTE: Performance will be terrible! Every rule and every value has to be iterated every time!
    # TODO: What's the correct behaviour if the new and old PV states have different lengths?
    # TODO: What is the correct behaviour for a Control Rule if the array size increases?
    # TODO: What if the Value["value"] has not changed?
    @check_applicable_post
    def post_rule(self, oldpvstate: Value, newpvstate: Value) -> RulesFlow:
        # Convert the current Value and new Value into scalar versions
        scalared_current_state = self.scalarise(oldpvstate)
        scalared_new_state = self.scalarise(newpvstate)

        gathered_value = self.scalarise(newpvstate)
        if isinstance(self._wrapped, BaseGatherableRule):
            self._wrapped.gather_init(gathered_value)

        # Loop through the array values applying the rules to each individual value
        newvals = []  # Use Ajit's trick to bypass the readonly value
        net_rule_flow = RulesFlow.CONTINUE
        for old_value, new_value in itertools.zip_longest(oldpvstate["value"], newpvstate["value"]):
            if old_value is not None:
                scalared_current_state["value"] = old_value
            else:
                scalared_current_state = None

            scalared_new_state["value"] = new_value

            rule_flow = self._wrapped.post_rule(scalared_current_state, scalared_new_state)

            if rule_flow == RulesFlow.ABORT:
                return RulesFlow.ABORT
            if rule_flow > net_rule_flow:  # Set the overall state to the worst we have encountered!
                net_rule_flow = rule_flow

            if isinstance(self._wrapped, BaseGatherableRule):
                self._wrapped.gather(scalared_new_state, gathered_value)

            newvals.append(scalared_new_state["value"])

        # Apply what was gathered
        newpvstate["value"] = newvals
        self._apply_gather(newpvstate, gathered_value)

        return net_rule_flow
