"""
Demonstration of implementing a custom Rule
"""

import logging

import p4p.nt.common as nt_common
from p4p import Type, Value
from p4p.nt.scalar import _metaHelper
from p4p.server import Server

from p4pillon.nt import NTScalar
from p4pillon.rules import (
    AlarmRule,
    BaseRule,
    ControlRule,
    RulesFlow,
    TimestampRule,
    ValueAlarmRule,
)
from p4pillon.rules.rules import check_applicable_init
from p4pillon.thread.sharednt import SharedNT

logger = logging.getLogger(__name__)


class NTScalarMatch(NTScalar):
    """
    Extend NTScalar with imatch fields
    """

    @staticmethod
    def buildType(valtype, extra=[], *args, **kws):
        """Build a Type

        :param str valtype: A type code to be used with the 'value' field.  See :ref:`valuecodes`
        :param list extra: A list of tuples describing additional non-standard fields
        :param bool display: Include optional fields for display meta-data
        :param bool control: Include optional fields for control meta-data
        :param bool valueAlarm: Include optional fields for alarm level meta-data
        :param bool form: Include ``display.form`` instead of the deprecated ``display.format``.
        :returns: A :py:class:`Type`
        """
        isarray = valtype[:1] == "a"
        fields = [
            ("value", valtype),
            ("alarm", nt_common.alarm),
            ("timeStamp", nt_common.timeStamp),
            ("imatch", Type(id="imatch_t", spec=[("active", "?"), ("imatch", "i")])),
        ]
        _metaHelper(fields, valtype, *args, **kws)
        fields.extend(extra)
        return Type(id="epics:nt/NTScalarArray:1.0" if isarray else "epics:nt/NTScalar:1.0", spec=fields)

    def __init__(self, valtype="d", **kws):
        self.type = self.buildType(valtype, **kws)


class IMatchRule(BaseRule):
    name = "imatch"
    fields = ["alarm", "imatch"]

    @check_applicable_init
    def init_rule(self, newpvstate: Value) -> RulesFlow:
        # Check if imatch alarms are present and active!
        if not newpvstate["imatch.active"]:
            # TODO: This is wrong! If valueAlarm was active and then made inactive
            #       the alarm will not be cleared
            logger.debug("imatch not active")
            return RulesFlow.CONTINUE

        if newpvstate["imatch.imatch"] == newpvstate["value"]:
            newpvstate["alarm.severity"] = 2
            newpvstate["alarm.message"] = "IMATCH"
        else:
            newpvstate["alarm.severity"] = 0
            newpvstate["alarm.message"] = ""

        return RulesFlow.CONTINUE


# Register the new rule
SharedNT.registered_handlers = [
    AlarmRule,
    ControlRule,
    ValueAlarmRule,
    IMatchRule,  # <-- This is the new rule
    TimestampRule,
]


def main():
    pv = SharedNT(nt=NTScalarMatch("i"), initial={"value": 5, "imatch.active": True, "imatch.imatch": 5})

    Server.forever(
        providers=[
            {
                "demo:pv:name": pv,  # PV name only appears here
            }
        ]
    )  # runs until KeyboardInterrupt


if __name__ == "__main__":
    main()
