from pathlib import Path

import pytest
import yaml
from p4p.client.thread import Context

from p4p_for_isis.config_reader import parse_config
from p4p_for_isis.server import ISISServer

root_dir = Path(__file__).parents[2]


@pytest.fixture
def ntscalar_config():
    with open(f"{root_dir}/tests/integration/ntscalar_config.yml", "r") as f:
        ntscalar_dict = yaml.load(f, Loader=yaml.SafeLoader)
        f.close()
    return ntscalar_dict


@pytest.fixture()
def basic_server() -> ISISServer:
    server = ISISServer(
        ioc_name="TESTIOC",
        section="controls testing",
        description="server for demonstrating Server use",
        prefix="TEST:",
    )
    yield server
    server.stop()


@pytest.fixture()
def ctx() -> Context:
    client_context = Context("pva")
    yield client_context
    client_context.close()


def start_server():
    # NOTE this will be replaced by a more universal `parse_yaml` function or equivalent
    server = ISISServer(
        ioc_name="TESTIOC",
        section="controls testing",
        description="server for demonstrating Server use",
        prefix="TEST:",
    )

    parse_config(f"{root_dir}/tests/integration/ntscalar_config.yml", server)

    server.start()
    return server


@pytest.fixture()
def server_from_yaml() -> ISISServer:
    """fixture that handles creation and desctruction of server for use during tests"""
    # NOTE this could be tidied up by moving the tests into classes and using
    # setupclass and teardownclass methods as suggested here:
    # https://docs.pytest.org/en/latest/how-to/xunit_setup.html
    # NOTE also that this fixture has to be used as a parameter in every test
    # for the server to actually run
    server = start_server()
    yield server
    server.stop()
