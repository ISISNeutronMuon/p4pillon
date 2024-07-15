import logging 
import yaml
from typing import Tuple, List

from .pvrecipe import BasePVRecipe, PVScalarRecipe, PVScalarArrayRecipe, PVEnumRecipe
from .definitions import *
from p4p_for_isis.server import ISISServer

logger = logging.getLogger(__name__)

def parse_config(filename:str, server: ISISServer = None) -> List[PVScalarRecipe]:
    """
    Parse a yaml file and return a list of PVScalarRecipe objects. 
    Optionally add the pvs to a server if server != None
    """
    pvconfigs = get_config(filename)
    pvrecipes = []

    if server is not None:
        for pvconfig in pvconfigs.items():
            pvrecipes.append(process_config(pvconfig))
            server.addPV(pvconfig[0], pvrecipes[-1])
    else:    
        for pvconfig in pvconfigs.items():
            pvrecipes.append(process_config(pvconfig))

    return pvrecipes

def get_config(filename:str) -> dict:
    pvconfigs = {}
    with open(filename) as f:
        pvconfigs = yaml.load(f, yaml.SafeLoader)

    return pvconfigs

def process_config(pvconfig : Tuple[str, dict]) -> BasePVRecipe:
    """ 
    Process the configuration of a single PV and update pvrecipe accordingly.

    The configuration is a dictionary, currently constructed from a YAML file.
    An example:

        pvname:
           type: 'd'
           valueAlarm: False

    The returned values are in three parts:
        construct_settings - passed to the default constructor of SharedPV

        initial_value   - a value initial value if one has not been supplied, 
        SharedPV won't open() the PV unless this is provided

        config_settings - SharedPV only supports setting some values in the
        constructor, the rest need to be added in a later post()
    """

    pvname    = pvconfig[0]
    pvdetails = pvconfig[1]

    logger.debug(f"Processing configuration for pv {pvname}, config is {pvdetails}")
    
    # Check that type and description are specified, absence is a syntax error
    if 'type' not in pvdetails:
        raise SyntaxError(f"'type' not specified in record {pvname}")
    if 'description' not in pvdetails:
        raise SyntaxError(f"'description' not specified in record {pvname}")
    
    initial = pvdetails.get('initial')
    if not initial:
        type = pvdetails['type']
            # If it's a number set it to 0, if it's a string make it empty
            # (This doesn't take into account syntax around arrays)
            # If it's something else an initial value needs to be supplied
        if type == 'DOUBLE' or type == 'INT':
            initial = 0
        elif type=='STRING':
            initial = ""
        else:
            raise SyntaxError(f"for PV {pvname} of type '{type}' an initial value must be supplied")
    
    if pvdetails['type'].endswith('_ARR'):
        pvrecipe = PVScalarArrayRecipe(PVTypes[pvdetails['type']], pvdetails['description'], initial)
    elif pvdetails['type'] == 'ENUM':
        pvrecipe = PVEnumRecipe(PVTypes[pvdetails['type']], pvdetails['description'], initial)
    else:
        pvrecipe = PVScalarRecipe(PVTypes[pvdetails['type']], pvdetails['description'], initial)
    
    supported_configs = [('units',str), ('precision', int), ('format', str), ('read_only', bool)]
    for conf in supported_configs:
        tmpConfig = pvdetails.get(conf[0])
        if tmpConfig is not None and isinstance(tmpConfig, conf[1]):
            if conf[0] == 'format':
                setattr(pvrecipe, conf[0], Format[tmpConfig])
            else:
                setattr(pvrecipe, conf[0], tmpConfig)
    
    if 'control' in pvdetails:
        pvrecipe.set_control_limits(config=pvdetails['control'])
    if 'display' in pvdetails:
        pvrecipe.set_display_limits(config=pvdetails['display'])
    if 'valueAlarm' in pvdetails:
        pvrecipe.set_alarm_limits(config=pvdetails['valueAlarm'])
    
    return pvrecipe
