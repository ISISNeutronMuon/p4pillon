from unittest.mock import MagicMock

import numpy as np
import pytest

from p4pillon.definitions import PVTypes
from p4pillon.thread.config_reader import parse_config
from p4pillon.thread.pvrecipe import PVEnumRecipe, PVScalarArrayRecipe, PVScalarRecipe


@pytest.mark.parametrize(
    "name, config, pvtype",
    [
        ("TEST:PV:DOUBLE", {"initial": 0.0, "type": "DOUBLE"}, PVTypes.DOUBLE),
        ("TEST:PV:DOUBLE", {"initial": 17.0, "type": "DOUBLE"}, PVTypes.DOUBLE),
        ("TEST:PV:INTEGER", {"initial": 0, "type": "INTEGER"}, PVTypes.INTEGER),
        ("TEST:PV:DOUBLE", {"type": "DOUBLE"}, PVTypes.DOUBLE),
        ("TEST:PV:INTEGER", {"type": "INTEGER"}, PVTypes.INTEGER),
        ("TEST:PV:DOUBLE:ARRAY", {"type": "DOUBLE", "array_size": 3}, PVTypes.DOUBLE),
        ("TEST:PV:INTEGER:ARRAY", {"type": "INTEGER", "array_size": 3}, PVTypes.INTEGER),
    ],
)
def test_parse_config_with_server(name, config, pvtype):
    server = MagicMock()

    config["description"] = "test"

    recipes = parse_config({name: config}, server)
    assert len(recipes) == 1

    assert recipes[name].description == config["description"]
    assert recipes[name].pvtype == pvtype

    if config.get("array_size"):
        assert isinstance(recipes[name], PVScalarArrayRecipe)
        assert np.allclose(recipes[name].initial_value, np.array([0, 0, 0]))
    else:
        assert isinstance(recipes[name], PVScalarRecipe)
        assert recipes[name].initial_value == config.get("initial", 0.0)

    assert server.add_pv.call_args_list[0][0][0] == name


@pytest.mark.parametrize(
    "config, error_msg",
    [
        ({"description": "test"}, "'type' not specified"),
        ({"type": PVTypes.DOUBLE}, "'description' not specified"),
    ],
)
def test_parse_config_syntax_errors(config, error_msg):
    with pytest.raises(SyntaxError) as e:
        parse_config({"TEST:PV": config})
    assert error_msg in str(e)


@pytest.mark.parametrize(
    "name, config, pvtype",
    [
        ("TEST:PV:ENUM", {"initial": {"index": 0, "choices": ["False", "True"]}, "type": "ENUM"}, PVTypes.ENUM),
        ("TEST:PV:ENUM", {"initial": {"index": 1, "choices": ["OFF", "ON"]}, "type": "ENUM"}, PVTypes.ENUM),
    ],
)
def test_parse_config_with_server_enum(name, config, pvtype):
    server = MagicMock()

    config["description"] = "test"

    recipes = parse_config({name: config}, server)
    assert len(recipes) == 1

    assert isinstance(recipes[name], PVEnumRecipe)
    assert recipes[name].description == config["description"]
    assert recipes[name].pvtype == pvtype

    assert server.add_pv.call_args_list[0][0][1].initial_value == config["initial"]
    assert isinstance(server.add_pv.call_args_list[0][0][1], PVEnumRecipe)
    assert server.add_pv.call_args_list[0][0][0] == name
