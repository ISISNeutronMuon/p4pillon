import math
from typing import Any
from unittest.mock import MagicMock

import pytest
from p4p import Value
from p4p.nt import NTScalar
from simpleeval import InvalidExpression

from p4pillon.rules import CalcRule
from p4pillon.rules.rules import RulesFlow


def make_calc_rule(calc_str: str, variables: str | list[str], pv_values: list[Any]) -> tuple[CalcRule, MagicMock]:
    """Build a CalcRule with a mock server that returns pv_values in order for get_pv_value calls."""
    server = MagicMock()
    server.__class__.__name__ = "Server"
    server.get_pv_value.side_effect = pv_values

    rule = CalcRule()
    rule.set_calc(
        {
            "calc_str": calc_str,
            "variables": variables,
            "server": server,
            "pv_name": "TEST:PV:CALC",
        }
    )
    return rule, server


class TestCalcRuleConfiguration:
    def test_create_calc_rule(self) -> None:
        rule = CalcRule()

        assert rule.name == "calc"

    def test_set_calc_normalises_single_variable_to_list(self) -> None:
        rule = CalcRule()

        rule.set_calc({"calc_str": "pv[0]+10", "variables": "a:pv:name", "server": "fakeServer", "pv_name": "this:pv:name"})

        assert rule._calc_str == "pv[0]+10"
        assert rule._variables == ["a:pv:name"]
        assert rule._server == "fakeServer"
        assert rule._pv_name == "this:pv:name"

    def test_set_calc_keeps_variable_list(self) -> None:
        rule = CalcRule()

        rule.set_calc({"variables": ["a:pv:name", "b:pv:name"]})

        assert rule._variables == ["a:pv:name", "b:pv:name"]


class TestCalcRuleGetVariables:
    def test_get_variables_returns_values_in_order(self) -> None:
        rule, _ = make_calc_rule("pv[0]", ["a:pv:name", "b:pv:name"], [1.0, 2.0])

        assert rule.get_variables() == [1.0, 2.0]

    def test_get_variables_returns_none_if_a_pv_is_missing(self) -> None:
        rule, _ = make_calc_rule("pv[0]", ["a:pv:name", "b:pv:name"], [1.0, None])

        assert rule.get_variables() is None

    def test_get_variables_returns_none_on_exception(self) -> None:
        rule, server = make_calc_rule("pv[0]", ["a:pv:name"], [1.0])
        server.get_pv_value.side_effect = RuntimeError("boom")

        assert rule.get_variables() is None


class TestCalcRulePostRule:
    def test_post_rule_evaluates_single_variable(self) -> None:
        rule, _ = make_calc_rule("pv[0]+10", "a:pv:name", [1.0])

        old_state: Value = NTScalar("d").wrap(0.0)
        new_state: Value = NTScalar("d").wrap(0.0)

        result = rule.post_rule(old_state, new_state)

        assert result is RulesFlow.CONTINUE
        assert new_state["value"] == 11.0

    def test_post_rule_evaluates_multiple_variables_in_order(self) -> None:
        rule, _ = make_calc_rule("pv[0]+2.12*pv[1]", ["a:pv:name", "b:pv:name"], [3.0, 4.0])

        new_state: Value = NTScalar("d").wrap(0.0)

        rule.post_rule(new_state, new_state)

        assert new_state["value"] == pytest.approx(3.0 + 2.12 * 4.0)

    def test_post_rule_supports_math_module_functions(self) -> None:
        rule, _ = make_calc_rule("pv[0]*m.sin(pv[1])", ["a:pv:name", "b:pv:name"], [3.0, 4.0])

        new_state: Value = NTScalar("d").wrap(0.0)

        rule.post_rule(new_state, new_state)

        assert new_state["value"] == pytest.approx(3.0 * math.sin(4.0))

    def test_post_rule_aborts_if_a_variable_is_missing(self) -> None:
        rule, _ = make_calc_rule("pv[0]", ["a:pv:name"], [None])

        new_state: Value = NTScalar("d").wrap(0.0)

        result = rule.post_rule(new_state, new_state)

        assert result is RulesFlow.ABORT

    @pytest.mark.parametrize(
        "malicious_calc_str",
        [
            "__import__('os').system('echo pwned')",
            "().__class__.__bases__[0].__subclasses__()",
            "open('/etc/passwd').read()",
        ],
    )
    def test_post_rule_rejects_unsafe_expressions(self, malicious_calc_str: str) -> None:
        rule, _ = make_calc_rule(malicious_calc_str, ["a:pv:name"], [1.0])

        new_state: Value = NTScalar("d").wrap(0.0)

        with pytest.raises(InvalidExpression):
            rule.post_rule(new_state, new_state)
