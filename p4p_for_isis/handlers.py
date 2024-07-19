""" Handler for NTScalar (so far) """
from __future__ import annotations # for older version of Python

import logging
import operator
import time

from collections import OrderedDict
from enum import Enum, auto
from typing import SupportsFloat as Numeric  # Hack to type hint number types
from typing import Callable

from p4p import Value
from p4p.server import ServerOperation
from p4p.server.thread import Handler, SharedPV

from p4p_for_isis.utils import time_in_seconds_and_nanoseconds


logger = logging.getLogger(__name__)

class RulesFlow(Enum):
    """ 
    Used by the BaseRulesHandler to control continuing or stopping
    evaluation of rules in the defined sequence.
    """

    CONTINUE  = auto()  # Continue rules processing
    TERMINATE = auto()  # Do not process more rules but apply timestamp and complete
    TERMINATE_WO_TIMESTAMP = auto() # Do not process further rules; do not apply timestamp rule
    ABORT     = auto()  # Stop rules processing and abort put

    def __init__(self, value) -> None:
        super().__init__(value)

        # We include an error string so that we can indicate why an ABORT
        # has been triggered
        self.error : str = None

    def set_errormsg(self, errormsg : str) -> RulesFlow:
        """ 
        Set an error message to explain an ABORT
        This function returns the class instance so it may be used in lambdas
        """
        self.error = errormsg

        return self

class BaseRulesHandler(Handler):
    """
    Base class for use as a handler which appplies named rules in a defined order.
    """

    # The BaseRulesHandler uses two OrderedDicts of functions to evaluate
    # handler rules. The BaseRulesHandler only includes built-in rules to
    # handle read only PVs and to apply timeStamps. Subclasses implement
    # rules to handle the standard fields of Normative Types. This base
    # class is already able to handle modifications of its existing rules
    # and addition of custom user generated rules (though it is expected
    # that users will anyway use the provided derived classes in most cases).
    #
    # There are two types of rule applied by the BaseRulesHandler, but these
    # two kinds of rules are usually interconnected as we'll see.
    #
    ### MERGING
    # But first we need to address an issue which complicates handler logic.
    # Imagine a PV which has a value and a control field:
    #    'example:pv': {
    #       'value': 3,
    #       'control': {
    #           'limitLow' : -1,
    #           'limitHigh' : 10,
    #           'minStep' : 1
    #       }
    #    }
    #
    # In the case of a put of '{value: 11}' the value will become 10.
    # In the case of a put of '{limitHigh: 2}' the value will become 2 and the
    # limitHigh will become 2. Note that in this case the value will change
    # even though the put operation did not directly change it.
    # In the case of a put of '{value: -3, limitLow: -5}' the value will
    # become -3 and the limitLow will become -5. But the *order of evaluation
    # now matters*. We need to evaluate the value against the new limitLow and
    # not the old one.
    #
    # In general we must merge the old and new state of a field such as control
    # during a put and only then can the handler correctly evaluate the results.
    #
    ### RULES
    # As noted the BaseRulesHandler maintains two different OrderedDict queues
    # of named rules (i.e. functions). Note that the call signatures of these
    # two types of rules are different.
    #
    # The first kind of rules is an init rule which is directly called when the
    # handler's onFirstCall is called, i.e. the first time the state of the PV
    # must be resolved, usually prompted by a first get/put/monitor. The PV has
    # only its initial state and no prior state
    # The init rules have function signature of
    #    evaluate_field(self, combinedvals, pvstate : Value) -> None | Value:
    # where combinedvals is a merger of the previous state of the PV and the
    # new state of the PV for the relevant field(s).
    #
    ### SPECIAL RULES
    # The two rules automatically included by BaseRulesHandler are given special
    # treatment during rules evaluation. The rule 'read_only' is always evaluated
    # first. The rule 'timestamp' is always evaluated last. These are included
    # as otherwise ordinary rules so that they may be replaced if desired.
    #

    def __init__(self) -> None:
        super().__init__()
        self._name = None   # Used purely for logging

        self._init_rules : OrderedDict[
            Callable[[dict, Value], Value]
        ] = OrderedDict()

        self._init_rules["timestamp"] = self.evaluate_timestamp

        self._put_rules : OrderedDict[
            Callable[[SharedPV, ServerOperation], RulesFlow]
        ] = OrderedDict()

        self._put_rules["timestamp"] = self._timestamp_rule

    def _post_init(self, pv : SharedPV) -> None:
        """
        This method is called by the pvrecipe after the pv has been created
        """
        # Evaluate the timestamp last
        self._init_rules.move_to_end("timestamp")

        for post_init_rule_name, post_init_rule in self._init_rules.items():
            logger.debug('Processing post init rule %s', post_init_rule_name)
            value = post_init_rule(pv.current().raw, pv.current().raw)
            if value:
                pv.post(value=value)

    def put(self, pv: SharedPV, op: ServerOperation) -> None:
        """Put that applies a set of rules"""
        self._name = op.name()
        logger.debug("Processing attempt to change PV %s by %s (member of %s) at %s",
                     op.name(), op.account(), op.roles(), op.peer())

        # oldpvstate : Value = pv.current().raw
        newpvstate: Value = op.value().raw

        logger.debug(
            "Processing changes to the following fields: %r (value = %s)",
            newpvstate.changedSet(),
            newpvstate["value"],
        )

        if not self._apply_rules(pv, op):
            return

        logger.info(
            "Making the following changes to %s: %r",
            self._name,
            newpvstate.changedSet(),
        )
        pv.post(op.value())  # just store and update subscribers

        op.done()
        logger.info("Processed change to PV %s by %s (member of %s) at %s",
                    op.name(), op.account(), op.roles(), op.peer())

    def _apply_rules(self, pv: SharedPV, op: ServerOperation) -> bool:
        """
        Apply the rules, usually when a put operation is attempted
        """
        for rule_name, put_rule in self._put_rules.items():
            logger.debug('Applying rule %s', rule_name)
            rule_flow = put_rule(pv, op)

            # Originally a more elegant match (rule_flow): but we need
            # to support versions of Python prior to 3.10
            if not rule_flow:
                logger.warning(
                        "Rule %s did not return rule flow. Defaulting to "
                        "CONTINUE, but this behaviour may change in "
                        "future.",
                        rule_name,
                )
            elif rule_flow == RulesFlow.CONTINUE:
                pass
            elif rule_flow == RulesFlow.ABORT:
                logger.debug("Rule %s triggered handler abort", rule_name)

                errormsg = None
                if rule_flow.error:
                    errormsg = rule_flow.error

                op.done(error=errormsg)
                return False
            elif rule_flow == RulesFlow.TERMINATE:
                logger.debug("Rule %s triggered handler terminate", rule_name)
                self._put_rules['timestamp'](pv, op)
                break
            elif rule_flow == RulesFlow.TERMINATE_WO_TIMESTAMP:
                logger.debug("Rule %s triggered handler terminate without timestamp", rule_name)
                break
            else:
                logger.critical("Rule %s returned unhandled return type", rule_name)
                raise TypeError(
                    f"Rule {rule_name} returned unhandled return type {type(rule_flow)}"
                )

        return True

    def set_read_only(self, onoff : bool = True):
        """
        Make this PV read only.
        """
        if onoff:
            # Switch on the read-only rule and make sure it's the first rule
            self._put_rules["read_only"] = \
                lambda new, old: RulesFlow(RulesFlow.ABORT).set_errormsg("read only PV")
            self._put_rules.move_to_end("read_only", last=False)
        else:
            # Switch off the read-only rule by deleting it
            self._put_rules.pop("read_only", None)

    def _timestamp_rule(self, _, op: ServerOperation) -> RulesFlow:
        """Handle updating the timestamps"""

        # Note that timestamps are not automatically handled so we may need to set them ourselves
        newpvstate: Value = op.value().raw
        self.evaluate_timestamp(_, newpvstate)

        return RulesFlow.CONTINUE

    def evaluate_timestamp(self, _ : dict, newpvstate : Value) -> Value:
        """ Update the timeStamp of a PV """
        if newpvstate.changed("timeStamp"):
            logger.debug("Using timeStamp from put operation")
        else:
            logger.debug("Generating timeStamp from time.time()")
            sec, nsec = time_in_seconds_and_nanoseconds(time.time())
            newpvstate["timeStamp.secondsPastEpoch"] = sec
            newpvstate["timeStamp.nanoseconds"] = nsec

        return newpvstate

class NTScalarRulesHandler(BaseRulesHandler):
    """
    Rules handler for NTScalar PVs.
    """
    def __init__(self) -> None:
        super().__init__()

        self._init_rules.update({
            'control' : self.evaluate_control_limits,
            'alarm_limit' : self.evaluate_alarm_limits
        })

        self._put_rules["control"] = self._controls_rule
        self._put_rules["alarm_limit"] = self._alarm_limit_rule
        self._put_rules.move_to_end("timestamp")

    def _controls_rule(self, pv: SharedPV, op: ServerOperation) -> RulesFlow:
        """Check whether control limits should trigger and restrict values appropriately"""
        logger.debug("Evaluating control limits")

        oldpvstate: Value = pv.current().raw
        newpvstate: Value = op.value().raw

        # Check if there are any controls!
        if "control" not in newpvstate and "control" not in oldpvstate:
            logger.debug("control not present in structure")
            return RulesFlow.CONTINUE

        combinedvals = self._combined_pvstates(oldpvstate, newpvstate, "control")

        # Check minimum step first
        if (
            abs(newpvstate["value"] - oldpvstate["value"])
            < combinedvals["control.minStep"]
        ):
            logger.debug("<minStep")
            newpvstate["value"] = oldpvstate["value"]
            return RulesFlow.CONTINUE

        value = self.evaluate_control_limits(combinedvals, None)
        if value:
            newpvstate["value"] = value

        return RulesFlow.CONTINUE

    def evaluate_control_limits(self, combinedvals : dict, _) -> None | int | Numeric:
        """ Check whether a value should be clipped by the control limits """

        if not 'control' in combinedvals:
            logger.debug("control not present in structure")
            return None

        # A philosophical question! What should we do when lowLimit = highLimit = 0?
        # This almost certainly means the structure hasn't been initialised, but it could
        # be an attempt (for some reason) to lock the value to 0. For now we treat this
        # as uninitialised and ignore limits in this case. Users will have to handle
        # keeping the PV constant at 0 themselves
        if (
            combinedvals["control.limitLow"] == 0
            and combinedvals["control.limitHigh"] == 0
        ):
            logger.info(
                "control.limitLow and control.LimitHigh set to 0, so ignoring control limits"
            )
            return None

        # Check lower and upper control limits
        if combinedvals["value"] < combinedvals["control.limitLow"]:
            value = combinedvals["control.limitLow"]
            logger.debug("Lower control limit exceeded, changing value to %s", value)
            return value

        if combinedvals["value"] > combinedvals["control.limitHigh"]:
            value = combinedvals["control.limitHigh"]
            logger.debug("Upper control limit exceeded, changing value to %s", value)
            return value

        return None

    def __alarm_state_check(
        self, combinedvals: dict, newpvstate: Value, alarm_type: str, op=None
    ) -> bool:
        """Check whether"""
        if not op:
            if alarm_type.startswith("low"):
                op = operator.le
            elif alarm_type.startswith("high"):
                op = operator.ge
            else:
                raise SyntaxError(
                    f"CheckAlarms/alarmStateCheck: do not know how to handle {alarm_type}"
                )

        severity = combinedvals[f"valueAlarm.{alarm_type}Severity"]
        if (
            op(combinedvals["value"], combinedvals[f"valueAlarm.{alarm_type}Limit"])
            and severity
        ):
            newpvstate["alarm.severity"] = severity
            if not newpvstate.changed("alarm.message"):
                newpvstate["alarm.message"] = alarm_type

            logger.info(
                "Setting %s to severity %i with message '%s'",
                self._name, severity, newpvstate['alarm.message']
            )

            return True

        return False

    def _alarm_limit_rule(self, pv: SharedPV, op: ServerOperation) -> BaseRulesHandler.RulesFlow:
        """ Evaluate alarm limits to see if we should change severity or message"""
        oldpvstate: Value = pv.current().raw
        newpvstate: Value = op.value().raw

        # Check if there are any value alarms!
        if "valueAlarm" not in newpvstate and "valueAlarm" not in oldpvstate:
            logger.debug("valueAlarm not present in structure")
            return RulesFlow.CONTINUE

        combinedvals = self._combined_pvstates(oldpvstate, newpvstate, ["valueAlarm", "alarm"])

        self.evaluate_alarm_limits(combinedvals, newpvstate)
        return self.RulesFlow.CONTINUE

    def evaluate_alarm_limits(self, combinedvals, pvstate : Value) -> None | Value:
        """ Evaluate alarm value limits """
        if 'valueAlarm' not in combinedvals:
            logger.debug("valueAlarm not present in structure")
            return None

        # Check if valueAlarms are present and active!
        if not combinedvals["valueAlarm.active"]:
            logger.debug("\tvalueAlarm not active")
            return None

        logger.debug("Processing valueAlarm for %s", self._name)

        try:
            # The order of these tests is defined in the Normative Types document
            if self.__alarm_state_check(combinedvals, pvstate, "highAlarm"):
                return pvstate
            if self.__alarm_state_check(combinedvals, pvstate, "lowAlarm"):
                return pvstate
            if self.__alarm_state_check(combinedvals, pvstate, "highWarning"):
                return pvstate
            if self.__alarm_state_check(combinedvals, pvstate, "lowWarning"):
                return pvstate
        except SyntaxError:
            # TODO: Need more specific error than SyntaxError
            return None

        # If we made it here then there are no alarms or warnings and we need to indicate that
        # possibly by resetting any existing ones
        #combinedvals = self._combined_pvstates(oldpvstate, newpvstate, "alarm")
        alarms_changed = False
        if combinedvals["alarm.severity"]:
            pvstate["alarm.severity"] = 0
            alarms_changed = True
        if combinedvals["alarm.message"]:
            pvstate["alarm.message"] = ""
            alarms_changed = True

        if alarms_changed:
            logger.info(
                "Setting %s to severity %i with message '%s'",
                self._name, pvstate['alarm.severity'], pvstate['alarm.message']
            )
            return pvstate

        logger.debug("Made no automatic changes to alarm state of %s", self._name)
        return None

    def _combined_pvstates(
        self, oldpvstate: Value, newpvstate: Value, interests: str | list[str]
    ) -> dict:
        # This is complicated! We may need to process alarms based on either
        # the oldstate or the newstate of the PV. Suppose, for example, the
        # valueAlarm limits have all been set in the PV but it is not yet active.
        # Now a value change and valueAlarms.active=True comes in. We have to
        # act on the new value of the PV (and its active state) but using the
        # old values for the limits!
        # NOTE: We can get away without deepcopies because we never change any
        #       of these values
        # TODO: What if valueAlarm has been added or removed?

        def extract_combined_value(newpvstate, oldpvstate, key):
            """Check a key. If it isn't marked as changed return the old PV state value,
            and if it is marked as changed then return the new PV state value instead
            """
            if newpvstate.changed(key):
                return newpvstate[key]

            return oldpvstate[key]

        combinedvals = {}
        combinedvals["value"] = extract_combined_value(newpvstate, oldpvstate, "value")

        if isinstance(interests, str):
            interests = [interests]

        for interest in interests:
            combinedvals[interest] =  extract_combined_value(
                    newpvstate, oldpvstate, interest
                )
            for key in newpvstate[interest]:
                fullkey = f"{interest}.{key}"
                combinedvals[fullkey] = extract_combined_value(
                    newpvstate, oldpvstate, fullkey
                )

        return combinedvals

class NTScalarArrayRulesHandler(BaseRulesHandler):
    """
    Rules handler for NTScalarArray PVs.
    """
    def __init__(self) -> None:
        super().__init__()
        self.is_array = True

class NTEnumRulesHandler(BaseRulesHandler):
    """
    Rules handler for NTScalarArray PVs.
    """
    def __init__(self) -> None:
        super().__init__()
