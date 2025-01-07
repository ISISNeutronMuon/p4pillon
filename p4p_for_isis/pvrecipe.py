"""Example of simplifed interface for NTScalar creation"""

import collections.abc
import dataclasses
import logging
import time
from abc import abstractmethod
from dataclasses import dataclass
from typing import Generic, Tuple, TypeVar, Union
from typing import SupportsFloat as Numeric  # Hack to type hint number types

from p4p.nt import NTEnum, NTScalar
from p4p.server.thread import SharedPV

from p4p_for_isis.isispv import ISISPV

from .definitions import (
    MAX_FLOAT,
    MAX_INT32,
    MIN_FLOAT,
    MIN_INT32,
    AlarmSeverity,
    Format,
    PVTypes,
)
from .handlers import (
    BaseRulesHandler,
    NTEnumRulesHandler,
    NTScalarArrayRulesHandler,
    NTScalarRulesHandler,
)
from .utils import time_in_seconds_and_nanoseconds

logger = logging.getLogger(__name__)


@dataclass
class Timestamp:
    """Very simple timestamp class"""

    time: float

    def time_in_seconds_and_nanoseconds(self) -> Tuple[int, int]:
        """Convert to EPICS style structured timestamp"""
        return time_in_seconds_and_nanoseconds(self.time)


T = TypeVar("T", int, Numeric)


@dataclass
class Control(Generic[T]):
    """Set limits on permitted values"""

    limit_low: T = None
    limit_high: T = None
    min_step: T = 0


@dataclass
class Display(Generic[T]):
    """Set limits on values that will be displayed"""

    limit_low: T = None
    limit_high: T = None
    units: str = ""
    format: Format = Format.DEFAULT
    precision: int = 2


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
    initial_value: Union[Numeric, list, str]

    # Alarm: alarm = field(init=False)
    timestamp: Union[Timestamp, None] = None
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
    def create_pv(self, pv_name: str) -> SharedPV:
        raise NotImplementedError

    def _config_timestamp(self):
        if self.timestamp:
            seconds, nanoseconds = self.timestamp.time_in_seconds_and_nanoseconds()
        else:
            seconds, nanoseconds = Timestamp(time.time()).time_in_seconds_and_nanoseconds()
        self.config_settings["timeStamp.secondsPastEpoch"] = seconds
        self.config_settings["timeStamp.nanoseconds"] = nanoseconds

    def build_pv(self, pv_name: str, handler: BaseRulesHandler) -> SharedPV:
        """
        This method is called by create_pv in the child classes after construct settings is set.
        """
        debugStr = f"Building pv\n Construct settings are: \n {self.construct_settings} \n"+\
            f" Config settings are:\n {self.config_settings} \n Initial value:\n {self.initial_value}\n"
        
        if hasattr(self,"forward_links"):
            # Add forward links to the handler
            debugStr += f" Forward links are: \n {self.forward_links}"
            handler.add_forward_links(self.forward_links)

        if hasattr(self,"calc"):
            # Add a calc rule to the handler
            debugStr += f" Calc details are: \n {self.calc}"
            handler.add_calc(self.calc)

        logger.debug(debugStr)

        if (
            self.construct_settings["valtype"] not in ["s", "e"]
            and isinstance(self.initial_value, collections.abc.Sequence)
            and not self.construct_settings["valtype"].startswith("a")
        ):
            self.construct_settings["valtype"] = "a" + self.construct_settings["valtype"]

        if self.pvtype == PVTypes.ENUM:
            nt = NTEnum(**self.construct_settings)
        else:
            nt = NTScalar(**self.construct_settings)

        self._config_timestamp()

        pvobj = ISISPV(nt=nt, initial=self.initial_value, handler=handler)
        pvobj.post(self.config_settings)
        handler._name = pv_name

        if self.read_only:
            handler.set_read_only()

        # handler.onFirstCall(pvobj)
        # AK: The line below is now done in the handler. The rule is evaluated last in the
        # above call to _rules_init()
        # handler._init_rules["timestamp"] = handler.evaluate_timestamp

        return pvobj

    def set_forward_links(self, links: str | list):
        """
        Add forward links to the pvrecipe. Links can be a single pv name or a list of pv names. 
        """
        if hasattr(self,'forward_links') == False: 
            self.forward_links = []

        if type(links) == list:
            for link in links:
                self.forward_links.append(link)
        else:
            self.forward_links.append(links)

    def copy(self) -> "BasePVRecipe":
        """Return a shallow copy of this instance"""
        return dataclasses.replace(self)

    def set_timestamp(self, timestamp: float):
        self.timestamp = Timestamp(timestamp)


class PVScalarRecipe(BasePVRecipe):
    """Recipe to build an NTScalar"""

    def __post_init__(self):
        super().__post_init__()
        if self.pvtype != PVTypes.DOUBLE and self.pvtype != PVTypes.INTEGER and self.pvtype != PVTypes.STRING:
            raise ValueError(f"Unsupported pv type {self.pvtype} " "for class {self.__class__.__name__}")

    def set_control_limits(self, low: Numeric = None, high: Numeric = None, min_step=0):
        """
        Add control limits
        config is a dictionary of low_limit and high_limit. This is used by the config_reader.
        """
        if self.pvtype == PVTypes.DOUBLE:
            if low is None:
                low = MIN_FLOAT
            if high is None:
                high = MAX_FLOAT
            self.control = Control[float](limit_low=low, limit_high=high, min_step=min_step)
        elif self.pvtype == PVTypes.INTEGER:
            if low is None:
                low = MIN_INT32
            if high is None:
                high = MAX_INT32
            self.control = Control[int](limit_low=low, limit_high=high, min_step=min_step)
        elif self.pvtype == PVTypes.STRING:
            raise SyntaxError("Control limits not supported on string PVs")
        else:
            raise ValueError("Unknown pvtype")

    def set_display_limits(
        self,
        low: Numeric = None,
        high: Numeric = None,
        units: str = "",
        format: Format = Format.DEFAULT,
        precision: int = 2,
    ):
        """
        Add display limits
        config is a dictionary of low_limit and high_limit. This is used by the config_reader.
        """
        if isinstance(format, str):
            # check if it's in the available options
            try:
                choices = [form.value[1] for form in Format]
                idx = choices.index(format.title())
                format = list(Format)[idx]
            except ValueError as e:
                raise ValueError(f"{format} not an available format, choices are: {choices}") from e

        if self.pvtype == PVTypes.DOUBLE:
            if low is None:
                low = MIN_FLOAT
            if high is None:
                high = MAX_FLOAT
            self.display = Display[float](
                limit_low=low,
                limit_high=high,
                units=units,
                format=format,
                precision=precision,
            )
        elif self.pvtype == PVTypes.INTEGER:
            if low is None:
                low = MIN_INT32
            if high is None:
                high = MAX_INT32
            self.display = Display[int](
                limit_low=low,
                limit_high=high,
                units=units,
                format=format,
                precision=precision,
            )
        elif self.pvtype == PVTypes.STRING:
            raise SyntaxError("Display limits not supported on string PVs")
        else:
            raise ValueError("Unknown pvtype")

    def set_alarm_limits(
        self,
        low_warning: Numeric = None,
        high_warning: Numeric = None,
        low_alarm: Numeric = None,
        high_alarm: Numeric = None,
    ):
        """
        Add display limits
        config is a dictionary of low_limit and high_limit. This is used by the config_reader.
        """
        if self.pvtype == PVTypes.DOUBLE:
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
        elif self.pvtype == PVTypes.INTEGER:
            if low_warning is None:
                low_warning = MIN_INT32
            if high_warning is None:
                high_warning = MAX_INT32
            if low_alarm is None:
                low_alarm = MIN_INT32
            if high_alarm is None:
                high_alarm = MAX_INT32
            self.alarm_limit = AlarmLimit[float](
                low_alarm_limit=low_alarm,
                low_warning_limit=low_warning,
                high_warning_limit=high_warning,
                high_alarm_limit=high_alarm,
            )
        elif self.pvtype == PVTypes.STRING:
            raise SyntaxError("Alarm limits not supported on string PVs")
        else:
            raise ValueError("Unknown pvtype")

    @abstractmethod
    def create_pv(self, pv_name: str) -> SharedPV:
        """Turn the recipe into an actual NTScalar, NTEnum, or
        other BasePV derived object"""

        if self.display:
            self._config_display()

        if self.control:
            self._config_control()

        if self.alarm_limit:
            self._config_alarm_limit()

        handler = NTScalarRulesHandler()

        return super().build_pv(pv_name, handler)

    def _config_display(self):
        # we configure the display settings if a Display object is configured or if all of
        # units, format and precision are not configured as the defaults
        self.construct_settings["display"] = True
        self.construct_settings["form"] = True
        self.config_settings["display.description"] = self.description
        self.config_settings["display.units"] = self.display.units
        self.config_settings["display.precision"] = self.display.precision
        self.config_settings["display.form.index"] = self.display.format.value[0]
        self.config_settings["display.form.choices"] = [form.value[1] for form in Format]
        self.config_settings["display.limitLow"] = self.display.limit_low
        self.config_settings["display.limitHigh"] = self.display.limit_high

    def _config_alarm_limit(self):
        self.construct_settings["valueAlarm"] = True
        self.config_settings["valueAlarm.active"] = self.alarm_limit.active
        self.config_settings["valueAlarm.lowAlarmLimit"] = self.alarm_limit.low_alarm_limit
        self.config_settings["valueAlarm.lowWarningLimit"] = self.alarm_limit.low_warning_limit
        self.config_settings["valueAlarm.highWarningLimit"] = self.alarm_limit.high_warning_limit
        self.config_settings["valueAlarm.highAlarmLimit"] = self.alarm_limit.high_alarm_limit
        self.config_settings["valueAlarm.lowAlarmSeverity"] = self.alarm_limit.low_alarm_severity.value
        self.config_settings["valueAlarm.lowWarningSeverity"] = self.alarm_limit.low_warning_severity.value
        self.config_settings["valueAlarm.highWarningSeverity"] = self.alarm_limit.high_warning_severity.value
        self.config_settings["valueAlarm.highAlarmSeverity"] = self.alarm_limit.high_alarm_severity.value
        self.config_settings["valueAlarm.hysteresis"] = self.alarm_limit.hysteresis

    def _config_control(self):
        self.construct_settings["control"] = True
        self.config_settings["control.limitLow"] = self.control.limit_low
        self.config_settings["control.limitHigh"] = self.control.limit_high
        self.config_settings["control.minStep"] = self.control.min_step


class PVScalarArrayRecipe(PVScalarRecipe):
    """Recipe to create an NTScalarArray"""

    @abstractmethod
    def create_pv(self, pv_name: str) -> SharedPV:
        """Turn the recipe into an actual NTScalar with an array"""

        if self.display:
            self._config_display()

        if self.control:
            self._config_control()

        if self.alarm_limit:
            self._config_alarm_limit()

        handler = NTScalarArrayRulesHandler()

        if not isinstance(self.initial_value, list):
            self.initial_value = [self.initial_value]

        return super().build_pv(pv_name, handler)


class PVEnumRecipe(BasePVRecipe):
    """Recipe to create an NTEnum"""

    def __post_init__(self):
        super().__post_init__()
        if self.pvtype != PVTypes.ENUM:
            raise ValueError(f"Unsupported pv type {self.pvtype} " "for class {self.__class__.__name__}")

    @abstractmethod
    def create_pv(self, pv_name: str) -> SharedPV:
        """Turn the recipe into an actual NTEnum"""

        handler = NTEnumRulesHandler()

        return super().build_pv(pv_name, handler)
