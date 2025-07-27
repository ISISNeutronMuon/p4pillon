from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_recipe():
    pv = MagicMock()
    return pv


@pytest.fixture
def mock_server_op():
    with patch("p4p_ext.handlers.ServerOperation", autospec=True) as server_op:
        yield server_op


@pytest.fixture
def mock_server():
    with patch("p4p_ext.server.Server", autospec=True) as server:
        yield server


@pytest.fixture
def mock_pv():
    with patch("p4p.server.thread.SharedPV", autospec=True) as shared_pv:
        yield shared_pv


@pytest.fixture
def mock_isispv():
    with patch("p4p.server.thread.SharedPV", autospec=True) as shared_pv:
        yield shared_pv


@pytest.fixture
def mock_provider():
    with patch("p4p.server.StaticProvider", autospec=True) as provider:
        yield provider
