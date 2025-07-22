from pathlib import Path

import pytest
import yaml
from p4p.client.thread import Context

from p4p_ext.thread.config_reader import parse_config
from p4p_ext.thread.server import SimpleServer

root_dir = Path(__file__).parents[2]


@pytest.fixture
def ntscalar_config():
    with open(f"{root_dir}/integration/ntscalar_config.yml") as f:
        ntscalar_dict = yaml.load(f, Loader=yaml.SafeLoader)
        f.close()
    return ntscalar_dict


@pytest.fixture()
def basic_server() -> SimpleServer:
    server = SimpleServer(
        prefix="TEST:",
    )
    yield server
    server.stop()


@pytest.fixture()
def ctx() -> Context:
    client_context = Context("pva")
    yield client_context
    client_context.close()


def start_server(ntscalar_config: dict):
    # NOTE this will be replaced by a more universal `parse_yaml` function or equivalent
    server = SimpleServer(
        prefix="TEST:",
    )

    parse_config(ntscalar_config, server)

    server.start()
    return server


@pytest.fixture()
def server_from_yaml() -> SimpleServer:
    """fixture that handles creation and desctruction of server for use during tests"""
    # NOTE this could be tidied up by moving the tests into classes and using
    # setupclass and teardownclass methods as suggested here:
    # https://docs.pytest.org/en/latest/how-to/xunit_setup.html
    # NOTE also that this fixture has to be used as a parameter in every test
    # for the server to actually run
    with open(f"{root_dir}/integration/ntscalar_config.yml") as f:
        ntscalar_dict = yaml.load(f, Loader=yaml.SafeLoader)
        f.close()

    server = start_server(ntscalar_dict)
    yield server
    server.stop()
