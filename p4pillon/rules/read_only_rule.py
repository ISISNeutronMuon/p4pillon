"""
Rules for any NormativeType, making them read-only.
"""

from typing import ClassVar

from p4p import Value
from p4p.server import ServerOperation

from .rules import BaseRule, RulesFlow, SupportedNTTypes


class ReadOnlyRule(BaseRule):
    """A rule which rejects all attempts to put values"""

    # @property
    # def name(self) -> str:
    #     return "read_only"

    # @property
    # def fields(self) -> list[str]:
    #     return []
    name = "read_only"
    nttypes: ClassVar[list[SupportedNTTypes] | None] = [SupportedNTTypes.ALL]
    fields: ClassVar[list[str] | None] = []

    def put_rule(self, oldpvstate: Value, newpvstate: Value, _op: ServerOperation) -> RulesFlow:
        return RulesFlow(RulesFlow.ABORT).set_errormsg("read-only")
