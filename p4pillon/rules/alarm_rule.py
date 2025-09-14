"""
Rules for the alarm and alarm_t fields of Normative Types.
"""

from .rules import BaseRule


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
