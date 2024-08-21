import logging
from unittest.mock import patch

import pytest
from p4p.nt import NTScalar

from p4p_for_isis.definitions import AlarmSeverity
from p4p_for_isis.rules import ValueAlarmRule, ControlRule, RulesFlow, TimestampRule
from p4p_for_isis.value_utils import overwrite_unmarked


class TestTimestamp:
    @pytest.mark.parametrize("nttype, val", [("d", 0), ("i", 0), ("s", "0")])
    @patch("time.time", return_value=123.456)
    def test_timestamp(self, _, nttype, val):
        rule = TimestampRule()

        assert rule._name == "timestamp"

        nt = NTScalar(nttype)
        old_state = nt.wrap(val)
        new_state = nt.wrap(val)
        overwrite_unmarked(old_state, new_state)

        assert new_state.changed("timeStamp") is False

        result = rule.post_rule(old_state, new_state)

        assert result is RulesFlow.CONTINUE
        assert new_state.changed("timeStamp") is True
        assert new_state["timeStamp.secondsPastEpoch"] == 123
        assert new_state["timeStamp.nanoseconds"] == 456000000

    @pytest.mark.parametrize("nttype, val", [("d", 0), ("i", 0), ("s", "0")])
    @patch("time.time", return_value=123.456)
    def test_timestamp_in_put(self, _, nttype, val):
        rule = TimestampRule()

        assert rule._name == "timestamp"

        nt = NTScalar(nttype)
        old_state = nt.wrap(val)
        new_state = nt.wrap(val)

        new_state["timeStamp.secondsPastEpoch"] = 123
        new_state["timeStamp.nanoseconds"] = 456000000

        overwrite_unmarked(old_state, new_state)

        assert new_state.changed("timeStamp") is True

        result = rule.post_rule(old_state, new_state)

        assert result is RulesFlow.CONTINUE


class TestControl:
    @pytest.mark.parametrize("nttype, val", [("d", 0), ("i", 0), ("s", "0")])
    def test_control_not_set(self, nttype, val, caplog):
        rule = ControlRule()

        assert rule._name == "control"

        # control not present
        nt = NTScalar(nttype)
        old_state = nt.wrap(val)
        new_state = nt.wrap(val)
        overwrite_unmarked(old_state, new_state)

        with caplog.at_level(logging.DEBUG):
            result = rule.post_rule(old_state, new_state)

        assert result is RulesFlow.CONTINUE
        assert len(caplog.records) == 1
        assert "Rule control.post_rule is not applicable" in str(caplog.records[0].getMessage())

    @pytest.mark.parametrize(
        "nttype, new_value, expected_value",
        [
            ("d", -6, -5),
            ("d", -1, -1),
            ("d", 1, 1),
            ("d", 6, 5),
            ("i", -6, -5),
            ("i", -1, -1),
            ("i", 1, 1),
            ("i", 6, 5),
        ],
    )
    def test_control(self, nttype, new_value, expected_value, caplog):
        rule = ControlRule()

        nt = NTScalar(nttype, control=True)
        control_limits = {"limitLow": -5, "limitHigh": 5, "minStep": 1}
        old_state = nt.wrap({"value": 0.0, "control": control_limits})
        new_state = nt.wrap({"value": new_value, "control": control_limits})
        overwrite_unmarked(old_state, new_state)

        with caplog.at_level(logging.DEBUG):
            result = rule.post_rule(old_state, new_state)

        assert result is RulesFlow.CONTINUE

        assert new_state["value"] == expected_value

        if new_value != expected_value:
            assert len(caplog.records) == 1
            assert f"control limit exceeded, changing value to {str(expected_value)}" in str(
                caplog.records[0].getMessage()
            )

    @pytest.mark.parametrize(
        "nttype, new_value, expected_value, expected_log",
        [
            ("d", 2, 2, ""),
            ("d", 1, 0, "minStep"),
            ("d", 6, 5, "control limit exceeded"),
            ("i", 2, 2, ""),
            ("i", 1, 0, "minStep"),
            ("i", 6, 5, "control limit exceeded"),
        ],
    )
    def test_control_min_step(self, nttype, new_value, expected_value, expected_log, caplog):
        rule = ControlRule()

        nt = NTScalar(nttype, control=True)
        control_limits = {"limitLow": -5, "limitHigh": 5, "minStep": 2}
        old_state = nt.wrap({"value": 0.0, "control": control_limits})
        new_state = nt.wrap({"value": new_value, "control": control_limits})
        overwrite_unmarked(old_state, new_state)

        with caplog.at_level(logging.DEBUG):
            result = rule.post_rule(old_state, new_state)

        assert result is RulesFlow.CONTINUE

        assert new_state["value"] == expected_value

        if new_value != expected_value:
            assert len(caplog.records) == 1
            assert expected_log in str(caplog.records[0].getMessage())


class TestAlarmLimit:
    @pytest.mark.parametrize(
        "nttype, new_val, expected_severity, expected_message",
        [
            ("d", -10, AlarmSeverity.MAJOR_ALARM.value, "lowAlarm"),
            ("d", -5, AlarmSeverity.MINOR_ALARM.value, "lowWarning"),
            ("d", 0, AlarmSeverity.NO_ALARM.value, ""),
            ("d", 5, AlarmSeverity.MINOR_ALARM.value, "highWarning"),
            ("d", 10, AlarmSeverity.MAJOR_ALARM.value, "highAlarm"),
            ("i", -10, AlarmSeverity.MAJOR_ALARM.value, "lowAlarm"),
            ("i", -5, AlarmSeverity.MINOR_ALARM.value, "lowWarning"),
            ("i", 0, AlarmSeverity.NO_ALARM.value, ""),
            ("i", 5, AlarmSeverity.MINOR_ALARM.value, "highWarning"),
            ("i", 10, AlarmSeverity.MAJOR_ALARM.value, "highAlarm"),
        ],
    )
    def test_alarm_limits_value_change(self, nttype, new_val, expected_severity, expected_message, caplog):
        rule = ValueAlarmRule()

        nt = NTScalar(nttype, valueAlarm=True)
        alarm_limits = {
            "active": True,
            "lowAlarmLimit": -9,
            "lowWarningLimit": -4,
            "highWarningLimit": 4,
            "highAlarmLimit": 9,
            "lowAlarmSeverity": AlarmSeverity.MAJOR_ALARM.value,
            "lowWarningSeverity": AlarmSeverity.MINOR_ALARM.value,
            "highAlarmSeverity": AlarmSeverity.MAJOR_ALARM.value,
            "highWarningSeverity": AlarmSeverity.MINOR_ALARM.value,
        }
        old_state = nt.wrap({"value": 0.0, "valueAlarm": alarm_limits})
        new_state = nt.wrap({"value": new_val, "valueAlarm": alarm_limits})
        overwrite_unmarked(old_state, new_state)

        with caplog.at_level(logging.DEBUG):
            result = rule.post_rule(old_state, new_state)

        assert result is RulesFlow.CONTINUE

        assert new_state["value"] == new_val
        assert new_state["alarm.severity"] == expected_severity
        assert new_state["alarm.message"] == expected_message

    @pytest.mark.parametrize("nttype", [("d"), ("i")])
    def test_alarm_limits_not_active(self, nttype, caplog):
        rule = ValueAlarmRule()

        nt = NTScalar(nttype, valueAlarm=True)
        alarm_limits = {
            "active": False,
            "lowAlarmLimit": -9,
            "lowAlarmSeverity": AlarmSeverity.MAJOR_ALARM.value,
        }
        old_state = nt.wrap({"value": 0.0, "valueAlarm": alarm_limits})
        new_state = nt.wrap({"value": -10, "valueAlarm": alarm_limits})
        overwrite_unmarked(old_state, new_state)

        with caplog.at_level(logging.DEBUG):
            result = rule.post_rule(old_state, new_state)

        assert result is RulesFlow.CONTINUE

        assert new_state["value"] == -10
        assert new_state["alarm.severity"] == AlarmSeverity.NO_ALARM.value
        assert new_state["alarm.message"] == ""

    @pytest.mark.parametrize("nttype", [("d"), ("i")])
    def test_alarm_limits_not_present(self, nttype, caplog):
        rule = ValueAlarmRule()

        nt = NTScalar(nttype)
        old_state = nt.wrap({"value": 0.0})
        new_state = nt.wrap({"value": -10})
        overwrite_unmarked(old_state, new_state)

        with caplog.at_level(logging.DEBUG):
            result = rule.post_rule(old_state, new_state)

        assert result is RulesFlow.CONTINUE

        assert new_state["value"] == -10
        assert new_state["alarm.severity"] == AlarmSeverity.NO_ALARM.value
        assert new_state["alarm.message"] == ""

    @pytest.mark.parametrize("nttype", [("d"), ("i")])
    def test_alarm_limits_from_alarm_state_to_none(self, nttype):
        # here we make sure that changing the value from a previous alarm state will put us
        # a no alarm state
        rule = ValueAlarmRule()

        nt = NTScalar(nttype, valueAlarm=True)
        alarm_limits = {
            "active": True,
            "lowAlarmLimit": -9,
            "lowWarningLimit": -4,
            "highWarningLimit": 4,
            "highAlarmLimit": 9,
            "lowAlarmSeverity": AlarmSeverity.MAJOR_ALARM.value,
            "lowWarningSeverity": AlarmSeverity.MINOR_ALARM.value,
            "highAlarmSeverity": AlarmSeverity.MAJOR_ALARM.value,
            "highWarningSeverity": AlarmSeverity.MINOR_ALARM.value,
        }
        old_state = nt.wrap(
            {
                "value": -10,
                "valueAlarm": alarm_limits,
                "alarm": {
                    "severity": AlarmSeverity.MAJOR_ALARM.value,
                    "message": "highAlarm",
                    "status": 0,
                },
            }
        )
        new_state = nt.wrap({"value": 0})
        overwrite_unmarked(old_state, new_state)

        result = rule.post_rule(old_state, new_state)

        assert result is RulesFlow.CONTINUE

        assert new_state["value"] == 0
        assert new_state["alarm.severity"] == AlarmSeverity.NO_ALARM.value
        assert new_state["alarm.message"] == ""

    @pytest.mark.parametrize(
        "nttype, limit_change, new_limit, expected_severity, expected_message",
        [
            ("d", "lowAlarmLimit", 2, AlarmSeverity.MAJOR_ALARM, "lowAlarm"),
            ("d", "lowWarningLimit", 2, AlarmSeverity.MINOR_ALARM, "lowWarning"),
            ("d", "highWarningLimit", 0, AlarmSeverity.MINOR_ALARM, "highWarning"),
            ("d", "highAlarmLimit", 0, AlarmSeverity.MAJOR_ALARM, "highAlarm"),
            ("i", "lowAlarmLimit", 2, AlarmSeverity.MAJOR_ALARM, "lowAlarm"),
            ("i", "lowWarningLimit", 2, AlarmSeverity.MINOR_ALARM, "lowWarning"),
            ("i", "highWarningLimit", 0, AlarmSeverity.MINOR_ALARM, "highWarning"),
            ("i", "highAlarmLimit", 1, AlarmSeverity.MAJOR_ALARM, "highAlarm"),
        ],
    )
    def test_alarm_limits_changing_limits(self, nttype, limit_change, new_limit, expected_severity, expected_message):
        # if we change the limit on an alarm, we want to make sure that the new alarm state
        # is calculated based on the new limits
        rule = ValueAlarmRule()

        nt = NTScalar(nttype, valueAlarm=True)
        alarm_limits = {
            "active": True,
            "lowAlarmLimit": -9,
            "lowWarningLimit": -4,
            "highWarningLimit": 4,
            "highAlarmLimit": 9,
            "lowAlarmSeverity": AlarmSeverity.MAJOR_ALARM.value,
            "lowWarningSeverity": AlarmSeverity.MINOR_ALARM.value,
            "highAlarmSeverity": AlarmSeverity.MAJOR_ALARM.value,
            "highWarningSeverity": AlarmSeverity.MINOR_ALARM.value,
        }
        old_state = nt.wrap(
            {
                "value": 0,
                "valueAlarm": alarm_limits,
            }
        )
        new_state = nt.wrap(
            {
                "value": 1,
                f"valueAlarm.{limit_change}": new_limit,
            }
        )
        overwrite_unmarked(old_state, new_state)

        result = rule.post_rule(old_state, new_state)

        assert result is RulesFlow.CONTINUE

        assert new_state["value"] == 1
        assert new_state["alarm.severity"] == expected_severity.value
        assert new_state["alarm.message"] == expected_message
