"""Enums used by p4pillon"""

from enum import Enum, IntEnum
from typing import TypedDict


class PVTypes(Enum):
    """Supported p4p Types"""

    DOUBLE = "d"
    INTEGER = "i"
    STRING = "s"
    ENUM = "e"


class AlarmSeverity(IntEnum):
    """PVAccess Normative Type alarm severities"""

    NO_ALARM = 0
    MINOR_ALARM = 1
    MAJOR_ALARM = 2
    INVALID_ALARM = 3
    UNDEFINED_ALARM = 4


class AlarmStatus(IntEnum):
    """PVAccess Normative Type alarm status codes"""

    NO_STATUS = 0
    DEVICE_STATUS = 1
    DRIVER_STATUS = 2
    RECORD_STATUS = 3
    DB_STATUS = 4
    CONF_STATUS = 5
    UNDEFINED_STATUS = 6
    CLIENT_STATUS = 7


class AlarmDict(TypedDict):
    """Normative Type alarm or alarm_t as Python dictionary"""

    severity: AlarmSeverity
    status: AlarmStatus
    message: str


class Format(Enum):
    """PVAccess Normative Type display format mappings"""

    DEFAULT = (0, "Default")
    STRING = (1, "String")
    BINARY = (2, "Binary")
    DECIMAL = (3, "Decimal")
    HEX = (4, "Hex")
    EXPONENTIAL = (5, "Exponential")
    ENGINEERING = (6, "Engineering")


MIN_FLOAT = float("-inf")
MAX_FLOAT = float("inf")
MIN_INT32 = -2147483648
MAX_INT32 = 2147483647
