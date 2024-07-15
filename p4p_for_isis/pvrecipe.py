"""Example of simplifed interface for NTScalar creation"""

import collections.abc
import dataclasses
import logging
import time

from abc import abstractmethod

from dataclasses import dataclass
from typing import SupportsFloat as Numeric  # Hack to type hint number types
from typing import TypeVar, Generic

from p4p.nt import NTEnum, NTScalar
from p4p.server.thread import SharedPV

from .definitions import PVTypes, AlarmSeverity, Format
from .handlers import BaseRulesHandler, NTScalarRulesHandler, \
                      NTEnumRulesHandler, NTScalarArrayRulesHandler

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


T = TypeVar('T', int, Numeric)


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
class BasePVRecipe:
    """A description of how to build a PV"""

    pvtype: PVTypes
    description: str
    initial_value: Numeric | list | str
    units: str = ""
    format: Format = Format.DEFAULT
    precision: int = -1

    # Alarm: alarm = field(init=False)
    timestamp: Timestamp | None = None
    display: Display = None
    control: Control = None
    alarm_limit: AlarmLimit = None

    read_only: bool = False

    def __post_init__(self):
        """Anything that isn't done by the automatically created __init__"""

        # Initialise the members that the default init doesn't cover
        # Specifically these are the ones tagged with field(init=False)
        self.construct_settings = {}
        self.config_settings = {}

        self.construct_settings["valtype"] = self.pvtype.value
        self.construct_settings["extra"] = [("descriptor", "s")]
        self.config_settings["descriptor"] = self.description

    @abstractmethod
    def create_pv(self, pv_name: str) -> NTScalar | NTEnum:
        raise NotImplementedError

    def build_pv(self, pv_name: str, handler: BaseRulesHandler) -> SharedPV:
        """
        This method is called by create_pv in the child classes after construct settings is set.
        """

        logger.debug("Building pv. Construct settings are: \n %r \n"
                     "and config settings are:\n %r",
                     self.construct_settings, self.config_settings)

        if (self.construct_settings['valtype'] not in ['s', 'e']
            and isinstance(self.initial_value, collections.abc.Sequence)
            and not self.construct_settings['valtype'].startswith('a')
            ):
            self.construct_settings['valtype'] = 'a' + self.construct_settings['valtype']

        if self.pvtype == PVTypes.ENUM:
            nt = NTEnum(**self.construct_settings)
        else:
            nt = NTScalar(**self.construct_settings)

        pvobj = SharedPV(
            nt=nt, initial=self.initial_value, timestamp=time.time(), handler=handler
        )
        pvobj.post(self.config_settings)
        handler._name = pv_name

        if self.read_only:
            handler.set_read_only()

        handler._post_init(pvobj)
        # AK: The line below is now done in the handler. The rule is evaluated last in the
        # above call to _post_init()
        # handler._init_rules["timestamp"] = handler.evaluate_timestamp

        return pvobj

    def copy(self) -> "BasePVRecipe":
        """Return a shallow copy of this instance"""
        return dataclasses.replace(self)

class PVScalarRecipe(BasePVRecipe):
    """ Recipe to build an NTScalar """

    def __post_init__(self):
        super().__post_init__()
        if self.pvtype != PVTypes.DOUBLE and self.pvtype != PVTypes.INTEGER:
            raise ValueError(f"Unsupported pv type {self.pvtype} "
                             "for class {self.__class__.__name__}")

    def set_control_limits(self,
                           low: Numeric = None, high: Numeric = None, min_step: Numeric = 0,
                           config: dict = None):
        """
        Add control limits
        config is a dictionary of low, high, min_step. This is used by the config_reader
        """

        # If config is supplied, use those values. Primarily used for reading in from YAML
        if config is not None:
            low = config.get('low')
            high = config.get('high')
            if config.get('min_step') is not None:
                # NB if min_step is not in config then the default, min_step=0, is used.
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

    def set_display_limits(self,
                           low_limit: Numeric = None, high_limit: Numeric = None,
                           config: dict = None):
        """
        Add display limits
        config is a dictionary of low_limit and high_limit. This is used by the config_reader.
        """
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

    @abstractmethod
    def create_pv(self, pv_name: str) -> NTScalar:
        """Turn the recipe into an actual NTScalar, NTEnum, or
        other BasePV derived object"""

        self._config_display()

        if self.control:
            self._config_control()

        if self.alarm_limit:
            self._config_alarm_limit()

        handler = NTScalarRulesHandler()

        return super().build_pv(pv_name, handler)

    def _config_display(self):
        if self.units:
            self.construct_settings["display"] = True
            self.config_settings["display.description"] = self.description
            self.config_settings["display.units"] = self.units

        # Precision doesn't actually seem to be supported in Phoebus
        if self.precision != -1:
            self.construct_settings["display"] = True
            self.construct_settings["form"] = True
            self.config_settings["display.description"] = self.description
            self.config_settings["display.precision"] = self.precision

        if self.format != Format.DEFAULT:
            self.construct_settings["display"] = True
            self.config_settings["display.description"] = self.description
            if "display.precision" not in self.config_settings:
                self.config_settings["display.format"] = self.format.value[1]
            else:
                self.construct_settings["form"] = True
                self.config_settings["display.form.index"] = self.format.value[0]
                self.config_settings["display.form.choices"] = [
                    "Default",
                    "String",
                    "Binary",
                    "Decimal",
                    "Hex",
                    "Exponential",
                    "Engineering",
                ]

        if self.display:
            self.construct_settings["display"] = True
            self.config_settings["display.description"] = self.description
            self.config_settings["display.limitLow"] = self.display.limit_low
            self.config_settings["display.limitHigh"] = self.display.limit_high

    def _config_alarm_limit(self):
        self.construct_settings["valueAlarm"] = True
        self.config_settings["valueAlarm.active"] = self.alarm_limit.active
        self.config_settings["valueAlarm.lowAlarmLimit"] = self.alarm_limit.low_alarm_limit
        self.config_settings["valueAlarm.lowWarningLimit"] = (
            self.alarm_limit.low_warning_limit
        )
        self.config_settings["valueAlarm.highWarningLimit"] = (
            self.alarm_limit.high_warning_limit
        )
        self.config_settings["valueAlarm.highAlarmLimit"] = self.alarm_limit.high_alarm_limit
        self.config_settings["valueAlarm.lowAlarmSeverity"] = (
            self.alarm_limit.low_alarm_severity.value
        )
        self.config_settings["valueAlarm.lowWarningSeverity"] = (
            self.alarm_limit.low_warning_severity.value
        )
        self.config_settings["valueAlarm.highWarningSeverity"] = (
            self.alarm_limit.high_warning_severity.value
        )
        self.config_settings["valueAlarm.highAlarmSeverity"] = (
            self.alarm_limit.high_alarm_severity.value
        )
        self.config_settings["valueAlarm.hysteresis"] = self.alarm_limit.hysteresis

    def _config_control(self):
        self.construct_settings["control"] = True
        self.config_settings["control.limitLow"] = self.control.limit_low
        self.config_settings["control.limitHigh"] = self.control.limit_high
        self.config_settings["control.minStep"] = self.control.min_step

class PVScalarArrayRecipe(BasePVRecipe):
    """ Recipe to create an NTScalarArray """

    @abstractmethod
    def create_pv(self, pv_name: str) -> NTScalar:
        """ Turn the recipe into an actual NTScalar with an array """

        handler = NTScalarArrayRulesHandler()

        return super().build_pv(pv_name, handler)

class PVEnumRecipe(BasePVRecipe):
    """ Recipe to create an NTEnum """

    def __post_init__(self):
        super().__post_init__()
        if self.pvtype != PVTypes.ENUM:
            raise ValueError(f"Unsupported pv type {self.pvtype} "
                             "for class {self.__class__.__name__}")

    @abstractmethod
    def create_pv(self, pv_name: str) -> NTEnum:
        """Turn the recipe into an actual NTEnum"""

        handler = NTEnumRulesHandler()

        return super().build_pv(pv_name, handler)
