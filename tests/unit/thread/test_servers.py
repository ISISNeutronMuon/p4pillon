import logging
from pathlib import Path
from unittest.mock import patch

import pytest
from p4p.server import StaticProvider

from p4pillon.thread.server import SimpleServer

root_dir = Path(__file__).parents[2]


def test_server_instantiation():
    server = SimpleServer(
        prefix="DEV:",
    )
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
    server = SimpleServer(
        prefix="DEV:",
    )
    server.add_pv(pv_name, mock_recipe)

    # we should be able to access the PV either with the full prefix added or without it
    assert server["TEST:PV"] == mock_recipe.create_pv.return_value
    assert server["DEV:TEST:PV"] == mock_recipe.create_pv.return_value


@patch("p4pillon.thread.server.StaticProvider", autospec=True)
@patch("p4pillon.thread.server.Server", autospec=True)
def test_server_start(server, provider, caplog, mock_ntpv):
    test_server = SimpleServer(
        prefix="DEV:",
    )

    mock_ntpv.on_start_methods = []
    test_server._pvs = {"DEV:TEST:PV:1": mock_ntpv}
    print(len(mock_ntpv.on_start_methods))

    assert test_server._running is False
    with caplog.at_level(logging.DEBUG):
        test_server.start()
    assert len(caplog.records) == 1
    provider.return_value.add.assert_called_once_with("DEV:TEST:PV:1", mock_ntpv)
    server.assert_called_once_with(providers=[provider.return_value])
    assert test_server._running is True


@patch("p4pillon.thread.server.StaticProvider", autospec=True)
@patch("p4pillon.thread.server.Server", autospec=True)
@patch("p4pillon.pvrecipe.PVScalarRecipe", autospec=True)
def test_server_add_pv(recipe, server, provider, caplog):
    test_server = SimpleServer(
        prefix="DEV:",
    )

    test_server.start()

    with caplog.at_level(logging.DEBUG):
        new_name = "TEST:PV:2"
        test_server.add_pv(new_name, recipe.return_value)
    assert test_server["TEST:PV:2"] is recipe.return_value.create_pv.return_value
    provider.return_value.add.assert_called_once_with("DEV:TEST:PV:2", recipe.return_value.create_pv.return_value)

    assert len(caplog.messages) == 1
    assert caplog.messages[0] == "Added DEV:TEST:PV:2 to server"


@patch("p4pillon.thread.server.StaticProvider", autospec=True)
@patch("p4pillon.thread.server.Server", autospec=True)
def test_server_stop(server, provider, caplog, mock_ntpv):
    test_server = SimpleServer(
        prefix="DEV:",
    )

    test_server._running = True
    test_server._server = server.return_value
    test_server._pvs = {"DEV:TEST:PV:1": mock_ntpv}

    with caplog.at_level(logging.DEBUG):
        test_server.stop()

    mock_ntpv.close.assert_called_once_with()
    provider.return_value.remove.assert_called_once_with("DEV:TEST:PV:1")
    server.return_value.stop.assert_called_once_with()
    assert test_server._running is False


@patch("p4pillon.thread.server.StaticProvider", autospec=True)
@patch("p4pillon.thread.server.Server", autospec=True)
@patch("p4pillon.pvrecipe.PVScalarRecipe", autospec=True)
def test_server_remove_pv(recipe, server, provider, caplog, mock_ntpv):
    test_server = SimpleServer(
        prefix="DEV:",
    )

    test_server._pvs["DEV:TEST:PV:1"] = mock_ntpv
    test_server._running = True
    test_server._server = server.return_value

    with caplog.at_level(logging.DEBUG):
        test_server.remove_pv("TEST:PV:1")

    mock_ntpv.close.assert_called_once_with()
    provider.return_value.remove.assert_called_once_with("DEV:TEST:PV:1")

    assert test_server._pvs.get("DEV:TEST:PV:1") is None

    assert len(caplog.messages) == 1
    assert caplog.messages[0] == "Removed DEV:TEST:PV:1 from server"
