import numpy as np
from p4p.client.thread import Context

from p4pillon.definitions import MAX_FLOAT, MAX_INT32, MIN_FLOAT, MIN_INT32, AlarmSeverity, Format


def assert_value_changed(pvname: str, put_value, put_timestamp: float, ctx: Context):
    pv_state = ctx.get(pvname)
    current_value = pv_state.raw.todict()["value"]
    assert np.array_equal(np.array(current_value), np.array(put_value))
    # assert pv_state.timestamp >= put_timestamp  # TODO: Check why this timestamp is broken?


def assert_value_not_changed(pvname: str, put_value, ctx: Context):
    pv_state = ctx.get(pvname)
    current_value = pv_state.raw.todict()["value"]
    assert not np.array_equal(np.array(current_value), np.array(put_value))


def assert_alarm_present(ctx: Context, pvname: str):
    pv_state = ctx.get(pvname)

    for key in ["severity", "status", "message"]:
        assert pv_state.raw.todict().get("alarm").get(key) is not None


def assert_correct_display_config(pv_state: dict, pv_config: dict):
    display_state = pv_state.get("display")
    display_config = pv_config.get("display")
    if display_config is None:
        # this occurs when the entry in the yaml file is present but nothing
        # listed within it
        display_config = {}

    assert display_state.get("description") == pv_config.get("description")
    assert display_state.get("units") == display_config.get("units", "")
    assert display_state.get("form") == {
        "index": Format[display_config.get("format", "DEFAULT")].value[0],
        "choices": [form.value[1] for form in Format],
    }

    assert display_state.get("precision") == display_config.get("precision", 2)
    assert display_state.get("limitHigh") == display_config.get("high", MAX_FLOAT)
    assert display_state.get("limitLow") == display_config.get("low", MIN_FLOAT)


def assert_correct_control_config(pv_state: dict, pv_config: dict):
    control_state = pv_state.get("control")
    control_config = pv_config.get("control")
    if control_config is None:
        # this occurs when the entry in the yaml file is present but nothing
        # listed within it
        control_config = {}

    if pv_config["type"] == "DOUBLE":
        default_max, default_min = MAX_FLOAT, MIN_FLOAT
    else:
        default_max, default_min = MAX_INT32, MIN_INT32

    assert control_state.get("limitLow") == control_config.get("low", default_min)
    assert control_state.get("limitHigh") == control_config.get("high", default_max)
    assert control_state.get("minStep") == control_config.get("min_step", 0)


def assert_correct_alarm_config(pv_state: dict, pv_config: dict):
    valueAlarm_state = pv_state.get("valueAlarm")

    valueAlarm_config = pv_config.get("valueAlarm")
    if valueAlarm_config is None:
        # this occurs when the entry in the yaml file is present but nothing
        # listed within it
        valueAlarm_config = {}

    if pv_config["type"] == "DOUBLE":
        default_max, default_min = MAX_FLOAT, MIN_FLOAT
    else:
        default_max, default_min = MAX_INT32, MIN_INT32

    assert valueAlarm_state.get("lowAlarmLimit") == valueAlarm_config.get("low_alarm", default_min)
    assert valueAlarm_state.get("lowWarningLimit") == valueAlarm_config.get("low_warning", default_min)
    assert valueAlarm_state.get("highAlarmLimit") == valueAlarm_config.get("high_alarm", default_max)
    assert valueAlarm_state.get("highWarningLimit") == valueAlarm_config.get("high_warning", default_max)
    assert valueAlarm_state.get("lowAlarmSeverity") == AlarmSeverity.MAJOR_ALARM.value
    assert valueAlarm_state.get("lowWarningSeverity") == AlarmSeverity.MINOR_ALARM.value
    assert valueAlarm_state.get("highAlarmSeverity") == AlarmSeverity.MAJOR_ALARM.value
    assert valueAlarm_state.get("highWarningSeverity") == AlarmSeverity.MINOR_ALARM.value
    assert valueAlarm_state.get("hysteresis") == 0


def assert_pv_in_major_alarm_state(pvname: str, ctx: Context):
    val = ctx.get(pvname)
    assert val.severity == AlarmSeverity.MAJOR_ALARM.value


def assert_pv_in_minor_alarm_state(pvname: str, ctx: Context):
    val = ctx.get(pvname)
    assert val.severity == AlarmSeverity.MINOR_ALARM.value


def assert_pv_in_invalid_alarm_state(pvname: str, ctx: Context):
    val = ctx.get(pvname)
    assert val.severity == AlarmSeverity.INVALID_ALARM.value


def assert_pv_not_in_alarm_state(pvname: str, ctx: Context):
    val = ctx.get(pvname)
    assert val.severity == AlarmSeverity.NO_ALARM.value


def assert_enum_value_changed(pvname: str, put_value: dict, put_timestamp: float, ctx: Context):
    pv_state = ctx.get(pvname)
    current_value = pv_state.raw.todict()["value"]
    assert put_value == current_value
    print(
        f"time from PV = {pv_state.timestamp}, time at put = {put_timestamp}, diff = {pv_state.timestamp - put_timestamp}"
    )
    assert pv_state.timestamp >= put_timestamp


def assert_enum_value_not_changed(pvname: str, put_value, ctx: Context):
    pv_state = ctx.get(pvname)
    current_value = pv_state.raw.todict()["value"]
    assert put_value != current_value
