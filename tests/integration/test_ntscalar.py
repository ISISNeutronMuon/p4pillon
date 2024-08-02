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
    assert_correct_alarm_config,
    assert_correct_control_config,
    assert_correct_display_config,
    assert_value_changed,
    assert_pv_not_in_alarm_state,
    assert_pv_in_minor_alarm_state,
    assert_pv_in_major_alarm_state,
    assert_pv_in_invalid_alarm_state,
    assert_value_not_changed,
)

root_dir = Path(__file__).parents[2]

sys.path.append(str(root_dir))

from p4p_for_isis.server import ISISServer
from p4p_for_isis.definitions import PVTypes, AlarmSeverity

from p4p_for_isis.config_reader import parse_config
from p4p_for_isis.pvrecipe import PVScalarRecipe

with open(f"{root_dir}/tests/integration/ntscalar_config.yml", "r") as f:
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

    parse_config(f"{root_dir}/tests/integration/ntscalar_config.yml", server)

    server.start()
    return server


@pytest.fixture()
def server_under_test() -> ISISServer:
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
def ctx() -> Context:
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
    current_val = ctx.get(pvname).raw.todict()["value"]
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
def test_ntscalar_configs(pvname, server_under_test, pv_config, ctx):
    # NOTE by using pytest and parameterize here we run the test individually
    # per PV in the config file, helping us to identify which PVs are causing
    # problems (this would be much more difficult if we were iterating over
    # a list from within the same test)
    pvname = server_under_test.prefix + pvname

    pv_type = pv_config["type"]
    pv_is_numeric = pv_type in [PVTypes.DOUBLE.name, PVTypes.INTEGER.name]

    assert pvname in server_under_test.pvlist

    pv_state = ctx.get(pvname).raw.todict()
    # if we only provide a description with no other display fields, only
    # descriptor will be present but it should be in all PVs. Whereas when
    # any other field is specified like units etc the display.description
    # should also be configured
    assert pv_state.get("descriptor", "") == pv_config.get("description", "")

    if pv_is_numeric:
        if "display" in pv_config.keys():
            assert_correct_display_config(pv_state, pv_config)
        if "control" in pv_config.keys():
            assert_correct_control_config(pv_state, pv_config)
        if "valueAlarm" in pv_config.keys():
            assert_correct_alarm_config(pv_state, pv_config)

    else:
        assert pv_state.get("display") is None
        assert pv_state.get("control") is None
        assert pv_state.get("valueAlarm") is None


@pytest.mark.parametrize("pvname, pv_config", list(ntscalar_config.items()))
def test_ntscalar_value_change(pvname, server_under_test, pv_config, ctx):
    pvname = server_under_test.prefix + pvname
    put_val, put_timestamp = put_different_value(ctx, pvname)

    if not pv_config.get("read_only"):
        assert_value_changed(pvname, put_val, put_timestamp, ctx)
    else:
        assert_value_not_changed(pvname, put_val, put_timestamp, ctx)


class TestAlarms:
    """Integration test case for validating alarm limit behaviour on a variety
    of PV types"""

    @pytest.mark.parametrize("pvtype", [(PVTypes.DOUBLE), (PVTypes.INTEGER)])
    def test_ntscalar_basic_alarm_logic(self, ctx: Context, pvtype):
        # here we have an example of a pretty standard range alarm configuration
        pvname = "TEST:ALARM:PV"

        server = ISISServer(
            ioc_name="TESTIOC",
            section="controls testing",
            description="server for demonstrating Server use",
            prefix="TEST:",
        )

        alarm_config = {
            "low_alarm": -9,
            "low_warning": -4,
            "high_warning": 4,
            "high_alarm": 9,
        }
        pv_double1 = PVScalarRecipe(pvtype, "An example alarmed PV", 0)
        pv_double1.set_alarm_limits(**alarm_config)
        server.addPV(pvname, pv_double1)

        server.start()

        ctx.put(pvname, -10)
        assert_pv_in_major_alarm_state(pvname, ctx)
        ctx.put(pvname, -5)
        assert_pv_in_minor_alarm_state(pvname, ctx)
        ctx.put(pvname, 0)
        assert_pv_not_in_alarm_state(pvname, ctx)
        ctx.put(pvname, 5)
        assert_pv_in_minor_alarm_state(pvname, ctx)
        ctx.put(pvname, 10)
        assert_pv_in_major_alarm_state(pvname, ctx)

        server.stop()

    @pytest.mark.parametrize("pvtype", [(PVTypes.DOUBLE), (PVTypes.INTEGER)])
    def test_ntscalar_defaults_alarm_logic(self, ctx: Context, pvtype):
        # PVs that use the default values will never go into the alarm state
        pvname = "TEST:ALARM:PV"

        server = ISISServer(
            ioc_name="TESTIOC",
            section="controls testing",
            description="server for demonstrating Server use",
            prefix="TEST:",
        )

        alarm_config = {}
        pv_double1 = PVScalarRecipe(pvtype, "An example double PV", 0)
        pv_double1.set_alarm_limits(**alarm_config)
        server.addPV(pvname, pv_double1)

        server.start()

        for val in [-10, -5, 0, 5, 10]:
            ctx.put(pvname, val)
            assert_pv_not_in_alarm_state(pvname, ctx)

        server.stop()


class TestControl:
    """Integration test case for validating control limit behaviour on a variety
    of PV types"""

    @pytest.mark.parametrize("pvtype", [(PVTypes.DOUBLE), (PVTypes.INTEGER)])
    def test_ntscalar_basic_control_logic(self, ctx: Context, pvtype):
        # here we have an example of a pretty standard range alarm configuration
        pvname = "TEST:CONTROL:PV"

        server = ISISServer(
            ioc_name="TESTIOC",
            section="controls testing",
            description="server for demonstrating Server use",
            prefix="TEST:",
        )

        control_config = {"low": -10, "high": 10, "min_step": 1}
        pv_double1 = PVScalarRecipe(pvtype, "An example PV with control limits", 0)
        pv_double1.set_control_limits(**control_config)
        server.addPV(pvname, pv_double1)

        server.start()
        # TODO implement test logic here
        server.stop()
