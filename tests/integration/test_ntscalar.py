"""
Integration tests for expected behaviour of NTScalar PV types:
- [ ] creation / modification (values, descriptions, limits)
- [ ] alarm handling
- [ ] control handling
- [ ] calc records
- [ ] forward linking records
"""

import sys
import time
from pathlib import Path

import pytest
import yaml
from p4p.client.thread import Context

from assertions import (
    assert_alarm_present,
    assert_correct_alarm_config,
    assert_correct_control_config,
    assert_correct_display_config,
    assert_value_changed,
    assert_value_not_changed,
)

root_dir = Path(__file__).parents[2]

sys.path.append(str(root_dir))

from p4p_for_isis import definitions
from p4p_for_isis.pvrecipe import PVScalarRecipe
from p4p_for_isis.server import ISISServer
from p4p_for_isis.definitions import PVTypes

with open("ntscalar_config.yml", "r") as f:
    ntscalar_config = yaml.load(f, Loader=yaml.SafeLoader)
    f.close()


def start_server(ntscalar_config):
    # NOTE this will be replaced by a more universal `parse_yaml` function or equivalent
    server = ISISServer(
        ioc_name="TESTIOC",
        section="controls testing",
        description="server for demonstrating Server use",
        prefix="TEST:",
    )

    for pvname, config in ntscalar_config.items():
        pv_double = PVScalarRecipe(
            definitions.PVTypes.DOUBLE, config["description"], config["initial"]
        )
        server.addPV(pvname, pv_double)

    server.start()
    return server


@pytest.fixture()
def test_server():
    """fixture that handles creation and desctruction of server for use during tests"""
    # NOTE this could be tidied up by moving the tests into classes and using
    # setupclass and teardownclass methods as suggested here:
    # https://docs.pytest.org/en/latest/how-to/xunit_setup.html
    # NOTE also that this fixture has to be used as a parameter in every test
    # for the server to actually run
    server = start_server(ntscalar_config)
    yield server
    server.stop()


@pytest.fixture()
def ctx():
    client_context = Context("pva")
    yield client_context
    client_context.close()


def put_different_value(ctx: Context, pvname: str):
    """
    Change the value of a process variable (PV) to ensure it is different from its current value.

    Parameters:
    -----------
    ctx : Context
        The context object that provides methods to get and put the value of the PV.
    pvname : str
        The name of the PV whose value is to be changed.

    Returns:
    --------
    tuple
        A tuple containing the new value of the PV and the Unix timestamp when the update was made.

    Example:
    --------
    >>> ctx = Context()
    >>> pvname = "temperature_sensor_1"
    >>> new_value, timestamp = put_different_value(ctx, pvname)
    >>> print(f"New value: {new_value}, Updated at: {timestamp}")
    """
    current_val = ctx.get(pvname).real
    if isinstance(current_val, str):
        put_val = current_val + "1"
    else:
        put_val = current_val + 1
    put_timestamp = time.time()
    ctx.put(pvname, put_val)
    return put_val, put_timestamp


def put_metadata(ctx: Context, pvname: str, field: str, value):
    """
    Update the metadata of a process variable in the given context and return the timestamp of the update.

    Parameters:
    -----------
    ctx : Context
        The context object that provides the method to update the PV.
    pvname : str
        The name of the PV whose metadata is to be updated.
    field : str
        The specific metadata field that needs to be updated. For subfields use dot notation e.g. valueAlarm.highAlarmLimit
    value
        The value to set for the specified metadata field. The type of this value can vary based on the field.

    Returns:
    --------
    float
        The Unix timestamp when the metadata was updated.

    Example:
    --------
    >>> ctx = Context()
    >>> pvname = "temperature_sensor_1"
    >>> field = "display.units"
    >>> value = "Celsius"
    >>> timestamp = put_metadata(ctx, pvname, field, value)
    >>> print(f"Metadata updated at {timestamp}")
    """
    put_timestamp = time.time()
    ctx.put(
        pvname,
        {field: value},
    )
    return put_timestamp


@pytest.mark.parametrize("pvname, pv_config", list(ntscalar_config.items()))
def test_ntscalar_configs(pvname, test_server, pv_config, ctx):
    # NOTE by using pytest and parameterize here we run the test individually
    # per PV in the config file, helping us to identify which PVs are causing
    # problems (this would be much more difficult if we were iterating over
    # a list from within the same test)

    pv_type = pv_config["type"]
    pv_is_numeric = pv_type in [PVTypes.DOUBLE.value, PVTypes.INTEGER.value]

    assert pvname in test_server.pvlist

    # check that the PV is configured correctly and has all the expected NTScalar
    # fields
    assert_alarm_present(ctx, pvname)
    assert_correct_display_config(
        ctx, pvname, pv_config.get("display"), numeric=pv_is_numeric
    )
    if pv_is_numeric:
        # check for valueAlarm and control fields
        assert_correct_alarm_config(ctx, pvname, pv_config.get("alarm"))
        assert_correct_control_config(ctx, pvname, pv_config.get("control"))


@pytest.mark.parametrize("pvname, pv_config", list(ntscalar_config.items()))
def test_ntscalar_value_change(pvname, test_server, pv_config, ctx):
    put_val, put_timestamp = put_different_value(ctx, pvname)
    if not pv_config["read-only"]:
        assert_value_changed(pvname, put_val, put_timestamp, ctx)
    else:
        assert_value_not_changed(pvname, put_val, put_timestamp, ctx)


@pytest.mark.parametrize("pvname, pv_config", list(ntscalar_config.items()))
def test_ntscalar_alarm_logic(pvname, test_server, pv_config, ctx):
    # TODO check alarm logic on relevant PVs e.g. putting a value in different
    # states triggers the correct logic to be applied
    pass


@pytest.mark.parametrize("pvname, pv_config", list(ntscalar_config.items()))
def test_ntscalar_control_logic(pvname, test_server, pv_config, ctx):
    # TODO check control logic on relevant PVs e.g. trying to put a value above
    # the limit will prevent it being applied
    pass
