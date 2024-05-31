import sys
from pathlib import Path

from p4p.client.thread import Context

root_dir = Path(__file__).parents[2]

sys.path.append(str(root_dir))


def assert_value_changed(
    pvname: str, put_value: float, put_timestamp: float, ctx: Context
):
    pv_state = ctx.get(pvname)
    assert pv_state.real == put_value
    assert pv_state.timestamp > put_timestamp


def assert_value_not_changed(
    pvname: str, put_value: float, put_timestamp: float, ctx: Context
):
    pv_state = ctx.get(pvname)
    assert pv_state.real != put_value
    assert pv_state.timestamp < put_timestamp


def assert_correct_display_config(
    ctx: Context, pvname: str, display_config: dict, numeric: bool = True
):
    pv_state = ctx.get(pvname).raw.todict()
    display_state = pv_state.get("display", {})
    # the descriptor and the display description should in theory be the same
    assert (
        pv_state.get("descriptor", "")
        == display_config.get("description", "")
        == display_state.get("description")
        == display_config.get("description", "")
    )
    assert display_state.get("units") == display_config.get("units", "")

    # string NTScalars don't have these fields configured so we don't check them
    if numeric:
        assert display_state.get("format") == display_config.get("format", "")
        assert display_state.get("limitHigh") == display_config.get("limitHigh", 0.0)
        assert display_state.get("limitLow") == display_config.get("limitLow", 0.0)


def assert_alarm_present(ctx: Context, pvname: str):
    pv_state = ctx.get(pvname)

    for key in ["severity", "status", "message"]:
        assert pv_state.raw.todict().get("alarm").get(key) is not None


def assert_correct_alarm_config(ctx: Context, pvname: str, alarm_config: dict):
    value_alarm_state = ctx.get(pvname).raw.todict().get("valueAlarm", {})

    assert value_alarm_state.get("active") is not None
    assert value_alarm_state.get("hysteresis") is not None
    assert value_alarm_state.get("highAlarmLimit") is not None
    assert value_alarm_state.get("highWarningLimit") is not None
    assert value_alarm_state.get("lowAlarmLimit") is not None
    assert value_alarm_state.get("lowWarningLimit") is not None
    assert value_alarm_state.get("highAlarmSeverity") is not None
    assert value_alarm_state.get("highWarningSeverity") is not None
    assert value_alarm_state.get("lowAlarmSeverity") is not None
    assert value_alarm_state.get("lowWarningSeverity") is not None


def assert_correct_control_config(ctx: Context, pvname: str, control_config: dict):
    control_state = ctx.get(pvname).raw.todict().get("control", {})

    assert control_state.get("limitHigh") is not None
    assert control_state.get("limitLow") is not None
    assert control_state.get("minStep") is not None
