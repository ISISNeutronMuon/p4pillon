''' Example of simplifed interface for NTScalar creation '''
import dataclasses
import logging
import time

from dataclasses import dataclass, field
from typing import SupportsFloat as Numeric # Hack to type hint number types

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

@dataclass
class Control:
    ''' Set limits '''
    limit_low: float
    limit_high: float
    min_step: float


@dataclass
class PVScalarRecipe:
    ''' A description of how to build a PV '''
    type: PVTypes
    description: str
    initial_value: Numeric
    # Alarm: alarm = field(init=False)
    timestamp : Timestamp = field(init=False)
    # Display: display = field(init=False)
    control : Control = field(init=False)

    read_only : bool = field(init=False)

    def __post_init__(self):
        ''' Anything that isn't done by the automatically created __init__'''

        # Initialise the members that the default init doesn't cover
        # Specifically these are the ones tagged with field(init=False)
        self.timestamp = None
        self.control = None
        self.read_only = False

    def copy(self) -> "PVScalarRecipe":
        ''' Return a shallow copy of this instance '''
        return dataclasses.replace(self)

    def add_control_limits(self, low : Numeric, high : Numeric, min_step : Numeric = None): 
        ''' Add control limits '''
        self.control = Control(low, high, min_step)

    def create_pv(self) -> NTScalar | NTEnum:
        ''' Turn the recipe into an actual NTScalar, NTEnum, or 
        other BasePV derived object'''
        construct_settings = {}
        construct_settings['valtype'] = self.type.value
        construct_settings['display'] = True

        config_settings = {}
        config_settings['display.description'] = self.description

        if self.control:
            construct_settings['control'] = True
            config_settings['control.limitLow'] = self.control.limit_low
            config_settings['control.limitHigh'] = self.control.limit_high
            config_settings['control.minStep'] = 2#self.control.min_step

        handler = NTScalarRulesHandler()
        pvobj = SharedPV(nt=NTScalar(**construct_settings),
                        initial=self.initial_value,
                        timestamp=time.time(),
                        handler=handler)
        pvobj.post(config_settings)

        if self.read_only:
            handler._put_rules['read_only'] = lambda new,old: NTScalarRulesHandler.RulesFlow.ABORT
            handler._put_rules.move_to_end('read_only', last=False)

        return pvobj
