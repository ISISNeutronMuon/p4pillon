"""Example of simplifed interface for NTScalar creation"""

import dataclasses
import logging
import time

from dataclasses import dataclass, field
from typing import SupportsFloat as Numeric  # Hack to type hint number types
from typing import TypeVar, Generic

from p4p.nt import NTEnum, NTScalar
from p4p.server.thread import Handler, SharedPV
from p4p.server import ServerOperation
from p4p import Value

from .metadata import *
from .handlers import NTScalarRulesHandler

logger = logging.getLogger(__name__)

MIN_FLOAT = float("-inf")
MAX_FLOAT = float("inf")
MIN_INT32 = -2147483648
MAX_INT32 = 2147483647


@dataclass
class Timestamp:
    """Very simple timestamp class"""

    time: float

    def time_in_seconds_and_nanoseconds(self) -> tuple[int, int]:
        """Convert to EPICS style structured timestamp"""
        seconds = int(self.time // 1)
        nanoseconds = int((self.time % 1) * 1e9)
        return (seconds, nanoseconds)


T = TypeVar("T")


@dataclass
class Control(Generic[T]):
    """Set limits on permitted values"""

    limit_low: T
    limit_high: T
    min_step: T

    # read_only = False


@dataclass
class Display(Generic[T]):
    """Set limits on values that will be displayed"""

    limit_low: T = None
    limit_high: T = None


@dataclass
class AlarmLimit(Generic[T]):
    """Conditions to test for alarms"""

    active: bool = True
    low_alarm_limit: T = None
    low_warning_limit: T = None
    high_warning_limit: T = None
    high_alarm_limit: T = None
    low_alarm_severity: AlarmSeverity = AlarmSeverity.MAJOR_ALARM
    low_warning_severity: AlarmSeverity = AlarmSeverity.MINOR_ALARM
    high_warning_severity: AlarmSeverity = AlarmSeverity.MINOR_ALARM
    high_alarm_severity: AlarmSeverity = AlarmSeverity.MAJOR_ALARM
    hysteresis: T = 0


@dataclass
class PVScalarRecipe:
    """A description of how to build a PV"""

    pvtype: PVTypes
    description: str
    initial_value: Numeric
    units: str = ""
    format: Format = Format.DEFAULT
    precision: int = -1

    # Alarm: alarm = field(init=False)
    timestamp: Timestamp = field(init=False)
    display: Display = None
    control: Control = None
    alarm_limit: AlarmLimit = None

    read_only: bool = False

    def __post_init__(self):
        """Anything that isn't done by the automatically created __init__"""

        # Initialise the members that the default init doesn't cover
        # Specifically these are the ones tagged with field(init=False)
        self.timestamp = None

    def copy(self) -> "PVScalarRecipe":
        """Return a shallow copy of this instance"""
        return dataclasses.replace(self)

    def set_control_limits(self, low: Numeric = None, high: Numeric = None, min_step: Numeric = 0, config: dict = None):
        """Add control limits"""
        
        # If config is supplied, use those values. Primarily used for reading in from YAML
        if config is not None:
            low = config.get('low')
            high = config.get('high')
            if config.get('min_step') is not None:
                min_step = config.get('min_step')

        if low is None:
            raise ValueError("low limit not set")
        if high is None:
            raise ValueError("high limit not set")
        
        match self.pvtype:
            case PVTypes.DOUBLE:
                self.control = Control[float](low, high, min_step)
            case PVTypes.INTEGER:
                self.control = Control[int](low, high, min_step)
            case PVTypes.STRING:
                raise SyntaxError("Control limits not supported on string PVs")
            case PVTypes.ENUM:
                raise SyntaxError("Control limits not supported on enum PVs")

    def set_display_limits(self, low_limit: Numeric = None, high_limit: Numeric = None, config: dict = None):
        """Add display limits"""
        if config is not None:
            low_limit = config.get('limitLow')
            high_limit = config.get('limitHigh')

        match self.pvtype:
            case PVTypes.DOUBLE:
                if low_limit is None:
                    low_limit = MIN_FLOAT
                if high_limit is None:
                    high_limit = MAX_FLOAT
                self.display = Display[float](
                    limit_low=low_limit, limit_high=high_limit
                )
            case PVTypes.INTEGER:
                if low_limit is None:
                    low_limit = MIN_INT32
                if high_limit is None:
                    high_limit = MAX_INT32
                self.display = Display[int](limit_low=low_limit, limit_high=high_limit)
            case PVTypes.STRING:
                raise SyntaxError("Control limits not supported on string PVs")
            case PVTypes.ENUM:
                raise SyntaxError("Control limits not supported on enum PVs")

    def set_alarm_limits(
        self,
        low_warning: Numeric = None,
        high_warning: Numeric = None,
        low_alarm: Numeric = None,
        high_alarm: Numeric = None,
        config: dict = None
    ):
        """Add alarm limits"""
        print(f"config is {config}")
        if config is not None:
            low_warning = config.get('lowWarningLimit')
            high_warning = config.get('highWarningLimit')
            low_alarm = config.get('lowAlarmLimit')
            high_alarm = config.get('highAlarmLimit')
            
        match self.pvtype:
            case PVTypes.DOUBLE:
                if low_warning is None:
                    low_warning = MIN_FLOAT
                if high_warning is None:
                    high_warning = MAX_FLOAT
                if low_alarm is None:
                    low_alarm = MIN_FLOAT
                if high_alarm is None:
                    high_alarm = MAX_FLOAT
                self.alarm_limit = AlarmLimit[float](
                    low_alarm_limit=low_alarm,
                    low_warning_limit=low_warning,
                    high_warning_limit=high_warning,
                    high_alarm_limit=high_alarm,
                )
            case PVTypes.INTEGER:
                if low_warning is None:
                    low_warning = MIN_INT32
                if high_warning is None:
                    high_warning = MAX_INT32
                if low_alarm is None:
                    low_alarm = MIN_INT32
                if high_alarm is None:
                    high_alarm = MAX_INT32
                self.alarm_limit = AlarmLimit[int](
                    low_alarm_limit=low_alarm,
                    low_warning_limit=low_warning,
                    high_warning_limit=high_warning,
                    high_alarm_limit=high_alarm,
                )
            case PVTypes.STRING:
                raise SyntaxError("Alarm limits not supported on string PVs")
            case PVTypes.ENUM:
                raise SyntaxError("Alarm limits not supported on enum PVs")

    def create_pv(self, pv_name: str) -> NTScalar | NTEnum:
        """Turn the recipe into an actual NTScalar, NTEnum, or
        other BasePV derived object"""
        construct_settings = {}
        config_settings = {}

        construct_settings["valtype"] = self.pvtype.value
        construct_settings["extra"] = [("descriptor", "s")]
        config_settings["descriptor"] = self.description

        self._config_display(construct_settings, config_settings)

        if self.control:
            self._config_control(construct_settings, config_settings)

        if self.alarm_limit:
            self._config_alarm_limit(construct_settings, config_settings)

        print(f"construct settings are: \n {construct_settings} \n and config settings are:\n {config_settings} ")
        handler = NTScalarRulesHandler()
        match self.pvtype:
            case PVTypes.DOUBLE | PVTypes.INTEGER:
                nt = NTScalar(**construct_settings)
            case PVTypes.ENUM:
                nt = NTEnum(**construct_settings)
            case _:
                raise NotImplementedError()

        pvobj = SharedPV(
            nt=nt, initial=self.initial_value, timestamp=time.time(), handler=handler
        )
        pvobj.post(config_settings)
        handler._name = pv_name

        if self.read_only:
            handler._put_rules["read_only"] = (
                lambda new, old: NTScalarRulesHandler.RulesFlow.ABORT
            )
            handler._put_rules.move_to_end("read_only", last=False)

        handler._post_init(pvobj)
        handler._init_rules["timestamp"] = handler.evaluate_timestamp

        return pvobj

    def _config_display(self, construct_settings, config_settings):
        if self.units:
            construct_settings["display"] = True
            config_settings["display.description"] = self.description
            config_settings["display.units"] = self.units

        # Precision doesn't actually seem to be supported in Phoebus
        if self.precision != -1:
            construct_settings["display"] = True
            construct_settings["form"] = True
            config_settings["display.description"] = self.description
            config_settings["display.precision"] = self.precision

        if self.format != Format.DEFAULT:
            construct_settings["display"] = True
            config_settings["display.description"] = self.description
            if "display.precision" not in config_settings:
                config_settings["display.format"] = self.format.value[1]
            else:
                construct_settings["form"] = True
                config_settings["display.form.index"] = self.format.value[0]
                config_settings["display.form.choices"] = [
                    "Default",
                    "String",
                    "Binary",
                    "Decimal",
                    "Hex",
                    "Exponential",
                    "Engineering",
                ]

        if self.display:
            construct_settings["display"] = True
            config_settings["display.description"] = self.description
            config_settings["display.limitLow"] = self.display.limit_low
            config_settings["display.limitHigh"] = self.display.limit_high

    def _config_alarm_limit(self, construct_settings, config_settings):
        construct_settings["valueAlarm"] = True
        config_settings["valueAlarm.active"] = self.alarm_limit.active
        config_settings["valueAlarm.lowAlarmLimit"] = self.alarm_limit.low_alarm_limit
        config_settings["valueAlarm.lowWarningLimit"] = (
            self.alarm_limit.low_warning_limit
        )
        config_settings["valueAlarm.highWarningLimit"] = (
            self.alarm_limit.high_warning_limit
        )
        config_settings["valueAlarm.highAlarmLimit"] = self.alarm_limit.high_alarm_limit
        config_settings["valueAlarm.lowAlarmSeverity"] = (
            self.alarm_limit.low_alarm_severity.value
        )
        config_settings["valueAlarm.lowWarningSeverity"] = (
            self.alarm_limit.low_warning_severity.value
        )
        config_settings["valueAlarm.highWarningSeverity"] = (
            self.alarm_limit.high_warning_severity.value
        )
        config_settings["valueAlarm.highAlarmSeverity"] = (
            self.alarm_limit.high_alarm_severity.value
        )
        config_settings["valueAlarm.hysteresis"] = self.alarm_limit.hysteresis

    def _config_control(self, construct_settings, config_settings):
        construct_settings["control"] = True
        config_settings["control.limitLow"] = self.control.limit_low
        config_settings["control.limitHigh"] = self.control.limit_high
        config_settings["control.minStep"] = self.control.min_step
