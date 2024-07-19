""" Handler for NTScalar (so far) """

import logging
import operator
import time

from collections import OrderedDict
from enum import Enum
from typing import SupportsFloat as Numeric  # Hack to type hint number types
from typing import Callable

from p4p import Value
from p4p.server import ServerOperation
from p4p.server.thread import Handler, SharedPV

from p4p_for_isis.utils import time_in_seconds_and_nanoseconds


logger = logging.getLogger(__name__)

class BaseRulesHandler(Handler):
    """
    Base class for rules that includes rules common to all PV types.
    """
    class RulesFlow(Enum):
        """What to do after a rule has been evaluated"""

        CONTINUE = 1  # Continue rules processing
        TERMINATE = 2  # Do not process more rules but we're good to here
        ABORT = 3  # Stop rules processing and abort put

    def __init__(self) -> None:
        super().__init__()
        self._name = None

        self._init_rules = OrderedDict[
            Callable[[dict, Value], Value]
        ]()

        self._init_rules["timestamp"] = self.evaluate_timestamp

        self._put_rules = OrderedDict[
            Callable[[SharedPV, ServerOperation], self.RulesFlow]
        ]()

        self._put_rules["timestamp"] = self._timestamp_rule

    def _rules_init(self, pv : SharedPV) -> None:
        """
        This method is called by the pvrecipe after the pv has been created
        """
        #Evaluate the timestamp last
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

            match (rule_flow):
                case self.RulesFlow.CONTINUE:
                    pass
                case self.RulesFlow.ABORT:
                    logger.debug("Rule %s triggered handler abort", rule_name)
                    op.done()
                    return False
                case self.RulesFlow.TERMINATE:
                    logger.debug("Rule %s triggered handler terminate", rule_name)
                    break
                case None:
                    logger.warning(
                        "Rule %s did not return rule flow. Defaulting to "
                        "CONTINUE, but this behaviour may change in "
                        "future.",
                        rule_name,
                    )
                case _:
                    logger.critical("Rule %s returned unhandled return type", rule_name)
                    raise TypeError(
                        f"Rule {rule_name} returned unhandled return type {type(rule_flow)}"
                    )

        return True

    def set_read_only(self, read_only: bool = True):
        """
        Make this PV read only.
        If read_only == False then the PV is made writable
        """
        if read_only == False and 'read_only' in self._put_rules:
            self._put_rules.pop('read_only')
        else:
            self._put_rules["read_only"] = (
                lambda new, old: BaseRulesHandler.RulesFlow.ABORT
            )
            self._put_rules.move_to_end("read_only", last=False)

    def _timestamp_rule(self, _, op: ServerOperation) -> RulesFlow:
        """Handle updating the timestamps"""

        # Note that timestamps are not automatically handled so we may need to set them ourselves
        newpvstate: Value = op.value().raw
        self.evaluate_timestamp(_, newpvstate)

        return self.RulesFlow.CONTINUE

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
            and if it is return the new PV state value
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

    def _controls_rule(self, pv: SharedPV, op: ServerOperation) -> BaseRulesHandler.RulesFlow:
        """Check whether control limits should trigger and restrict values appropriately"""
        logger.debug("Evaluating control limits")

        oldpvstate: Value = pv.current().raw
        newpvstate: Value = op.value().raw

        # Check if there are any controls!
        if "control" not in newpvstate and "control" not in oldpvstate:
            logger.debug("control not present in structure")
            return self.RulesFlow.CONTINUE

        combinedvals = self._combined_pvstates(oldpvstate, newpvstate, "control")

        # Check minimum step first
        if (
            abs(newpvstate["value"] - oldpvstate["value"])
            < combinedvals["control.minStep"]
        ):
            logger.debug("<minStep")
            newpvstate["value"] = oldpvstate["value"]
            return self.RulesFlow.CONTINUE

        value = self.evaluate_control_limits(combinedvals, None)
        if value:
            newpvstate["value"] = value

        return self.RulesFlow.CONTINUE

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
            return self.RulesFlow.CONTINUE

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

    

class NTScalarArrayRulesHandler(BaseRulesHandler):
    """
    Rules handler for NTScalarArray PVs.
    """
    def __init__(self) -> None:
        super().__init__()
    
        self._init_rules.update({'control' : self.evaluate_control_limits})
        self._put_rules["control"] = self._controls_rule
    
    def _controls_rule(self, pv: SharedPV, op: ServerOperation) -> BaseRulesHandler.RulesFlow:
        """Check whether control limits should trigger and restrict values appropriately"""
        logger.debug("Evaluating control limits")

        oldpvstate: Value = pv.current().raw
        newpvstate: Value = op.value().raw

        # Check if there are any controls!
        if "control" not in newpvstate and "control" not in oldpvstate:
            logger.debug("control not present in structure")
            return self.RulesFlow.CONTINUE

        combinedvals = self._combined_pvstates(oldpvstate, newpvstate, "control")

        # The numpy array used by the Value object is write protected so we need to create a copy 
        # of the value (using a list for simplicity) so individual elements can be assigned.
        newpvstateval = list(newpvstate["value"])

        for i in range(len(newpvstate["value"])):

            # Check minimum step first
            if (
                abs(newpvstate["value"][i] - oldpvstate["value"][i])
                < combinedvals["control.minStep"]
            ):
                logger.debug(f"Value at array index {i} is less than minStep {combinedvals['control.minStep']}")
                newpvstateval[i] = oldpvstate["value"][i]
            else: 
                value = self.evaluate_control_limits(combinedvals, None, index = i)
                if value:
                    logger.debug(f"Setting value to {value}")
                    newpvstateval[i] = value

        newpvstate["value"] = newpvstateval
        
        return self.RulesFlow.CONTINUE

    def evaluate_control_limits(self, combinedvals : dict, _, index : int = None) -> None | int | Numeric:
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
        
        if index is None:
            # This part is normally called when the rules are initialised
            value = list(combinedvals["value"])
            for i in range(len(combinedvals["value"])):
                # Check lower and upper control limits
                if combinedvals["value"][i] < combinedvals["control.limitLow"]:
                    value[i] = combinedvals["control.limitLow"]
                    logger.debug(f"Lower control limit exceeded for index {i}, changing value to {value[i]}")

                if combinedvals["value"][i] > combinedvals["control.limitHigh"]:
                    value[i] = combinedvals["control.limitHigh"]
                    logger.debug(f"Upper control limit exceeded for index {i}, changing value to {value[i]}")
            
            return value
        else:
            # Check lower and upper control limits
            if combinedvals["value"][index] < combinedvals["control.limitLow"]:
                value = combinedvals["control.limitLow"]
                logger.debug(f"Lower control limit exceeded for index {index}, changing value to {value}")
                return value

            if combinedvals["value"][index] > combinedvals["control.limitHigh"]:
                value = combinedvals["control.limitHigh"]
                logger.debug(f"Upper control limit exceeded for index {index}, changing value to {value}")
                return value

        return None


class NTEnumRulesHandler(BaseRulesHandler):
    """
    Rules handler for NTScalarArray PVs.
    """
    def __init__(self) -> None:
        super().__init__()
