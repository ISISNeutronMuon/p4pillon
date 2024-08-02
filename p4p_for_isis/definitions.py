from enum import Enum


class PVTypes(Enum):
    DOUBLE = "d"
    INTEGER = "i"
    STRING = "s"
    ENUM = "e"


class AlarmSeverity(Enum):
    NO_ALARM = 0
    MINOR_ALARM = 1
    MAJOR_ALARM = 2
    INVALID_ALARM = 3
    UNDEFINED_ALARM = 4


class AlarmStatus(Enum):
    NO_STATUS = 0
    DEVICE_STATUS = 1
    DRIVER_STATUS = 2
    RECORD_STATUS = 3
    DB_STATUS = 4
    CONF_STATUS = 5
    UNDEFINED_STATUS = 6
    CLIENT_STATUS = 7


class Format(Enum):
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
