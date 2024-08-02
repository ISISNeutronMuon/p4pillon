import logging
from typing import List, Tuple

import yaml

from p4p_for_isis.server import ISISServer

from .definitions import *
from .pvrecipe import BasePVRecipe, PVEnumRecipe, PVScalarArrayRecipe, PVScalarRecipe

logger = logging.getLogger(__name__)


def parse_config(filename: str, server: ISISServer = None) -> List[PVScalarRecipe]:
    """
    Parse a yaml file and return a list of PVScalarRecipe objects.
    Optionally add the pvs to a server if server != None
    """
    pvconfigs = read_config(filename)
    pvrecipes = []

    if server is not None:
        for pvconfig in pvconfigs.items():
            pvrecipes.append(process_config(pvconfig))
            server.addPV(pvconfig[0], pvrecipes[-1])
    else:
        for pvconfig in pvconfigs.items():
            pvrecipes.append(process_config(pvconfig))

    return pvrecipes


def read_config(filename: str) -> dict:
    pvconfigs = {}
    with open(filename) as f:
        pvconfigs = yaml.load(f, yaml.SafeLoader)

    return pvconfigs


def process_config(pvconfig: Tuple[str, dict]) -> BasePVRecipe:
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

    pvname = pvconfig[0]
    pvdetails = pvconfig[1]

    logger.debug(f"Processing configuration for pv {pvname}, config is {pvdetails}")

    # Check that type and description are specified, absence is a syntax error
    if "type" not in pvdetails:
        raise SyntaxError(f"'type' not specified in record {pvname}")
    if "description" not in pvdetails:
        raise SyntaxError(f"'description' not specified in record {pvname}")

    initial = pvdetails.get("initial")
    if not initial:
        type = pvdetails["type"]
        # If it's a number set it to 0, if it's a string make it empty
        # (This doesn't take into account syntax around arrays)
        # If it's something else an initial value needs to be supplied
        if type == "DOUBLE" or type == "INT":
            initial = 0
        elif type == "STRING":
            initial = ""
        else:
            raise SyntaxError(
                f"for PV {pvname} of type '{type}' an initial value must be supplied"
            )

    if isinstance(pvdetails["initial"], list):
        pvrecipe = PVScalarArrayRecipe(
            PVTypes[pvdetails["type"]], pvdetails["description"], initial
        )
    elif pvdetails["type"] == "ENUM":
        pvrecipe = PVEnumRecipe(
            PVTypes[pvdetails["type"]], pvdetails["description"], initial
        )
    else:
        pvrecipe = PVScalarRecipe(
            PVTypes[pvdetails["type"]], pvdetails["description"], initial
        )

    supported_configs = [("read_only", bool)]
    for config, config_type in supported_configs:
        # Process variables in the configuration that are attributes of the pvrecipe class
        tmpConfig = pvdetails.get(config)
        if tmpConfig is not None and isinstance(tmpConfig, config_type):
            setattr(pvrecipe, config, tmpConfig)

    if "control" in pvdetails:
        pvrecipe.set_control_limits(**get_field_config(pvdetails, "control"))
    if "display" in pvdetails:
        pvrecipe.set_display_limits(**get_field_config(pvdetails, "display"))
    if "valueAlarm" in pvdetails:
        pvrecipe.set_alarm_limits(**get_field_config(pvdetails, "valueAlarm"))

    return pvrecipe


def get_field_config(pvdetails: dict, field_name: str) -> dict:
    config = pvdetails.get(field_name)
    if config is None:
        config = {}
    return config
