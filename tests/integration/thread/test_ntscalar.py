"""
Integration tests for expected behaviour of NTScalar PV types:
- [x] creation / modification (values, descriptions, limits)
- [x] alarm handling
- [x] control handling
- [ ] calc records
- [ ] forward linking records
"""

import time
from pathlib import Path

import pytest
import yaml
from helpers import put_different_value_scalar, put_metadata
from p4p._p4p import RemoteError
from p4p.client.thread import Context

from p4pillon.definitions import PVTypes
from p4pillon.thread.pvrecipe import PVScalarArrayRecipe, PVScalarRecipe
from p4pillon.thread.server import SimpleServer
from tests.integration.thread.assertions import (
    assert_correct_alarm_config,
    assert_correct_control_config,
    assert_correct_display_config,
    assert_pv_in_major_alarm_state,
    assert_pv_in_minor_alarm_state,
    assert_pv_not_in_alarm_state,
    assert_value_changed,
    assert_value_not_changed,
)

root_dir = Path(__file__).parents[2]


with open(f"{root_dir}/integration/ntscalar_config.yml") as f:
    ntscalar_config = yaml.load(f, Loader=yaml.SafeLoader)
    f.close()


@pytest.mark.parametrize("pvname, pv_config", list(ntscalar_config.items()))
def test_configs(pvname, yaml_server, pv_config, ctx):
    # NOTE by using pytest and parameterize here we run the test individually
    # per PV in the config file, helping us to identify which PVs are causing
    # problems (this would be much more difficult if we were iterating over
    # a list from within the same test)
    pvname = yaml_server.prefix + pvname

    pv_type = pv_config["type"]
    pv_is_numeric = pv_type in [PVTypes.DOUBLE.name, PVTypes.INTEGER.name]

    assert pvname in yaml_server.pvlist

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
def test_value_change(pvname, yaml_server, pv_config, ctx):
    pvname = yaml_server.prefix + pvname

    current_state = ctx.get(pvname)

    if not pv_config.get("read_only"):
        put_val, put_timestamp = put_different_value_scalar(ctx, pvname)
        assert_value_changed(pvname, put_val, put_timestamp, ctx)
    else:
        with pytest.raises(RemoteError) as e:
            put_different_value_scalar(ctx, pvname)

        assert "read-only" in str(e)
        pvstate = ctx.get(pvname)

        assert pvstate.timestamp == current_state.timestamp
        assert pvstate == current_state


@pytest.mark.parametrize("pvname, pv_config", list(ntscalar_config.items()))
def test_field_change(pvname, yaml_server, pv_config, ctx):
    pvname = yaml_server.prefix + pvname

    current_state = ctx.get(pvname)

    current_description = current_state.raw.todict().get("descriptor")
    new_description = current_description + " modified"

    if not isinstance(pv_config.get("initial"), list):
        if not pv_config.get("read_only"):
            put_timestamp = put_metadata(ctx, pvname, "descriptor", new_description)
            pvstate = ctx.get(pvname)

            assert pvstate.raw.todict().get("descriptor") == new_description
            assert pvstate.timestamp >= put_timestamp
        else:
            with pytest.raises(RemoteError) as e:
                put_metadata(ctx, pvname, "descriptor", new_description)
            assert "read-only" in str(e)
            pvstate = ctx.get(pvname)
            assert pvstate.timestamp == current_state.timestamp
            assert pvstate.raw.todict().get("descriptor") == current_description
    else:
        pytest.xfail(reason="Currently unable to change fields in NTScalarArrays")


def test_alarm_limit_change_readonly(basic_server, ctx):
    # for each PV that is alarmed, we change the upper alarm limit on the PV
    # and check if setting the value to something above/below that triggers
    # the correct alarm state
    pvname = "TEST:ALARM:LIMIT:PV"

    alarm_config = {
        "low_alarm": -9,
        "low_warning": -4,
        "high_warning": 4,
        "high_alarm": 9,
    }
    pv_double1 = PVScalarRecipe(PVTypes.DOUBLE, "An example alarmed PV", 0)
    pv_double1.set_alarm_limits(**alarm_config)
    basic_server.add_pv(pvname, pv_double1)

    # TODO: This is a very messy way of making a rule not read_only!
    basic_server[pvname]._handler["alarm_limit"].read_only = True

    basic_server.start()

    ctx.put(pvname, -5)
    assert_pv_in_minor_alarm_state(pvname, ctx)

    put_metadata(ctx, pvname, "valueAlarm.lowWarningLimit", -6)
    assert_pv_in_minor_alarm_state(pvname, ctx)

    ctx.put(pvname, -10)
    assert_pv_in_major_alarm_state(pvname, ctx)

    put_metadata(ctx, pvname, "valueAlarm.lowAlarmLimit", -11)
    assert_pv_in_major_alarm_state(pvname, ctx)


def test_alarm_limit_change(basic_server, ctx):
    # for each PV that is alarmed, we change the upper alarm limit on the PV
    # and check if setting the value to something above/below that triggers
    # the correct alarm state
    pvname = "TEST:ALARM:LIMIT:PV"

    alarm_config = {
        "low_alarm": -9,
        "low_warning": -4,
        "high_warning": 4,
        "high_alarm": 9,
    }
    pv_double1 = PVScalarRecipe(PVTypes.DOUBLE, "An example alarmed PV", 0)
    pv_double1.set_alarm_limits(**alarm_config)
    basic_server.add_pv(pvname, pv_double1)

    # TODO: This is a very messy way of making a rule not read_only!
    basic_server[pvname]._handler["alarm_limit"].read_only = False

    basic_server.start()

    ctx.put(pvname, -5)
    assert_pv_in_minor_alarm_state(pvname, ctx)

    put_metadata(ctx, pvname, "valueAlarm.lowWarningLimit", -6)
    assert_pv_not_in_alarm_state(pvname, ctx)

    ctx.put(pvname, -10)
    assert_pv_in_major_alarm_state(pvname, ctx)

    put_metadata(ctx, pvname, "valueAlarm.lowAlarmLimit", -11)
    assert_pv_in_minor_alarm_state(pvname, ctx)


class TestAlarms:
    """Integration test case for validating alarm limit behaviour on a variety
    of PV types"""

    @pytest.mark.parametrize("pvtype", [(PVTypes.DOUBLE), (PVTypes.INTEGER)])
    def test_basic_alarm_logic(self, basic_server: SimpleServer, ctx: Context, pvtype):
        # here we have an example of a pretty standard range alarm configuration
        pvname = "TEST:ALARM:PV"

        alarm_config = {
            "low_alarm": -9,
            "low_warning": -4,
            "high_warning": 4,
            "high_alarm": 9,
        }
        pv_double1 = PVScalarRecipe(pvtype, "An example alarmed PV", 0)
        pv_double1.set_alarm_limits(**alarm_config)
        basic_server.add_pv(pvname, pv_double1)

        basic_server.start()

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

    @pytest.mark.parametrize("pvtype", [(PVTypes.DOUBLE), (PVTypes.INTEGER)])
    def test_defaults_alarm_logic(self, basic_server, ctx: Context, pvtype):
        # PVs that use the default values will never go into the alarm state
        pvname = "TEST:ALARM:PV"

        pv_double1 = PVScalarRecipe(pvtype, "An example numeric alarmed PV", 0)
        pv_double1.set_alarm_limits()
        basic_server.add_pv(pvname, pv_double1)

        basic_server.start()

        for val in [-10, -5, 0, 5, 10]:
            ctx.put(pvname, val)
            assert_pv_not_in_alarm_state(pvname, ctx)

    @pytest.mark.parametrize("pvtype", [(PVTypes.DOUBLE), (PVTypes.INTEGER)])
    def test_only_high_alarm(self, basic_server, ctx: Context, pvtype: PVTypes):
        # PVs that use the default values will never go into the alarm state
        pvname = "TEST:ALARM:PV"

        pv_double1 = PVScalarRecipe(pvtype, "An example numeric alarmed PV", 0)
        pv_double1.set_alarm_limits(high_alarm=9)
        basic_server.add_pv(pvname, pv_double1)

        basic_server.start()

        for val in [-10, -5, 0, 5, 9, 10]:
            ctx.put(pvname, val)
            if val < 9:
                assert_pv_not_in_alarm_state(pvname, ctx)
            else:
                assert_pv_in_major_alarm_state(pvname, ctx)

    @pytest.mark.parametrize("pvtype", [(PVTypes.DOUBLE), (PVTypes.INTEGER)])
    def test_basic_alarm_logic_array_vals(self, basic_server: SimpleServer, ctx: Context, pvtype):
        # here we have an example of a pretty standard range alarm configuration but on
        # an array PV. In this case we expect the alarm to be triggered if ANY of the
        # values in the list exceed these values

        pvname = "TEST:ALARM:PV"

        alarm_config = {
            "low_alarm": -9,
            "low_warning": -4,
            "high_warning": 4,
            "high_alarm": 9,
        }
        pv_double1 = PVScalarArrayRecipe(pvtype, "An example alarmed PV", [0])
        pv_double1.set_alarm_limits(**alarm_config)
        basic_server.add_pv(pvname, pv_double1)

        basic_server.start()

        test_list = [0] * 5

        # At start
        ctx.put(pvname, [-10] + test_list)
        assert_pv_in_major_alarm_state(pvname, ctx)
        ctx.put(pvname, [-5] + test_list)
        assert_pv_in_minor_alarm_state(pvname, ctx)
        ctx.put(pvname, [0] + test_list)
        assert_pv_not_in_alarm_state(pvname, ctx)
        ctx.put(pvname, [5] + test_list)
        assert_pv_in_minor_alarm_state(pvname, ctx)
        ctx.put(pvname, [10] + test_list)
        assert_pv_in_major_alarm_state(pvname, ctx)

        # At end
        ctx.put(pvname, test_list + [-10])
        assert_pv_in_major_alarm_state(pvname, ctx)
        ctx.put(pvname, test_list + [-5])
        assert_pv_in_minor_alarm_state(pvname, ctx)
        ctx.put(pvname, test_list + [0])
        assert_pv_not_in_alarm_state(pvname, ctx)
        ctx.put(pvname, test_list + [5])
        assert_pv_in_minor_alarm_state(pvname, ctx)
        ctx.put(pvname, test_list + [10])
        assert_pv_in_major_alarm_state(pvname, ctx)

    @pytest.mark.parametrize("pvtype", [(PVTypes.DOUBLE), (PVTypes.INTEGER)])
    def test_defaults_alarm_logic_arrays(self, basic_server, ctx: Context, pvtype):
        # PVs that use the default values will never go into the alarm state
        pvname = "TEST:ALARM:PV"

        pv_double1 = PVScalarArrayRecipe(pvtype, "An example numeric alarmed PV", 0)
        pv_double1.set_alarm_limits()
        basic_server.add_pv(pvname, pv_double1)

        basic_server.start()

        test_list = [0] * 5

        for val in [-10, -5, 0, 5, 10]:
            ctx.put(pvname, test_list + [val])
            assert_pv_not_in_alarm_state(pvname, ctx)


class TestControl:
    """Integration test case for validating control limit behaviour on a variety
    of PV types"""

    @pytest.mark.parametrize(
        "pvtype, put_val, expected_val",
        [
            (PVTypes.DOUBLE, -10, -9),
            (PVTypes.DOUBLE, 0, 0),
            (PVTypes.DOUBLE, 10, 9),
            (PVTypes.INTEGER, -10, -9),
            (PVTypes.INTEGER, 0, 0),
            (PVTypes.INTEGER, 10, 9),
        ],
    )
    def test_basic_control_logic(self, basic_server: SimpleServer, ctx: Context, pvtype, put_val, expected_val):
        # here we have an example of a PV with control limits
        pvname = "TEST:CONTROL:PV"

        control_config = {"low": -9, "high": 9, "min_step": 1}
        pv_double1 = PVScalarRecipe(pvtype, "An example PV with control limits", 0)
        pv_double1.set_control_limits(**control_config)
        basic_server.add_pv(pvname, pv_double1)

        basic_server.start()

        timestamp = time.time()
        ctx.put(pvname, put_val)
        assert_value_changed(pvname, expected_val, timestamp, ctx)

    @pytest.mark.parametrize(
        "pvtype, put_val",
        [
            (PVTypes.DOUBLE, -10),
            (PVTypes.DOUBLE, 0),
            (PVTypes.DOUBLE, 10),
            (PVTypes.INTEGER, -10),
            (PVTypes.INTEGER, 0),
            (PVTypes.INTEGER, 10),
        ],
    )
    def test_default_control_logic(self, basic_server: SimpleServer, ctx: Context, pvtype, put_val):
        # here we have an example of a PV with default control limits applied
        pvname = "TEST:CONTROL:PV"

        pv_double1 = PVScalarRecipe(pvtype, "An example PV with default control limits", 0)
        pv_double1.set_control_limits()
        basic_server.add_pv(pvname, pv_double1)

        basic_server.start()

        timestamp = time.time()
        ctx.put(pvname, put_val)
        assert_value_changed(pvname, put_val, timestamp, ctx)

    @pytest.mark.parametrize(
        "pvtype",
        [
            (PVTypes.DOUBLE),
            (PVTypes.INTEGER),
        ],
    )
    def test_control_logic_min_step(self, basic_server: SimpleServer, ctx: Context, pvtype):
        # putting a new value less than the minimum step should prevent
        # the value being set
        pvname = "TEST:CONTROL:PV"

        control_config = {"low": -9, "high": 9, "min_step": 2}
        pv_double1 = PVScalarRecipe(pvtype, "An example PV with control limits", 0)
        pv_double1.set_control_limits(**control_config)

        basic_server.add_pv(pvname, pv_double1)

        basic_server.start()
        assert ctx.get(pvname).real == 0
        # setting the value to 1 shouldn't work because it's less than the minimum step
        timestamp = time.time()
        new_val = 1
        ctx.put(pvname, new_val)
        assert_value_not_changed(pvname, new_val, ctx)
        # but putting a value of 3 should work because it's above the minimum step
        timestamp = time.time()
        new_val = 3
        ctx.put(pvname, new_val)
        assert_value_changed(pvname, new_val, timestamp, ctx)

    @pytest.mark.parametrize(
        "pvtype, put_val, expected_val",
        [
            (PVTypes.DOUBLE, -10, -9),
            (PVTypes.DOUBLE, 0, 0),
            (PVTypes.DOUBLE, 10, 9),
            (PVTypes.INTEGER, -10, -9),
            (PVTypes.INTEGER, 0, 0),
            (PVTypes.INTEGER, 10, 9),
        ],
    )
    def test_basic_control_logic_array(self, basic_server: SimpleServer, ctx: Context, pvtype, put_val, expected_val):
        # here we have an example of a PV with control limits
        pvname = "TEST:CONTROL:PV"

        array_length = 6

        control_config = {"low": -9, "high": 9, "min_step": 1}
        pv_double1 = PVScalarArrayRecipe(pvtype, "An example array PV with control limits", [0] * array_length)
        pv_double1.set_control_limits(**control_config)
        basic_server.add_pv(pvname, pv_double1)

        basic_server.start()

        test_list = [0] * (array_length - 1)

        timestamp = time.time()
        ctx.put(pvname, test_list + [put_val])
        assert_value_changed(pvname, test_list + [expected_val], timestamp, ctx)
