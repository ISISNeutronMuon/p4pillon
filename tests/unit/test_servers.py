import pytest
from p4p.server import StaticProvider
import os


import sys
from pathlib import Path

root_dir = Path(__file__).parents[2]

sys.path.append(str(root_dir))
from p4p_for_isis.server import ISISServer


def test_server_instantiation():
    server = ISISServer(
        ioc_name="TESTIOC",
        section="controls testing",
        description="server for unit tests",
        prefix="DEV:",
    )
    assert server.ioc_name == "TESTIOC"
    assert server.section == "controls testing"
    assert server.description == "server for unit tests"
    assert server.prefix == "DEV:"

    # before we explicitly call `start()`, the server shouldn't exist
    assert server._server is None
    assert isinstance(server._provider, StaticProvider)
    # and we also shouldn't have any PVs configured
    assert server.pvlist == []


@pytest.mark.parametrize(
    "pv_name",
    [("TEST:PV"), ("DEV:TEST:PV")],
)
def test_server_retrieve_pvs(mock_recipe, pv_name):
    server = ISISServer(
        ioc_name="TESTIOC",
        section="controls testing",
        description="server for unit tests",
        prefix="DEV:",
    )
    server.addPV(pv_name, mock_recipe)

    # we should be able to access the PV either with the full prefix added or without it
    assert server["TEST:PV"] == mock_recipe.create_pv.return_value
    assert server["DEV:TEST:PV"] == mock_recipe.create_pv.return_value
