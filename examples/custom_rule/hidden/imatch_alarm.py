"""
Demonstration of implementing a custom Rule
"""

import logging

from p4p import Value
from p4p.server import Server

from p4pillon.nt import NTScalar
from p4pillon.rules import (
    AlarmRule,
    BaseRule,
    RulesFlow,
    TimestampRule,
)
from p4pillon.rules.rules import check_applicable_init
from p4pillon.thread.sharednt import SharedNT

logger = logging.getLogger(__name__)


class IMatchRule(BaseRule):
    name = "imatch"
    fields = ["alarm"]

    def __init__(self, imatch: int | None = None):
        self._imatch = imatch

    @property
    def imatch(self):
        return self._imatch

    @imatch.setter
    def imatch(self, newval: int | None):
        self._imatch = newval

    @check_applicable_init
    def init_rule(self, newpvstate: Value) -> RulesFlow:
        # Check if imatch alarms are present and active!
        if not self._imatch:
            logger.debug("imatch not active")
            return RulesFlow.CONTINUE

        if self._imatch == newpvstate["value"]:
            newpvstate["alarm.severity"] = 2
            newpvstate["alarm.message"] = "IMATCH"
        else:
            newpvstate["alarm.severity"] = 0
            newpvstate["alarm.message"] = ""

        return RulesFlow.CONTINUE


def main():
    registered_handlers = [
        AlarmRule,
        IMatchRule,  # <-- This is the new rule
        TimestampRule,
    ]

    pv1 = SharedNT(nt=NTScalar("i"), initial=5, imatch={"imatch": 5}, registered_handlers=registered_handlers)

    pv2 = SharedNT(nt=NTScalar("i"), initial=5, imatch={"imatch": 3}, registered_handlers=registered_handlers)
    pv2.handler["imatch"].rule.imatch = 5

    pv3 = SharedNT(nt=NTScalar("i"), initial=5, imatch={"imatch": 3}, registered_handlers=registered_handlers)
    pv3.handler["imatch"].rule.imatch = 5
    pv3.post(5)

    Server.forever(
        providers=[
            {
                "demo:pv:name1": pv1,
                "demo:pv:name2": pv2,
                "demo:pv:name3": pv3,
            }
        ]
    )  # runs until KeyboardInterrupt


if __name__ == "__main__":
    main()
