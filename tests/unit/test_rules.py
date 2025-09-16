import logging
from unittest.mock import patch

import numpy
import pytest
from p4p.nt import NTScalar

from p4pillon.definitions import AlarmSeverity
from p4pillon.rules import ControlRule, RulesFlow, ScalarToArrayWrapperRule, TimestampRule, ValueAlarmRule
from p4pillon.utils import overwrite_unmarked


class TestTimestamp:
    @pytest.mark.parametrize(
        "nttype, val",
        [
            ("d", 0),
            ("i", 0),
            ("s", "0"),
            ("ad", [0.5, 1.1, 2.2]),
            ("ai", [0, 1, 2]),
            ("as", ["0", "a", "longerstring"]),
        ],
    )
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

    @pytest.mark.parametrize(
        "nttype, val",
        [
            ("d", 0),
            ("i", 0),
            ("s", "0"),
            ("ad", [0.5, 1.1, 2.2]),
            ("ai", [0, 1, 2]),
            ("as", ["0", "a", "longerstring"]),
        ],
    )
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
    @pytest.mark.parametrize(
        "nttype, val",
        [
            ("d", 0),
            ("i", 0),
            ("s", "0"),
            ("ad", [0.5, 1.1, 2.2]),
            ("ai", [0, 1, 2]),
            ("as", ["0", "a", "longerstring"]),
        ],
    )
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
            ("ad", [-6, -6, -6], [-5, -5, -5]),
            ("ad", [-1, -1, -1], [-1, -1, -1]),
            ("ad", [1, 1, 1], [1, 1, 1]),
            ("ad", [6, 6, 6], [5, 5, 5]),
            ("ai", [-6, -6, -6], [-5, -5, -5]),
            ("ai", [-1, -1, -1], [-1, -1, -1]),
            ("ai", [1, 1, 1], [1, 1, 1]),
            ("ai", [6, 6, 6], [5, 5, 5]),
        ],
    )
    def test_control(self, nttype, new_value, expected_value, caplog):
        nt = NTScalar(nttype, control=True)
        control_limits = {"limitLow": -5, "limitHigh": 5, "minStep": 1}
        if not nttype.startswith("a"):
            rule = ControlRule()
            old_state = nt.wrap({"value": 0.0, "control": control_limits})
        else:
            rule = ScalarToArrayWrapperRule(ControlRule())
            old_state = nt.wrap({"value": [0.0, 0.0, 0.0], "control": control_limits})

        new_state = nt.wrap({"value": new_value, "control": control_limits})
        overwrite_unmarked(old_state, new_state)

        with caplog.at_level(logging.DEBUG):
            result = rule.post_rule(old_state, new_state)

        assert result is RulesFlow.CONTINUE

        if not nttype.startswith("a"):
            assert new_state["value"] == expected_value

            if new_value != expected_value:
                assert len(caplog.records) == 3
                assert f"control limit exceeded, changing value to {str(expected_value)}" in str(
                    caplog.records[2].getMessage()
                )
        else:
            numpy.testing.assert_array_equal(new_state["value"], expected_value)

    @pytest.mark.parametrize(
        "nttype, new_value, expected_value, expected_log, expected_log_index",
        [
            ("d", 2, 2, "", 1),
            ("d", 1, 0, "minStep", 1),
            ("d", 6, 5, "control limit exceeded", 2),
            ("i", 2, 2, "", 1),
            ("i", 1, 0, "minStep", 1),
            ("i", 6, 5, "control limit exceeded", 2),
            ("ad", [2, 2, 2], [2, 2, 2], ["", "", ""], 1),
            ("ad", [1, 1, 1], [0, 0, 0], ["minStep", "minStep", "minStep"], 3),
            (
                "ad",
                [6, 6, 6],
                [5, 5, 5],
                ["control limit exceeded", "control limit exceeded", "control limit exceeded"],
                2,
            ),
            ("ai", [2, 2, 2], [2, 2, 2], ["", "", ""], 1),
            ("ai", [1, 1, 1], [0, 0, 0], ["minStep", "minStep", "minStep"], 3),
            (
                "ai",
                [6, 6, 6],
                [5, 5, 5],
                ["control limit exceeded", "control limit exceeded", "control limit exceeded"],
                2,
            ),
        ],
    )
    def test_control_min_step(self, nttype, new_value, expected_value, expected_log, expected_log_index, caplog):
        nt = NTScalar(nttype, control=True)
        control_limits = {"limitLow": -5, "limitHigh": 5, "minStep": 2}
        if not nttype.startswith("a"):
            rule = ControlRule()
            old_state = nt.wrap({"value": 0.0, "control": control_limits})
        else:
            rule = ScalarToArrayWrapperRule(ControlRule())
            old_state = nt.wrap({"value": [0.0, 0.0, 0.0], "control": control_limits})
        new_state = nt.wrap({"value": new_value, "control": control_limits})
        overwrite_unmarked(old_state, new_state)

        with caplog.at_level(logging.DEBUG):
            result = rule.post_rule(old_state, new_state)

        assert result is RulesFlow.CONTINUE

        if not nttype.startswith("a"):
            assert new_state["value"] == expected_value

            if new_value != expected_value:
                assert len(caplog.records) == 3
                assert expected_log in str(caplog.records[expected_log_index].getMessage())

        else:
            numpy.testing.assert_array_equal(new_state["value"], expected_value)

            if not numpy.array_equal(new_value, expected_value):
                assert len(caplog.records) == 9
                for item in zip(expected_log, caplog.records[expected_log_index:3:]):
                    assert item[0] in item[1].getMessage()

    @pytest.mark.parametrize(
        "nttype, control_changes, expected_value, read_only",
        [
            ("d", [-6, -5, 5, 2], -5, True),
            ("d", [-6, -5, 5, 2], -5, False),
            ("d", [-7, -10, 5, 2], -5, True),
            ("d", [-7, -10, 5, 2], -7, False),
        ],
    )
    def test_control_change_with_put(self, nttype, control_changes, expected_value, read_only):
        nt = NTScalar(nttype, control=True)
        control_limits = {"limitLow": -5, "limitHigh": 5, "minStep": 2}
        if not nttype.startswith("a"):
            rule = ControlRule()
            old_state = nt.wrap({"value": 0.0, "control": control_limits})
        else:
            rule = ScalarToArrayWrapperRule(ControlRule())
            old_state = nt.wrap({"value": [0.0, 0.0, 0.0], "control": control_limits})
        rule.read_only = read_only

        control_limits = {
            "limitLow": control_changes[1],
            "limitHigh": control_changes[2],
            "minStep": control_changes[3],
        }
        new_state = nt.wrap({"value": control_changes[0], "control": control_limits})
        overwrite_unmarked(old_state, new_state)

        with (
            patch("p4p.server.ServerOperation", autospec=True) as server_op,
        ):
            server_op.value.return_value = nt.unwrap(new_state)
            result = rule.put_rule(old_state, new_state, server_op)  # New rules no long auto-call post_rule
            result = rule.post_rule(old_state, new_state)

        assert result is RulesFlow.CONTINUE

        if not nttype.startswith("a"):
            assert new_state["value"] == expected_value
        else:
            numpy.testing.assert_array_equal(new_state["value"], expected_value)


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
            ("ad", [0, 0, -10], AlarmSeverity.MAJOR_ALARM.value, "lowAlarm"),
            ("ad", [0, -10, 0], AlarmSeverity.MAJOR_ALARM.value, "lowAlarm"),
            ("ad", [0, -5, 0], AlarmSeverity.MINOR_ALARM.value, "lowWarning"),
            ("ad", [0, 0, 0], AlarmSeverity.NO_ALARM.value, ""),
            ("ad", [0, 5, 0], AlarmSeverity.MINOR_ALARM.value, "highWarning"),
            ("ad", [0, 10, 0], AlarmSeverity.MAJOR_ALARM.value, "highAlarm"),
            ("ai", [0, 0, -10], AlarmSeverity.MAJOR_ALARM.value, "lowAlarm"),
            ("ai", [0, -10, 0], AlarmSeverity.MAJOR_ALARM.value, "lowAlarm"),
            ("ai", [0, -5, 0], AlarmSeverity.MINOR_ALARM.value, "lowWarning"),
            ("ai", [0, 0, 0], AlarmSeverity.NO_ALARM.value, ""),
            ("ai", [0, 5, 0], AlarmSeverity.MINOR_ALARM.value, "highWarning"),
            ("ai", [0, 10, 0], AlarmSeverity.MAJOR_ALARM.value, "highAlarm"),
        ],
    )
    def test_alarm_limits_value_change(self, nttype, new_val, expected_severity, expected_message, caplog):
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
        if not nttype.startswith("a"):
            rule = ValueAlarmRule()
            old_state = nt.wrap({"value": 0.0, "valueAlarm": alarm_limits})
        else:
            rule = ScalarToArrayWrapperRule(ValueAlarmRule())
            old_state = nt.wrap({"value": [0.0, 0.0, 0.0], "valueAlarm": alarm_limits})
        new_state = nt.wrap({"value": new_val, "valueAlarm": alarm_limits})
        overwrite_unmarked(old_state, new_state)

        with caplog.at_level(logging.DEBUG):
            result = rule.post_rule(old_state, new_state)

        assert result is RulesFlow.CONTINUE

        if not nttype.startswith("a"):
            assert new_state["value"] == new_val
        else:
            numpy.testing.assert_array_equal(new_state["value"], new_val)

        assert new_state["alarm.severity"] == expected_severity
        assert new_state["alarm.message"] == expected_message

    @pytest.mark.parametrize(
        "nttype, new_val", [("d", -10), ("i", -10), ("ad", [-10, -10, -10]), ("ai", [-10, -10, -10])]
    )
    def test_alarm_limits_not_active(self, nttype, new_val, caplog):
        nt = NTScalar(nttype, valueAlarm=True)
        alarm_limits = {
            "active": False,
            "lowAlarmLimit": -9,
            "lowAlarmSeverity": AlarmSeverity.MAJOR_ALARM.value,
        }
        if not nttype.startswith("a"):
            rule = ValueAlarmRule()
            old_state = nt.wrap({"value": 0.0, "valueAlarm": alarm_limits})
        else:
            rule = ScalarToArrayWrapperRule(ValueAlarmRule())
            old_state = nt.wrap({"value": [0.0, 0.0, 0.0], "valueAlarm": alarm_limits})
        new_state = nt.wrap({"value": new_val, "valueAlarm": alarm_limits})
        overwrite_unmarked(old_state, new_state)

        with caplog.at_level(logging.DEBUG):
            result = rule.post_rule(old_state, new_state)

        assert result is RulesFlow.CONTINUE

        if not nttype.startswith("a"):
            assert new_state["value"] == new_val
        else:
            numpy.testing.assert_array_equal(new_state["value"], new_val)

        assert new_state["alarm.severity"] == AlarmSeverity.NO_ALARM.value
        assert new_state["alarm.message"] == ""

    @pytest.mark.parametrize(
        "nttype, new_val", [("d", -10), ("i", -10), ("ad", [-10, -10, -10]), ("ai", [-10, -10, -10])]
    )
    def test_alarm_limits_not_present(self, nttype, new_val, caplog):
        nt = NTScalar(nttype)
        if not nttype.startswith("a"):
            rule = ValueAlarmRule()
            old_state = nt.wrap({"value": 0.0})
        else:
            rule = ScalarToArrayWrapperRule(ValueAlarmRule())
            old_state = nt.wrap({"value": [0.0, 0.0, 0.0]})
        new_state = nt.wrap({"value": new_val})
        overwrite_unmarked(old_state, new_state)

        with caplog.at_level(logging.DEBUG):
            result = rule.post_rule(old_state, new_state)

        assert result is RulesFlow.CONTINUE

        if not nttype.startswith("a"):
            assert new_state["value"] == new_val
        else:
            numpy.testing.assert_array_equal(new_state["value"], new_val)

        assert new_state["alarm.severity"] == AlarmSeverity.NO_ALARM.value
        assert new_state["alarm.message"] == ""

    @pytest.mark.parametrize(
        "nttype, new_val", [("d", -10), ("i", -10), ("ad", [-10, -10, -10]), ("ai", [-10, -10, -10])]
    )
    def test_alarm_limits_from_alarm_state_to_none(self, nttype, new_val):
        # here we make sure that changing the value from a previous alarm state will put us
        # a no alarm state

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
                "value": new_val,
                "valueAlarm": alarm_limits,
                "alarm": {
                    "severity": AlarmSeverity.MAJOR_ALARM.value,
                    "message": "highAlarm",
                    "status": 0,
                },
            }
        )
        if not nttype.startswith("a"):
            rule = ValueAlarmRule()
            new_state = nt.wrap({"value": 0})
        else:
            rule = ScalarToArrayWrapperRule(ValueAlarmRule())
            new_state = nt.wrap({"value": [0, 0, 0]})

        overwrite_unmarked(old_state, new_state)

        result = rule.post_rule(old_state, new_state)

        assert result is RulesFlow.CONTINUE

        if not nttype.startswith("a"):
            assert new_state["value"] == 0
        else:
            numpy.testing.assert_array_equal(new_state["value"], [0, 0, 0])

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
            ("ad", "lowAlarmLimit", 2, AlarmSeverity.MAJOR_ALARM, "lowAlarm"),
            ("ad", "lowWarningLimit", 2, AlarmSeverity.MINOR_ALARM, "lowWarning"),
            ("ad", "highWarningLimit", 0, AlarmSeverity.MINOR_ALARM, "highWarning"),
            ("ad", "highAlarmLimit", 0, AlarmSeverity.MAJOR_ALARM, "highAlarm"),
            ("ai", "lowAlarmLimit", 2, AlarmSeverity.MAJOR_ALARM, "lowAlarm"),
            ("ai", "lowWarningLimit", 2, AlarmSeverity.MINOR_ALARM, "lowWarning"),
            ("ai", "highWarningLimit", 0, AlarmSeverity.MINOR_ALARM, "highWarning"),
            ("ai", "highAlarmLimit", 1, AlarmSeverity.MAJOR_ALARM, "highAlarm"),
        ],
    )
    def test_alarm_limits_changing_limits(self, nttype, limit_change, new_limit, expected_severity, expected_message):
        # if we change the limit on an alarm, we want to make sure that the new alarm state
        # is calculated based on the new limits
        if not nttype.startswith("a"):
            rule = ValueAlarmRule()
            old_value = 0
            new_value = 1
        else:
            rule = ScalarToArrayWrapperRule(ValueAlarmRule())
            old_value = [0, 0, 0]
            new_value = [0, 1, 0]

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
                "value": old_value,
                "valueAlarm": alarm_limits,
            }
        )
        new_state = nt.wrap(
            {
                "value": new_value,
                f"valueAlarm.{limit_change}": new_limit,
            }
        )
        overwrite_unmarked(old_state, new_state)

        result = rule.post_rule(old_state, new_state)

        assert result is RulesFlow.CONTINUE

        if not nttype.startswith("a"):
            assert new_state["value"] == new_value
        else:
            numpy.testing.assert_array_equal(new_state["value"], new_value)

        assert new_state["alarm.severity"] == expected_severity.value
        assert new_state["alarm.message"] == expected_message
