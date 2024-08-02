import sys
from pathlib import Path

import pytest

root_dir = Path(__file__).parents[2]

sys.path.append(str(root_dir))
from p4p_for_isis.definitions import (
    MAX_FLOAT,
    MAX_INT32,
    MIN_FLOAT,
    MIN_INT32,
    AlarmSeverity,
    Format,
    PVTypes,
)
from p4p_for_isis.pvrecipe import PVScalarArrayRecipe, PVScalarRecipe


@pytest.mark.parametrize(
    "pvtype, display_config, expected_values",
    [
        (
            # passing an empty display dictionary gives the defaults
            PVTypes.INTEGER,
            {},
            (MIN_INT32, MAX_INT32, "", Format.DEFAULT, -1),
        ),
        (
            PVTypes.INTEGER,
            {"units": "V"},
            (MIN_INT32, MAX_INT32, "V", Format.DEFAULT, -1),
        ),
        (
            PVTypes.INTEGER,
            {"format": Format.ENGINEERING},
            (MIN_INT32, MAX_INT32, "", Format.ENGINEERING, -1),
        ),
        (
            PVTypes.DOUBLE,
            {"units": "V"},
            (MIN_FLOAT, MAX_FLOAT, "V", Format.DEFAULT, -1),
        ),
        (
            PVTypes.DOUBLE,
            {"low": -1.0, "high": 1.0},
            (-1.0, 1.0, "", Format.DEFAULT, -1),
        ),
        (
            PVTypes.DOUBLE,
            {"precision": 4},
            (MIN_FLOAT, MAX_FLOAT, "", Format.DEFAULT, 4),
        ),
        (
            PVTypes.DOUBLE,
            {"format": "ENGINEERING"},
            (MIN_FLOAT, MAX_FLOAT, "", Format.ENGINEERING, -1),
        ),
    ],
)
def test_ntscalar_display(pvtype, display_config, expected_values):
    for recipetype in [PVScalarRecipe, PVScalarArrayRecipe]:
        recipe = recipetype(pvtype, description="test PV", initial_value=0)

        assert recipe.display is None

        recipe.set_display_limits(**display_config)

        assert recipe.display.limit_low == expected_values[0]
        assert recipe.display.limit_high == expected_values[1]
        assert recipe.display.units == expected_values[2]
        assert recipe.display.format is expected_values[3]
        assert recipe.display.precision == expected_values[4]


@pytest.mark.parametrize(
    "pvtype, control_config, expected_values",
    [
        (
            PVTypes.INTEGER,
            {},
            (
                MIN_INT32,
                MAX_INT32,
                0,
            ),
        ),
        (
            PVTypes.INTEGER,
            {"low": -5, "high": 5, "min_step": 1},
            (
                -5,
                5,
                1,
            ),
        ),
        (
            PVTypes.DOUBLE,
            {},
            (
                MIN_FLOAT,
                MAX_FLOAT,
                0,
            ),
        ),
        (
            PVTypes.DOUBLE,
            {"low": -5, "high": 5, "min_step": 0.1},
            (
                -5,
                5,
                0.1,
            ),
        ),
    ],
)
def test_ntscalar_control(pvtype, control_config, expected_values):
    for recipetype in [PVScalarRecipe, PVScalarArrayRecipe]:
        recipe = recipetype(pvtype, description="test PV", initial_value=0)

        assert recipe.control is None

        recipe.set_control_limits(**control_config)

        assert recipe.control.limit_low == expected_values[0]
        assert recipe.control.limit_high == expected_values[1]
        assert recipe.control.min_step == expected_values[2]


@pytest.mark.parametrize(
    "pvtype, alarm_config, expected_values",
    [
        (
            PVTypes.INTEGER,
            {},
            (MIN_INT32, MIN_INT32, MAX_INT32, MAX_INT32),
        ),
        (
            PVTypes.INTEGER,
            {"low_alarm": -5, "low_warning": -3, "high_alarm": 5, "high_warning": 3},
            (-5, -3, 3, 5),
        ),
        (
            # TODO confirm if this is the right behaviour?
            PVTypes.INTEGER,
            {
                "low_alarm": -5,
                "high_alarm": 5,
            },
            (-5, MIN_INT32, MAX_INT32, 5),
        ),
        (
            PVTypes.INTEGER,
            {"low_alarm": -5, "low_warning": 5},
            (-5, 5, MAX_INT32, MAX_INT32),
        ),
        (
            PVTypes.DOUBLE,
            {},
            (MIN_FLOAT, MIN_FLOAT, MAX_FLOAT, MAX_FLOAT),
        ),
        (
            PVTypes.DOUBLE,
            {"low_alarm": -5, "low_warning": -3, "high_alarm": 5, "high_warning": 3},
            (-5, -3, 3, 5),
        ),
        (
            # TODO confirm if this is the right behaviour?
            PVTypes.DOUBLE,
            {
                "low_alarm": -5,
                "high_alarm": 5,
            },
            (-5, MIN_FLOAT, MAX_FLOAT, 5),
        ),
        (
            PVTypes.DOUBLE,
            {"low_alarm": -5, "low_warning": 5},
            (-5, 5, MAX_FLOAT, MAX_FLOAT),
        ),
    ],
)
def test_ntscalar_alarm_limit(pvtype, alarm_config, expected_values):
    for recipetype in [PVScalarRecipe, PVScalarArrayRecipe]:
        recipe = recipetype(pvtype, description="test PV", initial_value=0)

        assert recipe.alarm_limit is None

        recipe.set_alarm_limits(**alarm_config)

        assert recipe.alarm_limit.low_alarm_limit == expected_values[0]
        assert recipe.alarm_limit.low_warning_limit == expected_values[1]
        assert recipe.alarm_limit.high_warning_limit == expected_values[2]
        assert recipe.alarm_limit.high_alarm_limit == expected_values[3]
        assert recipe.alarm_limit.low_alarm_severity == AlarmSeverity.MAJOR_ALARM
        assert recipe.alarm_limit.low_warning_severity == AlarmSeverity.MINOR_ALARM
        assert recipe.alarm_limit.high_warning_severity == AlarmSeverity.MINOR_ALARM
        assert recipe.alarm_limit.high_alarm_severity == AlarmSeverity.MAJOR_ALARM
        assert recipe.alarm_limit.hysteresis == 0


def test_ntscalar_string_errors():
    # string NTScalars don't support any of the standard numeric NTScalar fields like display,
    # control or alarm limits
    for recipetype in [PVScalarRecipe, PVScalarArrayRecipe]:
        recipe = recipetype(PVTypes.STRING, description="test PV", initial_value=0)

        # check display
        assert recipe.display is None
        with pytest.raises(SyntaxError) as e:
            recipe.set_display_limits()
        assert "not supported" in str(e)

        # check control
        assert recipe.control is None
        with pytest.raises(SyntaxError) as e:
            recipe.set_control_limits()
        assert "not supported" in str(e)

        # check valueAlarm
        assert recipe.alarm_limit is None
        with pytest.raises(SyntaxError) as e:
            recipe.set_alarm_limits()
        assert "not supported" in str(e)
