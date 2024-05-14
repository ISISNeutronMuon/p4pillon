''' Example of simplifed interface for NTScalar creation '''
import dataclasses
import logging
import time

from dataclasses import dataclass, field
from typing import SupportsFloat as Numeric # Hack to type hint number types
from typing import TypeVar, Generic

from p4p.nt import NTEnum, NTScalar
from p4p.server.thread import Handler, SharedPV
from p4p.server import ServerOperation
from p4p import Value

from .pvs import *
from .handlers import NTScalarRulesHandler

logger = logging.getLogger(__name__)

@dataclass
class Timestamp:
    ''' Very simple timestamp class '''
    time: float

    def time_in_seconds_and_nanoseconds(self) -> tuple[int,int]:
        ''' Convert to EPICS style structured timestamp '''
        seconds     = int(self.time // 1)
        nanoseconds = int((self.time % 1) * 1e9)
        return (seconds, nanoseconds)

T = TypeVar('T')

@dataclass
class Control(Generic[T]):
    ''' Set limits '''
    limit_low: T
    limit_high: T
    min_step: T

    #read_only = False

@dataclass
class Display(Generic[T]):
    limit_low: T = None
    limit_high: T = None

@dataclass
class AlarmLimit(Generic[T]):
    ''' Conditions to test for alarms '''
    active : bool = True
    low_alarm_limit : T = None
    low_warning_limit : T = None
    high_warning_limit : T = None
    high_alarm_limit : T = None
    low_alarm_severity : AlarmSeverity = AlarmSeverity.MAJOR_ALARM
    low_warning_severity : AlarmSeverity = AlarmSeverity.MINOR_ALARM
    high_warning_severity : AlarmSeverity = AlarmSeverity.MINOR_ALARM
    high_alarm_severity : AlarmSeverity = AlarmSeverity.MAJOR_ALARM
    hysteresis : T = 0

@dataclass
class PVScalarRecipe:
    ''' A description of how to build a PV '''
    pvtype: PVTypes
    description: str
    initial_value: Numeric
    units : str = ""
    format : Format = Format.DEFAULT
    precision : int = -1

    # Alarm: alarm = field(init=False)
    timestamp : Timestamp = field(init=False)
    display: Display = None
    control : Control = None
    alarm_limit : AlarmLimit = None

    read_only : bool = False

    def __post_init__(self):
        ''' Anything that isn't done by the automatically created __init__'''

        # Initialise the members that the default init doesn't cover
        # Specifically these are the ones tagged with field(init=False)
        self.timestamp = None


    def copy(self) -> "PVScalarRecipe":
        ''' Return a shallow copy of this instance '''
        return dataclasses.replace(self)

    def add_control_limits(self, low : Numeric, high : Numeric, min_step : Numeric = 0):
        ''' Add control limits '''
        match self.pvtype:
            case PVTypes.DOUBLE:
                self.control = Control[float](low, high, min_step)
            case PVTypes.INTEGER:
                self.control = Control[int](low, high, min_step)
            case PVTypes.STRING:
                raise SyntaxError('Control limits not supported on string PVs')
            case PVTypes.ENUM:
                raise SyntaxError('Control limits not supported on enum PVs')

    def add_display_limits(self, low_limit=None, high_limit=None):
        ''' Add display limits '''
        match self.pvtype:
            case PVTypes.DOUBLE: 
                if low_limit is None: low_limit = float('-inf')
                if high_limit is None: high_limit = float('inf')
                self.display = Display[float](limit_low=low_limit, limit_high=high_limit)
            case PVTypes.INTEGER:
                if low_limit is None: low_limit = -2147483648
                if high_limit is None: high_limit = 2147483647
                self.display = Display[float](limit_low=low_limit, limit_high=high_limit)
            case PVTypes.STRING:
                raise SyntaxError('Control limits not supported on string PVs')
            case PVTypes.ENUM:
                raise SyntaxError('Control limits not supported on enum PVs')
            

    def add_alarm_limits(self, low_warning=None, high_warning=None, low_alarm=None, high_alarm=None):
        ''' Add alarm limits '''
        match self.pvtype:
            case PVTypes.DOUBLE:
                if low_warning is None: low_warning = float('-inf')
                if high_warning is None: high_warning = float('inf')
                if low_alarm is None: low_alarm = float('-inf')
                if high_alarm is None: high_alarm = float('inf')
                self.alarm_limit = AlarmLimit[float](low_alarm_limit=low_alarm, low_warning_limit=low_warning, high_warning_limit=high_warning, high_alarm_limit=high_alarm)
            case PVTypes.INTEGER:
                if low_warning is None: low_warning = -2147483648
                if high_warning is None: high_warning = 2147483647
                if low_alarm is None: low_alarm = -2147483648
                if high_alarm is None: high_alarm = 2147483647
                self.alarm_limit = AlarmLimit[int](low_alarm_limit=low_alarm, low_warning_limit=low_warning, high_warning_limit=high_warning, high_alarm_limit=high_alarm)
            case PVTypes.STRING:
                raise SyntaxError('Control limits not supported on string PVs')
            case PVTypes.ENUM:
                raise SyntaxError('Control limits not supported on enum PVs')
        

    def create_pv(self) -> NTScalar | NTEnum:
        ''' Turn the recipe into an actual NTScalar, NTEnum, or 
        other BasePV derived object'''
        construct_settings = {}
        config_settings = {}

        construct_settings['valtype'] = self.pvtype.value
        construct_settings['extra'] = [('descriptor', 's')]
        config_settings['descriptor'] = self.description

        self._config_display(construct_settings, config_settings)

        if self.control:
            self._config_control(construct_settings, config_settings)

        if self.alarm_limit:
            self._config_alarm_limit(construct_settings, config_settings)

        handler = NTScalarRulesHandler()
        pvobj = SharedPV(nt=NTScalar(**construct_settings),
                        initial=self.initial_value,
                        timestamp=time.time(),
                        handler=handler)
        pvobj.post(config_settings)

        if self.read_only:
            handler._put_rules['read_only'] = lambda new,old: NTScalarRulesHandler.RulesFlow.ABORT
            handler._put_rules.move_to_end('read_only', last=False)

        # TODO: Need to handle the case where limits and alarms already apply!

        return pvobj

    def _config_display(self, construct_settings, config_settings):
        if self.units:
            construct_settings['display'] = True
            config_settings['display.description'] = self.description
            config_settings['display.units'] = self.units

        # Precision doesn't actually seem to be supported in Phoebus
        if self.precision != -1:
            construct_settings['display'] = True
            construct_settings['form'] = True
            config_settings['display.description'] = self.description
            config_settings['display.precision'] = self.precision

        if self.format != Format.DEFAULT:
            construct_settings['display'] = True
            config_settings['display.description'] = self.description
            if 'display.precision' not in config_settings:
                config_settings['display.format'] = self.format.value[1]
            else:
                construct_settings['form'] = True
                config_settings['display.form.index'] = self.format.value[0]
                config_settings['display.form.choices'] = ["Default", "String", "Binary", "Decimal", "Hex", "Exponential", "Engineering"]
     
        if self.display:
            construct_settings['display'] = True
            config_settings['display.description'] = self.description
            config_settings['display.limitLow'] = self.display.limit_low
            config_settings['display.limitHigh'] = self.display.limit_high


    def _config_alarm_limit(self, construct_settings, config_settings):
        construct_settings['valueAlarm'] = True
        config_settings['valueAlarm.active'] = self.alarm_limit.active
        config_settings['valueAlarm.lowAlarmLimit'] = self.alarm_limit.low_alarm_limit
        config_settings['valueAlarm.lowWarningLimit'] = self.alarm_limit.low_warning_limit
        config_settings['valueAlarm.highWarningLimit'] = self.alarm_limit.high_warning_limit
        config_settings['valueAlarm.highAlarmLimit'] = self.alarm_limit.high_alarm_limit
        config_settings['valueAlarm.lowAlarmSeverity'] = self.alarm_limit.low_alarm_severity.value
        config_settings['valueAlarm.lowWarningSeverity'] = self.alarm_limit.low_warning_severity.value
        config_settings['valueAlarm.highWarningSeverity'] = self.alarm_limit.high_warning_severity.value
        config_settings['valueAlarm.highAlarmSeverity'] = self.alarm_limit.high_alarm_severity.value
        config_settings['valueAlarm.hysteresis'] = self.alarm_limit.hysteresis

    def _config_control(self, construct_settings, config_settings):
        construct_settings['control'] = True
        config_settings['control.limitLow'] = self.control.limit_low
        config_settings['control.limitHigh'] = self.control.limit_high
        config_settings['control.minStep'] = self.control.min_step
