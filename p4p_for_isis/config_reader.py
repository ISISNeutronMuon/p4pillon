"""Read configuration from a YAML file"""

import logging
from typing import Dict, Union

import yaml

from .definitions import PVTypes
from .pvrecipe import BasePVRecipe, PVEnumRecipe, PVScalarArrayRecipe, PVScalarRecipe
from .server import ISISServer

logger = logging.getLogger(__name__)


def parse_config_file(filename: str, server: Union[ISISServer, None] = None) -> Dict[str, BasePVRecipe]:
    """
    Parse a yaml file and return a dictionary of PVScalarRecipe objects.
    Optionally add the pvs to a server if server != None
    """
    pvconfigs = {}
    with open(filename, encoding="utf8") as f:
        pvconfigs = yaml.load(f, yaml.SafeLoader)

    return parse_config(pvconfigs, server)


def parse_config_string(yamlStr: str, server: Union[ISISServer, None] = None) -> Dict[str, BasePVRecipe]:
    """
    Parse a yaml string and return a dictionary of PVScalarRecipe objects.
    Optionally add the pvs to a server if server != None
    """
    pvconfigs = {}
    pvconfigs = yaml.load(yamlStr, yaml.SafeLoader)

    return parse_config(pvconfigs, server)


def parse_config(yamlObj: dict, server: Union[ISISServer, None] = None) -> Dict[str, BasePVRecipe]:
    """
    Parse a dictionary that has been filled using yaml.load() and return a dictionary of PVScalarRecipe objects.
    Optionally add the pvs to a server if server != None
    """

    pvrecipes = {}

    logger.debug("Processing yaml: \n%r", yamlObj)

    for name, config in yamlObj.items():
        recipe = process_config(name, config)
        pvrecipes[name] = recipe

        if server is not None:
            server.add_pv(name, recipe)

    return pvrecipes


def process_config(pvname: str, pvdetails: dict) -> BasePVRecipe:
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

    logger.debug("Processing configuration for pv %s, config is %r", pvname, pvdetails)

    # Check that type and description are specified, absence is a syntax error
    if "type" not in pvdetails:
        raise SyntaxError(f"'type' not specified in record {pvname}")
    if "description" not in pvdetails:
        raise SyntaxError(f"'description' not specified in record {pvname}")

    initial = pvdetails.get("initial")
    array_size = pvdetails.get("array_size", 1)
    pvtype = pvdetails["type"]
    if not initial:
        # If it's a number set it to 0, if it's a string make it empty
        # If it's something else an initial value needs to be supplied
        if pvtype == "DOUBLE" or pvtype == "INTEGER":
            if array_size > 1:
                initial = [0] * array_size
            else:
                initial = 0
        elif pvtype == "STRING":
            if array_size > 1:
                initial = [""] * array_size
            else:
                initial = ""
        else:
            raise SyntaxError(f"for PV {pvname} of type '{pvtype}' an initial value must be supplied")

    if isinstance(initial, list):
        pvrecipe = PVScalarArrayRecipe(PVTypes[pvdetails["type"]], pvdetails["description"], initial)
    elif pvtype == "ENUM":
        pvrecipe = PVEnumRecipe(PVTypes[pvdetails["type"]], pvdetails["description"], initial)
    else:
        pvrecipe = PVScalarRecipe(PVTypes[pvdetails["type"]], pvdetails["description"], initial)

    supported_configs = [("read_only", bool), ("calc", dict)]
    for config, config_type in supported_configs:
        # Process variables in the configuration that are attributes of the pvrecipe class
        temp_config = pvdetails.get(config)
        if temp_config is not None and isinstance(temp_config, config_type):
            setattr(pvrecipe, config, temp_config)

    if "control" in pvdetails:
        pvrecipe.set_control_limits(**get_field_config(pvdetails, "control"))
    if "display" in pvdetails:
        pvrecipe.set_display_limits(**get_field_config(pvdetails, "display"))
    if "valueAlarm" in pvdetails:
        pvrecipe.set_alarm_limits(**get_field_config(pvdetails, "valueAlarm"))
    if "forward_links" in pvdetails:
        pvrecipe.set_forward_links(**get_field_config(pvdetails, "forward_links"))

    return pvrecipe


def get_field_config(pvdetails: dict, field_name: str) -> dict:
    """Get a specified field from the configuration"""
    config = pvdetails.get(field_name)
    if config is None:
        config = {}
    return config
