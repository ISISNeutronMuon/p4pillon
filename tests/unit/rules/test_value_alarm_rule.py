"""
Regression tests for :class:`p4pillon.rules.ValueAlarmRule` against the
``alarmLimit_t`` / ``valueAlarm_t`` specification in the EPICS Normative Types
document:

    https://github.com/epics-docs/epics-docs/blob/master/pv-access/Normative-Types-Specification.rst

The specification defines the structure as::

    alarmLimit_t :=
    structure
        boolean active
        double lowAlarmLimit
        double lowWarningLimit
        double highWarningLimit
        double highAlarmLimit
        int lowAlarmSeverity
        int lowWarningSeverity
        int highWarningSeverity
        int highAlarmSeverity
        double hysteresis

and prescribes the checking algorithm as, in order, returning at the first match:

    if (!active) return;
    if (highAlarmSeverity   > 0 && value >= highAlarmLimit)   -> "highAlarm"
    if (lowAlarmSeverity    > 0 && value <= lowAlarmLimit)    -> "lowAlarm"
    if (highWarningSeverity > 0 && value >= highWarningLimit) -> "highWarning"
    if (lowWarningSeverity  > 0 && value <= lowWarningLimit)  -> "lowWarning"
    raiseAlarm(0, val, 0, "")

The note in the specification records that pvData implementations name the
structure ``valueAlarm_t`` and permit any integer or floating point scalar type
for the four limit fields, which is what p4p builds -- hence the type matrix
below covers every numeric scalar type and its array form. ``boolean`` and
``string`` NTScalars have no ``valueAlarm`` field in p4p and so are excluded.

Tests marked ``xfail(strict=True)`` describe specified behaviour that is not yet
implemented; they will report XPASS (a failure) once the implementation catches
up, which is the signal to remove the marker.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy
import pytest
from p4p.nt import NTScalar

from p4pillon.definitions import AlarmSeverity, AlarmStatus
from p4pillon.rules import RulesFlow, ScalarToArrayWrapperRule, ValueAlarmRule
from p4pillon.utils import overwrite_unmarked

if TYPE_CHECKING:
    from p4p import Value

# --------------------------------------------------------------------------------------
# Type matrix
# --------------------------------------------------------------------------------------

# p4p type codes for the scalar types that carry a valueAlarm structure. Note that
# p4p follows the struct-module convention where the unsigned types are the
# upper-case forms, so "b" is int8 and "B" is uint8.
SIGNED_INT_CODES = ["b", "h", "i", "l"]
UNSIGNED_INT_CODES = ["B", "H", "I", "L"]
FLOAT_CODES = ["f", "d"]

SCALAR_CODES = SIGNED_INT_CODES + UNSIGNED_INT_CODES + FLOAT_CODES
ARRAY_CODES = ["a" + code for code in SCALAR_CODES]
ALL_CODES = SCALAR_CODES + ARRAY_CODES

# A representative subset for tests of behaviour that does not depend on how the
# value is represented -- check order, alarm clearing, hysteresis, and so on. One
# integer and one float, each in scalar and array form: the array codes exercise
# ScalarToArrayWrapperRule, and the float codes exercise the comparisons that
# integer truncation would otherwise hide. Running these over the full 20-type
# matrix costs a great deal and proves the same thing twenty times.
#
# The full matrix is kept where the type itself is under test: the boundary matrix
# in TestLimitChecks.test_post_rule, TestTypeExtremes, TestFractionalLimits and
# TestApplicability. Between them every type is driven across every limit
# comparison, at its own extremes, and through type introspection, so the rest of
# the file can take the representation as read.
SAMPLE_SCALAR_CODES = ["i", "d"]
SAMPLE_ARRAY_CODES = ["ai", "ad"]
SAMPLE_CODES = SAMPLE_SCALAR_CODES + SAMPLE_ARRAY_CODES

# Inclusive (min, max) of each integer type, used to check the rule behaves at the
# extremes of the value's own type rather than only in the middle of its range.
INTEGER_RANGES: dict[str, tuple[int, int]] = {
    "b": (-(2**7), 2**7 - 1),
    "B": (0, 2**8 - 1),
    "h": (-(2**15), 2**15 - 1),
    "H": (0, 2**16 - 1),
    "i": (-(2**31), 2**31 - 1),
    "I": (0, 2**32 - 1),
    "l": (-(2**63), 2**63 - 1),
    "L": (0, 2**64 - 1),
}

# --------------------------------------------------------------------------------------
# Shared limits
# --------------------------------------------------------------------------------------

# Chosen so every value used in the tests (0..127) is representable in *every* type
# in the matrix: non-negative, so uint8 can hold them, and <= 127 so int8 can too.
LOW_ALARM_LIMIT = 10
LOW_WARNING_LIMIT = 20
HIGH_WARNING_LIMIT = 80
HIGH_ALARM_LIMIT = 90

#: A value comfortably inside the no-alarm band for the limits below.
NEUTRAL = 50

BASE_LIMITS: dict[str, Any] = {
    "active": True,
    "lowAlarmLimit": LOW_ALARM_LIMIT,
    "lowWarningLimit": LOW_WARNING_LIMIT,
    "highWarningLimit": HIGH_WARNING_LIMIT,
    "highAlarmLimit": HIGH_ALARM_LIMIT,
    "lowAlarmSeverity": AlarmSeverity.MAJOR_ALARM.value,
    "lowWarningSeverity": AlarmSeverity.MINOR_ALARM.value,
    "highWarningSeverity": AlarmSeverity.MINOR_ALARM.value,
    "highAlarmSeverity": AlarmSeverity.MAJOR_ALARM.value,
    "hysteresis": 0,
}

NO_ALARM = AlarmSeverity.NO_ALARM
MINOR = AlarmSeverity.MINOR_ALARM
MAJOR = AlarmSeverity.MAJOR_ALARM
INVALID = AlarmSeverity.INVALID_ALARM

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def limits(**overrides: Any) -> dict[str, Any]:
    """Return :data:`BASE_LIMITS` with the given fields replaced."""
    return {**BASE_LIMITS, **overrides}


def is_array(code: str) -> bool:
    """Is this p4p type code an array type?"""
    return code.startswith("a")


def make_rule(code: str) -> ValueAlarmRule | ScalarToArrayWrapperRule:
    """Build the rule appropriate to the type code.

    ``ValueAlarmRule`` sets ``wrap_for_array``, so an NTScalarArray is served by
    the same rule wrapped in a ``ScalarToArrayWrapperRule``.
    """
    return ScalarToArrayWrapperRule(ValueAlarmRule()) if is_array(code) else ValueAlarmRule()


def embed(code: str, value: Any) -> Any:
    """Place a single test value in a form appropriate to the type code.

    For arrays the value is surrounded by no-alarm neighbours, so the aggregate
    alarm reported for the array is the one the single value should produce.
    """
    return [NEUTRAL, value, NEUTRAL] if is_array(code) else value


def uniform(code: str, value: Any) -> Any:
    """As :func:`embed`, but filling the array with the value itself.

    Used where the limits under test are deliberately overlapping, so that
    :data:`NEUTRAL` is not in the no-alarm band and would contribute an alarm of
    its own to the aggregate.
    """
    return [value, value, value] if is_array(code) else value


def build(
    code: str,
    value: Any,
    alarm_limits: dict[str, Any] | None = BASE_LIMITS,
    alarm: dict[str, Any] | None = None,
) -> Value:
    """Wrap a value (and optionally valueAlarm/alarm contents) as an NTScalar Value."""
    nt = NTScalar(code, valueAlarm=alarm_limits is not None)
    contents: dict[str, Any] = {"value": value}
    if alarm_limits is not None:
        contents["valueAlarm"] = alarm_limits
    if alarm is not None:
        contents["alarm"] = alarm
    return nt.wrap(contents)


def run_post(
    code: str,
    new_value: Any,
    alarm_limits: dict[str, Any] | None = BASE_LIMITS,
    *,
    old_value: Any = None,
    old_alarm: dict[str, Any] | None = None,
    new_alarm: dict[str, Any] | None = None,
    new_limits: dict[str, Any] | None = None,
) -> tuple[RulesFlow, Value]:
    """Drive ``post_rule`` and return the flow and the resulting new state.

    ``old_value`` defaults to a no-alarm value of the right shape. ``new_limits``
    allows the incoming post to change the limits as well as the value.
    """
    if old_value is None:
        old_value = embed(code, NEUTRAL)

    old_state = build(code, old_value, alarm_limits, old_alarm)
    new_state = build(code, new_value, new_limits if new_limits is not None else alarm_limits, new_alarm)
    overwrite_unmarked(old_state, new_state)

    return make_rule(code).post_rule(old_state, new_state), new_state


def run_init(
    code: str,
    value: Any,
    alarm_limits: dict[str, Any] | None = BASE_LIMITS,
    alarm: dict[str, Any] | None = None,
) -> tuple[RulesFlow, Value]:
    """Drive ``init_rule`` on a freshly built (fully marked) Value."""
    state = build(code, value, alarm_limits, alarm)
    return make_rule(code).init_rule(state), state


def assert_alarm(state: Value, severity: AlarmSeverity, message: str) -> None:
    """Assert the resulting alarm severity and message."""
    assert state["alarm.severity"] == severity.value
    assert state["alarm.message"] == message


def assert_value(state: Value, expected: Any) -> None:
    """Assert the value survived rule evaluation unchanged."""
    if isinstance(expected, list):
        numpy.testing.assert_array_equal(state["value"], expected)
    else:
        assert state["value"] == expected


# The full boundary matrix for BASE_LIMITS. Every limit comparison in the
# specification is inclusive, so each limit value itself is tested along with the
# values either side of it.
LIMIT_MATRIX = [
    (0, MAJOR, "lowAlarm"),
    (9, MAJOR, "lowAlarm"),
    (10, MAJOR, "lowAlarm"),  # value <= lowAlarmLimit
    (11, MINOR, "lowWarning"),
    (19, MINOR, "lowWarning"),
    (20, MINOR, "lowWarning"),  # value <= lowWarningLimit
    (21, NO_ALARM, ""),
    (50, NO_ALARM, ""),
    (79, NO_ALARM, ""),
    (80, MINOR, "highWarning"),  # value >= highWarningLimit
    (85, MINOR, "highWarning"),
    (89, MINOR, "highWarning"),
    (90, MAJOR, "highAlarm"),  # value >= highAlarmLimit
    (100, MAJOR, "highAlarm"),
    (127, MAJOR, "highAlarm"),
]


class TestLimitChecks:
    """The four limit comparisons, over every type, at and around each boundary."""

    @pytest.mark.parametrize("code", ALL_CODES)
    @pytest.mark.parametrize(("value", "severity", "message"), LIMIT_MATRIX)
    def test_post_rule(self, code, value, severity, message):
        flow, state = run_post(code, embed(code, value))

        assert flow is RulesFlow.CONTINUE
        assert_value(state, embed(code, value))
        assert_alarm(state, severity, message)

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    @pytest.mark.parametrize(("value", "severity", "message"), LIMIT_MATRIX)
    def test_init_rule(self, code, value, severity, message):
        """``init_rule`` has no previous state to compare against but must reach
        the same verdict as ``post_rule`` for the same value.

        Both entry points share the verdict code, and ``test_post_rule`` above runs
        the boundary matrix over every type, so this needs only a sample."""
        flow, state = run_init(code, embed(code, value))

        assert flow is RulesFlow.CONTINUE
        assert_value(state, embed(code, value))
        assert_alarm(state, severity, message)

    @pytest.mark.parametrize("code", ALL_CODES)
    def test_alarm_status_is_not_touched(self, code):
        """The rule owns ``alarm.severity`` and ``alarm.message``; ``alarm.status``
        is set by whatever raised the condition and must be left alone."""
        _flow, state = run_post(
            code,
            embed(code, 100),
            old_alarm={"severity": NO_ALARM.value, "message": "", "status": 4},
        )

        assert state["alarm.status"] == 4


class TestTypeExtremes:
    """Values at the extremes of each type's own range still classify correctly."""

    @pytest.mark.parametrize("code", [*INTEGER_RANGES, *["a" + c for c in INTEGER_RANGES]])
    def test_integer_minimum_is_low_alarm(self, code):
        minimum = INTEGER_RANGES[code.lstrip("a")][0]
        _flow, state = run_post(code, embed(code, minimum))

        assert_alarm(state, MAJOR, "lowAlarm")

    @pytest.mark.parametrize(
        "code",
        [
            *INTEGER_RANGES,
            *[
                pytest.param(
                    "a" + c,
                    marks=pytest.mark.xfail(
                        reason="ScalarToArrayWrapperRule hands numpy.uint64 elements back to p4p, "
                        "which rejects them for a uint64 scalar field ('an integer is required')",
                        strict=True,
                    ),
                )
                if c == "L"
                else "a" + c
                for c in INTEGER_RANGES
            ],
        ],
    )
    def test_integer_maximum_is_high_alarm(self, code):
        maximum = INTEGER_RANGES[code.lstrip("a")][1]
        _flow, state = run_post(code, embed(code, maximum))

        assert_alarm(state, MAJOR, "highAlarm")

    @pytest.mark.parametrize("code", ["f", "d", "af", "ad"])
    @pytest.mark.parametrize(
        ("value", "severity", "message"),
        [
            (float("-inf"), MAJOR, "lowAlarm"),
            (float("inf"), MAJOR, "highAlarm"),
        ],
    )
    def test_float_infinities(self, code, value, severity, message):
        _flow, state = run_post(code, embed(code, value))

        assert_alarm(state, severity, message)

    @pytest.mark.parametrize("code", ["f", "d", "af", "ad"])
    def test_float_nan_is_undefined(self, code):
        """NaN satisfies no limit, so the specification's fall-through would clear
        the alarm. EPICS base instead treats an undefined value as UDF_ALARM at
        severity UDFS -- INVALID_ALARM by default -- before any limit is tested
        (``aiRecord.c``), and p4pillon follows base."""
        _flow, state = run_post(code, embed(code, float("nan")))

        assert_alarm(state, INVALID, "UDF")
        assert state["alarm.status"] == AlarmStatus.UNDEFINED_STATUS

    @pytest.mark.parametrize("code", ["f", "d", "af", "ad"])
    def test_leaving_nan_clears_the_undefined_alarm(self, code):
        """The rule undoes the status it set itself once the value is defined again."""
        _flow, state = run_post(
            code,
            embed(code, NEUTRAL),
            old_value=embed(code, float("nan")),
            old_alarm={
                "severity": INVALID.value,
                "message": "UDF",
                "status": AlarmStatus.UNDEFINED_STATUS.value,
            },
        )

        assert_alarm(state, NO_ALARM, "")
        assert state["alarm.status"] == AlarmStatus.NO_STATUS


class TestFractionalLimits:
    """Floating point limits are compared exactly, not rounded to integers.

    The limits and values here are exact in binary floating point so that the
    single-precision ("f") types behave identically to double.
    """

    FRACTIONAL = limits(
        lowAlarmLimit=10.25,
        lowWarningLimit=20.5,
        highWarningLimit=80.5,
        highAlarmLimit=90.25,
    )

    @pytest.mark.parametrize("code", ["f", "d", "af", "ad"])
    @pytest.mark.parametrize(
        ("value", "severity", "message"),
        [
            (10.25, MAJOR, "lowAlarm"),
            (10.5, MINOR, "lowWarning"),
            (20.5, MINOR, "lowWarning"),
            (20.75, NO_ALARM, ""),
            (80.25, NO_ALARM, ""),
            (80.5, MINOR, "highWarning"),
            (90.0, MINOR, "highWarning"),
            (90.25, MAJOR, "highAlarm"),
        ],
    )
    def test_fractional_boundaries(self, code, value, severity, message):
        _flow, state = run_post(code, embed(code, value), self.FRACTIONAL)

        assert_alarm(state, severity, message)


class TestSeverityZeroDisablesCheck:
    """``if(severity>0 && ...)``: a zero severity switches that limit check off.

    The check is skipped entirely rather than matching with severity zero, so
    evaluation falls through to the next check in the specified order.
    """

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    @pytest.mark.parametrize(
        ("disabled", "value", "severity", "message"),
        [
            # highAlarm off: a high value falls through to highWarning.
            ("highAlarmSeverity", 100, MINOR, "highWarning"),
            # lowAlarm off: a low value falls through to lowWarning.
            ("lowAlarmSeverity", 0, MINOR, "lowWarning"),
            # highWarning off: a value in the warning band raises nothing.
            ("highWarningSeverity", 85, NO_ALARM, ""),
            # lowWarning off: a value in the warning band raises nothing.
            ("lowWarningSeverity", 15, NO_ALARM, ""),
            # A disabled check does not suppress the others.
            ("highAlarmSeverity", 0, MAJOR, "lowAlarm"),
            ("lowAlarmSeverity", 100, MAJOR, "highAlarm"),
        ],
    )
    def test_zero_severity_skips_that_limit(self, code, disabled, value, severity, message):
        _flow, state = run_post(code, embed(code, value), limits(**{disabled: 0}))

        assert_alarm(state, severity, message)

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    @pytest.mark.parametrize("value", [0, 15, 50, 85, 100])
    def test_all_severities_zero_raises_nothing(self, code, value):
        all_off = limits(
            lowAlarmSeverity=0,
            lowWarningSeverity=0,
            highWarningSeverity=0,
            highAlarmSeverity=0,
        )
        _flow, state = run_post(code, embed(code, value), all_off)

        assert_alarm(state, NO_ALARM, "")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    @pytest.mark.parametrize(
        ("severity_field", "value", "message"),
        [
            ("highAlarmSeverity", 100, "highAlarm"),
            ("lowAlarmSeverity", 0, "lowAlarm"),
            ("highWarningSeverity", 85, "highWarning"),
            ("lowWarningSeverity", 15, "lowWarning"),
        ],
    )
    @pytest.mark.parametrize("severity", [MINOR, MAJOR, INVALID])
    def test_configured_severity_is_used_verbatim(self, code, severity_field, value, message, severity):
        """Whatever severity is configured for a limit is the severity raised,
        including INVALID_ALARM -- the rule does not clamp or reinterpret it."""
        configured = limits(
            lowAlarmSeverity=0,
            lowWarningSeverity=0,
            highWarningSeverity=0,
            highAlarmSeverity=0,
        )
        configured[severity_field] = severity.value

        _flow, state = run_post(code, embed(code, value), configured)

        assert_alarm(state, severity, message)


class TestCheckOrder:
    """The specification fixes the order: highAlarm, lowAlarm, highWarning, lowWarning.

    The order is only observable when limits are configured so that more than one
    condition holds at once, which the specification permits. Arrays are filled
    with the value under test rather than padded with :data:`NEUTRAL`, which these
    overlapping limits would themselves put into alarm.
    """

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    def test_high_alarm_beats_low_alarm(self, code):
        """With lowAlarmLimit above highAlarmLimit both alarm checks match; the
        high alarm is tested first and returns."""
        overlapping = limits(highAlarmLimit=80, lowAlarmLimit=100)
        _flow, state = run_post(code, uniform(code, 90), overlapping, old_value=uniform(code, 90))

        assert_alarm(state, MAJOR, "highAlarm")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    def test_high_warning_beats_low_warning(self, code):
        """Same overlap for the warnings, with both alarm checks disabled so the
        warnings are reached."""
        overlapping = limits(
            highAlarmSeverity=0,
            lowAlarmSeverity=0,
            highWarningLimit=80,
            lowWarningLimit=100,
        )
        _flow, state = run_post(code, uniform(code, 90), overlapping, old_value=uniform(code, 90))

        assert_alarm(state, MINOR, "highWarning")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    def test_low_alarm_beats_high_warning(self, code):
        """A value that is both below lowAlarmLimit and above highWarningLimit
        reports lowAlarm: the alarm checks both precede the warning checks."""
        overlapping = limits(highAlarmSeverity=0, lowAlarmLimit=90, highWarningLimit=80)
        _flow, state = run_post(code, uniform(code, 85), overlapping, old_value=uniform(code, 85))

        assert_alarm(state, MAJOR, "lowAlarm")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    def test_order_is_by_position_not_by_severity(self, code):
        """The order is positional. A lowWarning configured as MAJOR does not
        displace a highAlarm configured as MINOR when both conditions hold."""
        inverted = limits(
            highAlarmLimit=80,
            highAlarmSeverity=MINOR.value,
            lowAlarmSeverity=0,
            highWarningSeverity=0,
            lowWarningLimit=100,
            lowWarningSeverity=MAJOR.value,
        )
        _flow, state = run_post(code, uniform(code, 90), inverted, old_value=uniform(code, 90))

        assert_alarm(state, MINOR, "highAlarm")


class TestActive:
    """``active``: is alarming active? If no, then alarms are not raised."""

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    @pytest.mark.parametrize("value", [0, 15, 50, 85, 100])
    def test_inactive_raises_no_alarm(self, code, value):
        _flow, state = run_post(code, embed(code, value), limits(active=False))

        assert_alarm(state, NO_ALARM, "")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    @pytest.mark.parametrize("message", ["lowAlarm", "highAlarm", "highWarning", "lowWarning"])
    def test_deactivating_clears_a_previously_raised_alarm(self, code, message):
        """An alarm raised by this rule is this rule's to clear. Once alarming is
        switched off the value is no longer being checked, so the stale severity
        must not be left latched on the PV."""
        _flow, state = run_post(
            code,
            embed(code, NEUTRAL),
            BASE_LIMITS,
            old_value=embed(code, 100),
            old_alarm={"severity": MAJOR.value, "message": message, "status": 0},
            new_limits=limits(active=False),
        )

        assert_alarm(state, NO_ALARM, "")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    def test_inactive_does_not_latch_an_alarm_for_an_alarming_value(self, code):
        """The value is still outside the limits, but with checking switched off
        no alarm should be reported for it."""
        _flow, state = run_post(
            code,
            embed(code, 100),
            limits(active=False),
            old_value=embed(code, 100),
            old_alarm={"severity": MAJOR.value, "message": "highAlarm", "status": 0},
        )

        assert_alarm(state, NO_ALARM, "")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    def test_reactivating_re_evaluates_the_value(self, code):
        """Switching alarming back on must raise the alarm the current value
        warrants, even though the value itself did not change."""
        _flow, state = run_post(
            code,
            embed(code, 100),
            limits(active=False),
            old_value=embed(code, 100),
            new_limits=BASE_LIMITS,
        )

        assert_alarm(state, MAJOR, "highAlarm")


class TestAlarmClearing:
    """The specification's fall-through, ``raiseAlarm(0, val, 0, "")``."""

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    @pytest.mark.parametrize(
        ("from_value", "from_message", "from_severity"),
        [
            (100, "highAlarm", MAJOR),
            (0, "lowAlarm", MAJOR),
            (85, "highWarning", MINOR),
            (15, "lowWarning", MINOR),
        ],
    )
    def test_returning_to_the_no_alarm_band_clears(self, code, from_value, from_message, from_severity):
        _flow, state = run_post(
            code,
            embed(code, NEUTRAL),
            old_value=embed(code, from_value),
            old_alarm={"severity": from_severity.value, "message": from_message, "status": 0},
        )

        assert_alarm(state, NO_ALARM, "")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    @pytest.mark.parametrize(
        ("to_value", "to_message", "to_severity"),
        [
            (0, "lowAlarm", MAJOR),
            (15, "lowWarning", MINOR),
            (85, "highWarning", MINOR),
        ],
    )
    def test_moving_between_alarm_states_replaces_severity_and_message(self, code, to_value, to_message, to_severity):
        _flow, state = run_post(
            code,
            embed(code, to_value),
            old_value=embed(code, 100),
            old_alarm={"severity": MAJOR.value, "message": "highAlarm", "status": 0},
        )

        assert_alarm(state, to_severity, to_message)

    @pytest.mark.parametrize("code", SAMPLE_SCALAR_CODES)
    def test_no_change_when_already_clear(self, code):
        """Moving within the no-alarm band when no alarm is set must not mark the
        alarm fields as changed -- a needless post to every monitoring client."""
        _flow, state = run_post(code, embed(code, 60), old_value=embed(code, NEUTRAL))

        assert_alarm(state, NO_ALARM, "")
        assert not state.changed("alarm.severity")
        assert not state.changed("alarm.message")

    @pytest.mark.parametrize("code", SAMPLE_ARRAY_CODES)
    @pytest.mark.xfail(
        reason="ValueAlarmRule.gather_init unconditionally writes alarm.severity and "
        "alarm.message, so an array marks them changed on every update even when "
        "the alarm state did not move",
        strict=True,
    )
    def test_no_change_when_already_clear_array(self, code):
        _flow, state = run_post(code, embed(code, 60), old_value=embed(code, NEUTRAL))

        assert_alarm(state, NO_ALARM, "")
        assert not state.changed("alarm.severity")
        assert not state.changed("alarm.message")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    def test_staying_in_the_same_alarm_state_reports_it_consistently(self, code):
        _flow, state = run_post(
            code,
            embed(code, 110),
            old_value=embed(code, 100),
            old_alarm={"severity": MAJOR.value, "message": "highAlarm", "status": 0},
        )

        assert_alarm(state, MAJOR, "highAlarm")


class TestChangingLimits:
    """Changing the limits re-evaluates the current value against them."""

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    @pytest.mark.parametrize(
        ("limit_field", "new_limit", "severity", "message"),
        [
            ("highAlarmLimit", 40, MAJOR, "highAlarm"),
            ("highWarningLimit", 40, MINOR, "highWarning"),
            ("lowAlarmLimit", 60, MAJOR, "lowAlarm"),
            ("lowWarningLimit", 60, MINOR, "lowWarning"),
        ],
    )
    def test_tightening_a_limit_raises_an_alarm(self, code, limit_field, new_limit, severity, message):
        """The value stays at NEUTRAL; only the limit moves across it."""
        _flow, state = run_post(
            code,
            embed(code, NEUTRAL),
            old_value=embed(code, NEUTRAL),
            new_limits=limits(**{limit_field: new_limit}),
        )

        assert_alarm(state, severity, message)

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    def test_relaxing_a_limit_clears_an_alarm(self, code):
        _flow, state = run_post(
            code,
            embed(code, 100),
            old_value=embed(code, 100),
            old_alarm={"severity": MAJOR.value, "message": "highAlarm", "status": 0},
            new_limits=limits(highAlarmLimit=120, highWarningLimit=110),
        )

        assert_alarm(state, NO_ALARM, "")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    def test_raising_a_severity_from_zero_enables_the_check(self, code):
        _flow, state = run_post(
            code,
            embed(code, 100),
            limits(highAlarmSeverity=0, highWarningSeverity=0),
            old_value=embed(code, 100),
            new_limits=limits(highWarningSeverity=0),
        )

        assert_alarm(state, MAJOR, "highAlarm")


class TestExternalAlarms:
    """Alarms this rule did not raise.

    The Normative Types specification does not say how the limit verdict combines
    with an alarm the update already carries. EPICS base maximises:
    ``recGblSetSevrVMsg`` writes only when ``prec->nsev < new_sevr``, so the worst
    severity contributed during a processing cycle wins and the first contributor
    at that severity keeps its message. An INVALID_ALARM supplied with the update
    therefore survives -- not as a special case, but because 3 is the largest
    number in play.
    """

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    @pytest.mark.parametrize("value", [0, 50, 100])
    def test_an_incoming_invalid_alarm_is_preserved(self, code, value):
        _flow, state = run_post(
            code,
            embed(code, value),
            new_alarm={"severity": INVALID.value, "message": "disconnected", "status": 1},
        )

        assert_alarm(state, INVALID, "disconnected")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    def test_a_stale_invalid_alarm_is_not_preserved(self, code):
        """Only an INVALID_ALARM arriving *with* this update is honoured. One left
        over from a previous update carries no assertion about the new value, so
        the limit verdict applies."""
        _flow, state = run_post(
            code,
            embed(code, 100),
            old_alarm={"severity": INVALID.value, "message": "disconnected", "status": 1},
        )

        assert_alarm(state, MAJOR, "highAlarm")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    @pytest.mark.parametrize("value", [85, 15])
    def test_a_worse_incoming_alarm_outranks_the_limit_verdict(self, code, value):
        """A MAJOR_ALARM arriving with a value that is only in a warning band must
        not be downgraded to MINOR_ALARM."""
        _flow, state = run_post(
            code,
            embed(code, value),
            new_alarm={"severity": MAJOR.value, "message": "comm", "status": 1},
        )

        assert_alarm(state, MAJOR, "comm")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    @pytest.mark.parametrize(
        ("value", "message"),
        [(100, "highAlarm"), (0, "lowAlarm")],
    )
    def test_a_worse_limit_verdict_outranks_the_incoming_alarm(self, code, value, message):
        """The other direction: the limits win when they are the worse of the two."""
        _flow, state = run_post(
            code,
            embed(code, value),
            new_alarm={"severity": MINOR.value, "message": "comm", "status": 1},
        )

        assert_alarm(state, MAJOR, message)

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    def test_an_equal_incoming_alarm_keeps_its_message(self, code):
        """On a tie base keeps the first contributor's message, and whatever supplied
        the value contributed before this rule ran."""
        _flow, state = run_post(
            code,
            embed(code, 100),
            new_alarm={"severity": MAJOR.value, "message": "comm", "status": 1},
        )

        assert_alarm(state, MAJOR, "comm")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    def test_an_incoming_alarm_is_honoured_while_inactive(self, code):
        """Deactivating the limit checks clears only the alarm this rule raised."""
        _flow, state = run_post(
            code,
            embed(code, NEUTRAL),
            limits(active=False),
            new_alarm={"severity": MAJOR.value, "message": "comm", "status": 1},
        )

        assert_alarm(state, MAJOR, "comm")


class TestArrayAggregation:
    """An NTScalarArray has one alarm structure for the whole array.

    ``ValueAlarmRule`` is a ``BaseGatherableRule``: the scalar rule runs per element
    and the results are gathered into a single alarm. The gathered alarm is the
    highest severity any element reached, with the message from the first element
    to reach that severity.
    """

    @pytest.mark.parametrize("code", SAMPLE_ARRAY_CODES)
    @pytest.mark.parametrize(
        ("values", "severity", "message"),
        [
            # Highest severity present wins, wherever it sits in the array.
            ([100, 50, 50], MAJOR, "highAlarm"),
            ([50, 100, 50], MAJOR, "highAlarm"),
            ([50, 50, 100], MAJOR, "highAlarm"),
            ([0, 50, 50], MAJOR, "lowAlarm"),
            ([50, 50, 0], MAJOR, "lowAlarm"),
            # A major anywhere outranks a minor anywhere.
            ([85, 100], MAJOR, "highAlarm"),
            ([100, 85], MAJOR, "highAlarm"),
            ([15, 0], MAJOR, "lowAlarm"),
            ([0, 15], MAJOR, "lowAlarm"),
            # Minors only.
            ([50, 85, 50], MINOR, "highWarning"),
            ([50, 15, 50], MINOR, "lowWarning"),
            # Every element clear.
            ([21, 50, 79], NO_ALARM, ""),
            # Single element behaves like the scalar case.
            ([100], MAJOR, "highAlarm"),
            ([50], NO_ALARM, ""),
        ],
    )
    def test_worst_element_determines_the_alarm(self, code, values, severity, message):
        _flow, state = run_post(code, values, old_value=[NEUTRAL] * len(values))

        assert_alarm(state, severity, message)
        assert_value(state, values)

    @pytest.mark.parametrize("code", SAMPLE_ARRAY_CODES)
    @pytest.mark.parametrize(
        ("values", "message"),
        [
            ([100, 0], "highAlarm"),
            ([0, 100], "lowAlarm"),
            ([85, 15], "highWarning"),
            ([15, 85], "lowWarning"),
        ],
    )
    def test_first_element_at_the_worst_severity_supplies_the_message(self, code, values, message):
        """When several elements tie on severity the message is the first one's,
        so the reported message is a deterministic function of the array."""
        _flow, state = run_post(code, values, old_value=[NEUTRAL] * len(values))

        assert state["alarm.message"] == message

    @pytest.mark.parametrize("code", SAMPLE_ARRAY_CODES)
    @pytest.mark.parametrize(("old_length", "new_length"), [(2, 5), (1, 4), (3, 3)])
    def test_array_grows_or_keeps_length(self, code, old_length, new_length):
        """A resized array is evaluated on the elements it now has."""
        values = [NEUTRAL] * (new_length - 1) + [100]
        _flow, state = run_post(code, values, old_value=[NEUTRAL] * old_length)

        assert_alarm(state, MAJOR, "highAlarm")
        assert_value(state, values)

    @pytest.mark.parametrize("code", SAMPLE_ARRAY_CODES)
    @pytest.mark.parametrize(("old_length", "new_length"), [(5, 2), (4, 1)])
    @pytest.mark.xfail(
        reason="ScalarToArrayWrapperRule.post_rule zips old and new with "
        "itertools.zip_longest, so a shrinking array yields a None new value and "
        "raises TypeError; see the TODO in rules.py",
        strict=True,
    )
    def test_array_shrinks(self, code, old_length, new_length):
        values = [NEUTRAL] * (new_length - 1) + [100]
        _flow, state = run_post(code, values, old_value=[NEUTRAL] * old_length)

        assert_alarm(state, MAJOR, "highAlarm")
        assert_value(state, values)

    @pytest.mark.parametrize("code", SAMPLE_ARRAY_CODES)
    def test_every_element_is_checked(self, code):
        """A long array with the only alarming element at the very end."""
        values = [NEUTRAL] * 63 + [100]
        _flow, state = run_post(code, values, old_value=[NEUTRAL] * 64)

        assert_alarm(state, MAJOR, "highAlarm")

    @pytest.mark.parametrize("code", SAMPLE_ARRAY_CODES)
    @pytest.mark.xfail(
        reason="ScalarToArrayWrapperRule iterates value directly, and p4p represents "
        "an empty array as None, so an empty array raises TypeError",
        strict=True,
    )
    def test_empty_array_raises_no_alarm(self, code):
        """No elements means no element is in alarm."""
        flow, state = run_init(code, [])

        assert flow is RulesFlow.CONTINUE
        assert_alarm(state, NO_ALARM, "")

    @pytest.mark.parametrize("code", SAMPLE_ARRAY_CODES)
    def test_array_alarm_clears_when_all_elements_return_to_range(self, code):
        _flow, state = run_post(
            code,
            [NEUTRAL, NEUTRAL, NEUTRAL],
            old_value=[100, 0, NEUTRAL],
            old_alarm={"severity": MAJOR.value, "message": "highAlarm", "status": 0},
        )

        assert_alarm(state, NO_ALARM, "")


class TestHysteresis:
    """``hysteresis``: "When a value enters an alarm limit this is how much it must
    change before it is put into a lower severity state. This prevents alarm chatter."

    The tests below encode the standard EPICS reading of that sentence: hysteresis
    only ever delays *leaving* a state, never entering one. While a state is held,
    the limit that produced it is effectively widened by the hysteresis -- a high
    limit downwards, a low limit upwards -- for the purpose of the test that would
    drop the value to a lower severity.

    Hysteresis needs the previous alarm state, so it is a ``post_rule`` concern only.
    """

    HYSTERESIS = 5
    HYST_LIMITS = limits(hysteresis=HYSTERESIS)

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    @pytest.mark.parametrize(
        ("value", "severity", "message"),
        [
            (100, MAJOR, "highAlarm"),
            (90, MAJOR, "highAlarm"),
            (0, MAJOR, "lowAlarm"),
            (10, MAJOR, "lowAlarm"),
            (85, MINOR, "highWarning"),
            (15, MINOR, "lowWarning"),
            (50, NO_ALARM, ""),
        ],
    )
    def test_hysteresis_does_not_affect_entering_a_state(self, code, value, severity, message):
        """Coming from no alarm, the plain limits apply however large hysteresis is."""
        _flow, state = run_post(code, embed(code, value), self.HYST_LIMITS, old_value=embed(code, NEUTRAL))

        assert_alarm(state, severity, message)

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    @pytest.mark.parametrize(
        ("value", "held_message"),
        [
            # highAlarmLimit is 90; held until the value drops below 90 - 5.
            (89, "highAlarm"),
            (85, "highAlarm"),
        ],
    )
    @pytest.mark.xfail(reason="hysteresis is not implemented; see the TODO in ValueAlarmRule", strict=True)
    def test_high_alarm_is_held_within_hysteresis(self, code, value, held_message):
        _flow, state = run_post(
            code,
            embed(code, value),
            self.HYST_LIMITS,
            old_value=embed(code, 100),
            old_alarm={"severity": MAJOR.value, "message": "highAlarm", "status": 0},
        )

        assert_alarm(state, MAJOR, held_message)

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    def test_high_alarm_is_released_beyond_hysteresis(self, code):
        """84 is below highAlarmLimit - hysteresis (85), so the high alarm drops --
        to highWarning, since 84 is still above highWarningLimit."""
        _flow, state = run_post(
            code,
            embed(code, 84),
            self.HYST_LIMITS,
            old_value=embed(code, 100),
            old_alarm={"severity": MAJOR.value, "message": "highAlarm", "status": 0},
        )

        assert_alarm(state, MINOR, "highWarning")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    @pytest.mark.parametrize("value", [11, 15])
    @pytest.mark.xfail(reason="hysteresis is not implemented; see the TODO in ValueAlarmRule", strict=True)
    def test_low_alarm_is_held_within_hysteresis(self, code, value):
        """lowAlarmLimit is 10; held until the value rises above 10 + 5."""
        _flow, state = run_post(
            code,
            embed(code, value),
            self.HYST_LIMITS,
            old_value=embed(code, 0),
            old_alarm={"severity": MAJOR.value, "message": "lowAlarm", "status": 0},
        )

        assert_alarm(state, MAJOR, "lowAlarm")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    def test_low_alarm_is_released_beyond_hysteresis(self, code):
        """16 is above lowAlarmLimit + hysteresis (15), so the low alarm drops --
        to lowWarning, since 16 is still at or below lowWarningLimit."""
        _flow, state = run_post(
            code,
            embed(code, 16),
            self.HYST_LIMITS,
            old_value=embed(code, 0),
            old_alarm={"severity": MAJOR.value, "message": "lowAlarm", "status": 0},
        )

        assert_alarm(state, MINOR, "lowWarning")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    @pytest.mark.parametrize("value", [79, 76])
    @pytest.mark.xfail(reason="hysteresis is not implemented; see the TODO in ValueAlarmRule", strict=True)
    def test_high_warning_is_held_within_hysteresis(self, code, value):
        """highWarningLimit is 80; held until the value drops below 80 - 5."""
        _flow, state = run_post(
            code,
            embed(code, value),
            self.HYST_LIMITS,
            old_value=embed(code, 85),
            old_alarm={"severity": MINOR.value, "message": "highWarning", "status": 0},
        )

        assert_alarm(state, MINOR, "highWarning")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    def test_high_warning_is_released_beyond_hysteresis(self, code):
        _flow, state = run_post(
            code,
            embed(code, 74),
            self.HYST_LIMITS,
            old_value=embed(code, 85),
            old_alarm={"severity": MINOR.value, "message": "highWarning", "status": 0},
        )

        assert_alarm(state, NO_ALARM, "")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    @pytest.mark.parametrize("value", [21, 25])
    @pytest.mark.xfail(reason="hysteresis is not implemented; see the TODO in ValueAlarmRule", strict=True)
    def test_low_warning_is_held_within_hysteresis(self, code, value):
        """lowWarningLimit is 20; held until the value rises above 20 + 5."""
        _flow, state = run_post(
            code,
            embed(code, value),
            self.HYST_LIMITS,
            old_value=embed(code, 15),
            old_alarm={"severity": MINOR.value, "message": "lowWarning", "status": 0},
        )

        assert_alarm(state, MINOR, "lowWarning")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    def test_low_warning_is_released_beyond_hysteresis(self, code):
        _flow, state = run_post(
            code,
            embed(code, 26),
            self.HYST_LIMITS,
            old_value=embed(code, 15),
            old_alarm={"severity": MINOR.value, "message": "lowWarning", "status": 0},
        )

        assert_alarm(state, NO_ALARM, "")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    def test_escalating_severity_ignores_hysteresis(self, code):
        """Hysteresis delays only the move to a *lower* severity. A value moving
        from highWarning into the high alarm band raises immediately."""
        _flow, state = run_post(
            code,
            embed(code, 90),
            self.HYST_LIMITS,
            old_value=embed(code, 85),
            old_alarm={"severity": MINOR.value, "message": "highWarning", "status": 0},
        )

        assert_alarm(state, MAJOR, "highAlarm")

    @pytest.mark.parametrize("code", SAMPLE_CODES)
    @pytest.mark.parametrize("value", [50, 84, 16])
    def test_zero_hysteresis_holds_nothing(self, code, value):
        """The default. Included so the hysteresis tests above are known to be
        exercising hysteresis rather than the plain limits."""
        _flow, state = run_post(
            code,
            embed(code, value),
            limits(hysteresis=0),
            old_value=embed(code, 100),
            old_alarm={"severity": MAJOR.value, "message": "highAlarm", "status": 0},
        )

        assert state["alarm.severity"] != MAJOR.value


class TestApplicability:
    """When the rule should and should not run at all."""

    @pytest.mark.parametrize("code", ALL_CODES)
    def test_applies_to_a_type_with_valuealarm(self, code):
        assert ValueAlarmRule.applies_to(NTScalar(code, valueAlarm=True).type()) is True

    @pytest.mark.parametrize("code", ALL_CODES)
    def test_does_not_apply_to_a_type_without_valuealarm(self, code):
        assert ValueAlarmRule.applies_to(NTScalar(code).type()) is False

    @pytest.mark.parametrize("code", ALL_CODES)
    def test_no_valuealarm_field_leaves_the_alarm_alone(self, code):
        flow, state = run_post(code, embed(code, 100), alarm_limits=None)

        assert flow is RulesFlow.CONTINUE
        assert_alarm(state, NO_ALARM, "")

    @pytest.mark.parametrize("code", ALL_CODES)
    def test_nothing_changed_means_not_applicable(self, code):
        state = build(code, embed(code, 100))
        state.unmark()

        assert make_rule(code).is_applicable(state) is False

    @pytest.mark.parametrize("code", ALL_CODES)
    def test_a_value_change_makes_the_rule_applicable(self, code):
        old_state = build(code, embed(code, NEUTRAL))
        new_state = build(code, embed(code, 100))
        overwrite_unmarked(old_state, new_state)

        assert make_rule(code).is_applicable(new_state) is True

    @pytest.mark.parametrize("code", ALL_CODES)
    def test_a_valuealarm_change_alone_makes_the_rule_applicable(self, code):
        """Limits can move under a value that has not itself changed."""
        old_state = build(code, embed(code, NEUTRAL))
        new_state = build(code, embed(code, NEUTRAL), limits(highAlarmLimit=40))
        overwrite_unmarked(old_state, new_state)
        new_state.mark("value", False)

        assert make_rule(code).is_applicable(new_state) is True

    def test_rule_metadata(self):
        assert ValueAlarmRule.name == "alarm_limit"
        assert ValueAlarmRule.fields == ["alarm", "valueAlarm"]
        assert ValueAlarmRule.wrap_for_array is True

    def test_array_wrapper_reports_the_wrapped_rule_metadata(self):
        rule = ScalarToArrayWrapperRule(ValueAlarmRule())

        assert rule.name == "alarm_limit"
        assert rule.fields == ["alarm", "valueAlarm"]
