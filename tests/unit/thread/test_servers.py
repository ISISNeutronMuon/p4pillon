from pathlib import Path

import pytest
from p4p.nt import NTScalar
from p4p.server import StaticProvider

from p4pillon.thread.pvrecipe import BasePVRecipe
from p4pillon.thread.server import Server
from p4pillon.thread.sharednt import SharedNT

root_dir = Path(__file__).parents[2]


def test_server_instantiation():
    server = Server(
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
def test_server_retrieve_pvs(mock_recipe: BasePVRecipe, pv_name):
    server = Server(
        prefix="DEV:",
    )
    server.add_pv(pv_name, mock_recipe.create_pv.return_value)

    # we should be able to access the PV either with the full prefix added or without it
    assert server["TEST:PV"] == mock_recipe.create_pv.return_value
    assert server["DEV:TEST:PV"] == mock_recipe.create_pv.return_value


def test_server_start():
    test_server = Server(
        prefix="DEV:",
    )

    pv = SharedNT(
        nt=NTScalar(
            "d",
            valueAlarm=True,
        ),  # scalar double
        initial={"value": 4.5, "valueAlarm.active": True, "valueAlarm.highAlarmLimit": 17},
    )

    test_server._pvs = {"DEV:TEST:PV:1": pv}
    pv = SharedNT(
        nt=NTScalar(
            "d",
            valueAlarm=True,
        ),  # scalar double
        initial={"value": 4.5, "valueAlarm.active": True, "valueAlarm.highAlarmLimit": 17},
    )

    test_server._pvs = {"DEV:TEST:PV:1": pv}

    assert test_server._running is False

    test_server.start()
    assert test_server._running is True
    assert len(test_server._pvs) == 1
    assert list(test_server._pvs)[0] == "DEV:TEST:PV:1"


def test_server_stop():
    test_server = Server(
        prefix="DEV:",
    )

    test_server.start()
    assert test_server._running is True

    test_server.stop()
    assert test_server._running is False


def test_server_remove_pv():
    test_server = Server(
        prefix="DEV:",
    )

    pv = SharedNT(
        nt=NTScalar(
            "d",
            valueAlarm=True,
        ),  # scalar double
        initial={"value": 4.5, "valueAlarm.active": True, "valueAlarm.highAlarmLimit": 17},
    )

    test_server._pvs = {"DEV:TEST:PV:1": pv}

    test_server.start()
    assert len(test_server._pvs) == 1
    assert list(test_server._pvs)[0] == "DEV:TEST:PV:1"
    test_server.remove_pv("DEV:TEST:PV:1")
    assert len(test_server._pvs) == 0
    assert test_server._pvs.get("DEV:TEST:PV:1") is None
