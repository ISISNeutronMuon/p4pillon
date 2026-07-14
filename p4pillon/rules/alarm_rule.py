"""
Rules for the alarm and alarm_t fields of Normative Types.
"""

from typing import ClassVar

from .rules import BaseRule


class AlarmRule(BaseRule):
    """
    This class exists only to allow the alarm field, i.e. severity and
    message to be made read-only for put operations
    """

    name = "alarm"
    fields: ClassVar[list[str] | None] = ["alarm"]
