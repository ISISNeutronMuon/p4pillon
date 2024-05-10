import logging
import time

from collections import OrderedDict
from enum import Enum

from p4p import Value
from p4p.server import ServerOperation
from p4p.server.thread import Handler, SharedPV

from p4p_for_isis.utils import time_in_seconds_and_nanoseconds


logger = logging.getLogger(__name__)
class NTScalarRulesHandler(Handler):
    ''' Implement the most common rules for NTScalars '''
    class RulesFlow(Enum):
        CONTINUE = 1    # Continue rules processing
        TERMINATE = 2   # Do not process more rules but we're good to here
        ABORT = 3       # Stop rules processing and abort put

    def __init__(self) -> None:
        super().__init__()
        self._name = None
        self._put_rules = OrderedDict()

        self._put_rules['control'] = self._controls_rule
        self._put_rules['timestamp'] = self._timestamp_rule


    def put(self, pv : SharedPV, op : ServerOperation) -> None:
        ''' Put that applies a set of rules '''
        self._name = op.name()

        #oldpvstate : Value = pv.current().raw
        newpvstate : Value = op.value().raw

        logger.info('Processing changes to PV %s', op.name())
        logger.debug('Changes to the following fields: %r', newpvstate.changedSet())

        for rule_name, put_rule in self._put_rules.items():
            rule_flow = put_rule(pv, op)

            match (rule_flow):
                case self.RulesFlow.CONTINUE:
                    pass
                case self.RulesFlow.ABORT:
                    logger.debug('Rule %s triggered handler abort', rule_name)
                    op.done()
                    return
                case self.RulesFlow.TERMINATE:
                    logger.debug('Rule %s triggered handler terminate', rule_name)
                    break
                case None:
                    logger.warning('Rule %s did not return rule flow. Defaulting to CONTINUE, but this behaviour may change in future.', rule_name)
                case _:
                    logger.critical('Rule %s returned unhandled return type', rule_name)
                    raise TypeError(f'Rule {rule_name} returned unhandled return type {type(rule_flow)}')

        logger.info("Making the following changes to %s: %r", self._name, newpvstate.changedSet())
        pv.post(op.value()) # just store and update subscribers

        op.done()


    def _timestamp_rule(self, _, op : ServerOperation):
        ''' Handle updating the timestamps '''

        # Note that timestamps are not automatically handled so we may need to set them ourselves
        newpvstate : Value = op.value().raw

        if newpvstate.changed('timeStamp'):
            logger.debug('Using timeStamp from put operation')
        else:
            logger.debug('Generating timeStamp')
            sec, nsec = time_in_seconds_and_nanoseconds(time.time())
            newpvstate['timeStamp.secondsPastEpoch'] = sec
            newpvstate['timeStamp.nanoseconds'] = nsec
    

    def _controls_rule(self, pv : SharedPV, op : ServerOperation) -> RulesFlow:
        """ Check whether control limits should trigger and restrict values appropriately"""
        logger.debug('Evaluating control limits')

        oldpvstate : Value = pv.current().raw
        newpvstate : Value = op.value().raw

        # Check if there are any controls!
        if 'control' not in newpvstate and 'control' not in oldpvstate:
            logger.info('control not present in structure')
            return self.RulesFlow.CONTINUE

        combinedvals = self._combined_pvstates(oldpvstate, newpvstate, 'control')

        # Check minimum step first
        if abs(newpvstate['value']-oldpvstate['value']) < combinedvals['control.minStep']:
            logger.debug('<minStep')
            newpvstate['value'] = oldpvstate['value']

        # A philosophical question! What should we do when lowLimit = highLimit = 0?
        # This almost certainly means the structure hasn't been initialised, but it could
        # be an attempt (for some reason) to lock the value to 0. For now we treat this
        # as uninitialised and ignore limits in this case. Users will have to handle 
        # keeping the PV constant at 0 themselves
        if combinedvals['control.limitLow'] == 0 and combinedvals['control.limitHigh'] == 0:
            logger.info('control.limitLow and control.LimitHigh set to 0, so ignoring control limits')
            return self.RulesFlow.CONTINUE

        # Check lower and upper control limits
        if combinedvals['value'] < combinedvals['control.limitLow']:
            logger.debug('Lower limit')
            newpvstate['value'] = combinedvals['control.limitLow']
            return self.RulesFlow.CONTINUE

        if combinedvals['value'] > combinedvals['control.limitHigh']:
            logger.debug('Upper limit')
            newpvstate['value'] = combinedvals['control.limitHigh']
            return self.RulesFlow.CONTINUE
        
        return True

    def _combined_pvstates(self, oldpvstate : Value, newpvstate : Value, interest : str) -> dict:
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
            """ Check a key. If it isn't marked as changed return the old PV state value,
                and if it is return the new PV state value
            """
            if newpvstate.changed(key):
                return newpvstate[key]
            else:
                return oldpvstate[key]

        combinedvals = {}
        combinedvals['value'] = extract_combined_value(newpvstate, oldpvstate, 'value')
        for key in newpvstate[interest]:
            fullkey = f'{interest}.{key}'
            combinedvals[fullkey] = extract_combined_value(newpvstate, oldpvstate, fullkey)

        return combinedvals