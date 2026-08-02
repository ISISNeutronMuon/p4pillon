import logging
from unittest.mock import patch

import numpy
import pytest
from p4p import Type, Value
from p4p.nt import NTScalar

from p4pillon.rules import (
    AlarmNTEnumRule,
    AlarmRule,
    CalcRule,
    ControlRule,
    ReadOnlyRule,
    RulesFlow,
    ScalarToArrayWrapperRule,
    TimestampRule,
    ValueAlarmRule,
)
from p4pillon.rules.rules import SupportedNTTypes
from p4pillon.utils import overwrite_unmarked

# Concrete Rules exported from p4pillon.rules -- excludes BaseRule itself and
# ScalarToArrayWrapperRule, whose name/nttypes are properties derived from the
# rule it wraps rather than fixed class attributes.
#
# Deliberately hand-rolled rather than derived from p4pillon.rules.__all__: a
# derived list still needs its own exclusion set for non-rule/abstract names,
# so it doesn't remove the upkeep, just moves it. Update this list by hand
# when adding or removing a concrete rule.
CONCRETE_RULE_CLASSES = [
    AlarmNTEnumRule,
    AlarmRule,
    CalcRule,
    ControlRule,
    ReadOnlyRule,
    TimestampRule,
    ValueAlarmRule,
]


class TestTimestamp:
    @pytest.mark.parametrize(
        ("nttype", "val"),
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
    def test_timestamp(self, mock_time, nttype, val):  # noqa: ARG002 - mock only needed to prevent real time.time() being used
        rule = TimestampRule()

        assert rule.name == "timestamp"

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
        ("nttype", "val"),
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
    def test_timestamp_in_put(self, mock_time, nttype, val):  # noqa: ARG002 - mock only needed to prevent real time.time() being used
        rule = TimestampRule()

        assert rule.name == "timestamp"

        nt = NTScalar(nttype)
        old_state = nt.wrap(val)
        new_state = nt.wrap(val)

        new_state["timeStamp.secondsPastEpoch"] = 123
        new_state["timeStamp.nanoseconds"] = 456000000

        overwrite_unmarked(old_state, new_state)

        assert new_state.changed("timeStamp") is True

        result = rule.post_rule(old_state, new_state)

        assert result is RulesFlow.CONTINUE

    def test_is_applicable_no_changes(self):
        rule = TimestampRule()

        nt = NTScalar("d")
        new_state = nt.wrap(0)
        new_state.unmark()

        assert new_state.changedSet() == set()
        assert rule.is_applicable(new_state) is False

    def test_is_applicable_no_timestamp_field(self):
        rule = TimestampRule()

        type_for_test = Type([("value", "d")], id="epics:nt/NTScalar")
        new_state = Value(type_for_test, {"value": 0})

        assert "timeStamp" not in new_state
        assert rule.is_applicable(new_state) is False

    def test_is_applicable_with_timestamp_field(self):
        rule = TimestampRule()

        nt = NTScalar("d")
        new_state = nt.wrap(0)

        assert rule.is_applicable(new_state) is True

    @patch("time.time", return_value=999.999)
    def test_init_rule_preserves_caller_supplied_timestamp(self, mock_time):  # noqa: ARG002 - mock only needed to prevent real time.time() being used
        rule = TimestampRule()

        nt = NTScalar("d")
        old_state = nt.wrap(0)
        new_state = nt.wrap(0)

        # Caller explicitly supplies their own timestamp, distinct from the mocked time.time()
        new_state["timeStamp.secondsPastEpoch"] = 123
        new_state["timeStamp.nanoseconds"] = 456000000

        overwrite_unmarked(old_state, new_state)

        result = rule.init_rule(new_state)

        assert result is RulesFlow.CONTINUE
        assert new_state["timeStamp.secondsPastEpoch"] == 123
        assert new_state["timeStamp.nanoseconds"] == 456000000


class TestControl:
    @pytest.mark.parametrize(
        ("nttype", "val"),
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

        assert rule.name == "control"

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
        ("nttype", "new_value", "expected_value"),
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
                assert f"control limit exceeded, changing value to {expected_value!s}" in str(
                    caplog.records[2].getMessage()
                )
        else:
            numpy.testing.assert_array_equal(new_state["value"], expected_value)

    @pytest.mark.parametrize(
        ("nttype", "new_value", "expected_value", "expected_log", "expected_log_index"),
        [
            ("d", 2, 2, "", 1),
            ("d", 1, 0, "minStep", 1),
            ("d", 6, 5, "control limit exceeded", 2),
            ("i", 2, 2, "", 1),
            ("i", 1, 0, "minStep", 1),
            ("i", 6, 5, "control limit exceeded", 2),
            ("ad", [2, 2, 2], [2, 2, 2], ["", "", ""], 1),
            ("ad", [1, 1, 1], [0, 0, 0], ["minStep", "minStep", "minStep"], 1),
            (
                "ad",
                [6, 6, 6],
                [5, 5, 5],
                ["control limit exceeded", "control limit exceeded", "control limit exceeded"],
                2,
            ),
            ("ai", [2, 2, 2], [2, 2, 2], ["", "", ""], 1),
            ("ai", [1, 1, 1], [0, 0, 0], ["minStep", "minStep", "minStep"], 1),
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
                for item in zip(expected_log, caplog.records[expected_log_index::3], strict=True):
                    assert item[0] in item[1].getMessage()

    @pytest.mark.parametrize(
        ("nttype", "control_changes", "expected_value", "read_only"),
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


class TestCalcRule:
    def test_create_calc_rule(self):
        rule = CalcRule()

        assert rule.name == "calc"

    def test_initialise_calc_rule(self):
        rule = CalcRule()

        a_server = "fakeServer"
        calc = {"calc_str": "pv[0]+10", "variables": "a:pv:name", "server": a_server, "pv_name": "this:pv:name"}
        rule.set_calc(calc)
        assert rule._calc_str == "pv[0]+10"
        assert type(rule._variables) is list
        assert len(rule._variables) == 1
        assert rule._variables[0] == "a:pv:name"
        assert rule._server == "fakeServer"
        assert rule._pv_name == "this:pv:name"


class TestRuleClassAttributes:
    """`name` and `nttypes` are used by SharedNT/CompositeHandler for rule
    introspection (see BaseRule's docstring). A Rule that leaves either unset
    -- e.g. through a typo like `nttype` instead of `nttypes` -- silently
    becomes invisible to that machinery instead of raising an error."""

    @pytest.mark.parametrize("rule_cls", CONCRETE_RULE_CLASSES, ids=lambda cls: cls.__name__)
    def test_name_is_set(self, rule_cls):
        assert isinstance(rule_cls.name, str)
        assert rule_cls.name != ""

    @pytest.mark.parametrize("rule_cls", CONCRETE_RULE_CLASSES, ids=lambda cls: cls.__name__)
    def test_nttypes_is_set(self, rule_cls):
        # None/[] both mean "applies to all types" (see BaseRule.nttypes docstring
        # and sharednt.py's `if supported_nttypes:` check) -- either is valid, but
        # whatever is set must only contain real SupportedNTTypes members.
        if rule_cls.nttypes is None:
            return
        assert isinstance(rule_cls.nttypes, list)
        assert all(isinstance(nttype, SupportedNTTypes) for nttype in rule_cls.nttypes)
