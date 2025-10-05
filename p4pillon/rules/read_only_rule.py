"""
Rules for any NormativeType, making them read-only.
"""

from p4p.server import ServerOperation

from p4pillon.server.raw import SharedPV

from .rules import BaseRule, RulesFlow


class ReadOnlyRule(BaseRule):
    """A rule which rejects all attempts to put values"""

    @property
    def name(self) -> str:
        return "read_only"

    @property
    def fields(self) -> list[str]:
        return []

    def put_rule(self, pv: SharedPV, op: ServerOperation) -> RulesFlow:
        return RulesFlow(RulesFlow.ABORT).set_errormsg("read-only")
