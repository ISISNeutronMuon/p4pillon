import math
from unittest.mock import patch

import pytest
from p4p.nt import NTScalar

from p4pillon.composite_handler import CompositeHandler
from p4pillon.definitions import MAX_FLOAT, MAX_INT32, MIN_FLOAT, MIN_INT32, AlarmSeverity, Format, PVTypes
from p4pillon.thread.pvrecipe import PVEnumRecipe, PVScalarArrayRecipe, PVScalarRecipe


@pytest.mark.parametrize(
    "pvtype, display_config, expected_values",
    [
        (
            # passing an empty display dictionary gives the defaults
            PVTypes.INTEGER,
            {},
            (MIN_INT32, MAX_INT32, "", Format.DEFAULT, 2),
        ),
        (
            PVTypes.INTEGER,
            {"units": "V"},
            (MIN_INT32, MAX_INT32, "V", Format.DEFAULT, 2),
        ),
        (
            PVTypes.INTEGER,
            {"format": Format.ENGINEERING},
            (MIN_INT32, MAX_INT32, "", Format.ENGINEERING, 2),
        ),
        (
            PVTypes.DOUBLE,
            {"units": "V"},
            (MIN_FLOAT, MAX_FLOAT, "V", Format.DEFAULT, 2),
        ),
        (
            PVTypes.DOUBLE,
            {"low": -1.0, "high": 1.0},
            (-1.0, 1.0, "", Format.DEFAULT, 2),
        ),
        (
            PVTypes.DOUBLE,
            {"precision": 4},
            (MIN_FLOAT, MAX_FLOAT, "", Format.DEFAULT, 4),
        ),
        (
            PVTypes.DOUBLE,
            {"format": "ENGINEERING"},
            (MIN_FLOAT, MAX_FLOAT, "", Format.ENGINEERING, 2),
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
    "pvtype, time_val",
    [
        pytest.param(
            PVTypes.INTEGER,
            123.456,
            marks=pytest.mark.xfail,
        ),  # Issue with _wrap preventing timestamp setting
        pytest.param(
            PVTypes.DOUBLE,
            123.456,
            marks=pytest.mark.xfail,
        ),  # Issue with _wrap preventing timestamp setting
        (PVTypes.INTEGER, None),
        (PVTypes.DOUBLE, None),
    ],
)
@patch("time.time", return_value=456.789)
def test_ntscalar_timestamp(mock_time, pvtype, time_val):
    for recipetype in [PVScalarRecipe, PVScalarArrayRecipe]:
        recipe = recipetype(pvtype, description="test PV", initial_value=0)

        assert recipe.timestamp is None

        if time_val is not None:
            recipe.set_timestamp(time_val)
            assert recipe.timestamp.time == time_val
        else:
            assert recipe.timestamp is None

        pv = recipe.create_pv("TEST:NAME")

        if time_val is not None:
            # once we've added the PVs and started the server, the PV timestamp should be respected
            print(pv.current().timestamp, time_val)
            assert math.isclose(pv.current().timestamp, time_val)
        else:
            # if the timestamp isn't set, we use the default time.time return val
            assert math.isclose(pv.current().timestamp, mock_time.return_value)


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


def test_ntscalar_enum_error():
    with pytest.raises(ValueError) as e:
        PVScalarRecipe(PVTypes.ENUM, description="test", initial_value=1)

    assert "Unsupported pv type" in str(e)


@pytest.mark.parametrize(
    "recipe, pvtype, with_limits, expected_value",
    [
        (PVScalarRecipe, PVTypes.DOUBLE, True, 1),
        (PVScalarRecipe, PVTypes.INTEGER, True, 1),
        (PVScalarRecipe, PVTypes.DOUBLE, False, 1),
        (PVScalarRecipe, PVTypes.INTEGER, False, 1),
        (PVScalarArrayRecipe, PVTypes.DOUBLE, True, [1]),
        (PVScalarArrayRecipe, PVTypes.INTEGER, True, [1]),
        (PVScalarArrayRecipe, PVTypes.DOUBLE, False, [1]),
        (PVScalarArrayRecipe, PVTypes.INTEGER, False, [1]),
    ],
)
@patch("time.time")
def test_ntscalar_numeric_create_pv(mock_time, recipe, pvtype, with_limits, expected_value):
    mock_time.return_value = 123.456
    initial = 1.0
    recipe = recipe(pvtype, description="test", initial_value=initial)

    if with_limits:
        recipe.set_display_limits()
        recipe.set_control_limits()
        recipe.set_alarm_limits()

    pv = recipe.create_pv(pv_name="UNIT:TEST:PV")

    pvdict = pv.current().raw.todict()

    assert isinstance(pv._handler, CompositeHandler)
    assert list(pv._handler.keys()) == ["control", "alarm", "alarm_limit", "timestamp"]
    assert isinstance(pv.nt, NTScalar)  # change to check the name instead?
    assert pv.isOpen() is True

    assert pv.current().real == expected_value
    assert pv.current().timestamp == mock_time.return_value
    assert pvdict.get("alarm") is not None
    if with_limits:
        assert pvdict.get("display") is not None
        assert pvdict.get("control") is not None
        assert pvdict.get("valueAlarm") is not None
    else:
        assert pvdict.get("display") is None
        assert pvdict.get("control") is None
        assert pvdict.get("valueAlarm") is None


@pytest.mark.parametrize(
    "recipe, expected_value",
    [
        (PVScalarRecipe, "test"),
        # TODO work out how to fix this - currently failing with error:
        # ValueError: Unable to wrap ['test'] with <bound method NTScalar.wrap of <p4p.nt.scalar.NTScalar
        pytest.param(
            PVScalarArrayRecipe,
            ["test"],
            marks=pytest.mark.xfail,
        ),
    ],
)
@patch("time.time")
def test_ntscalar_string_create_pv(mock_time, recipe, expected_value):
    mock_time.return_value = 123.456
    initial = "test"
    recipe = recipe(PVTypes.STRING, description="test", initial_value=initial)

    pv = recipe.create_pv(pv_name="UNIT:TEST:PV")

    pvdict = pv.current().raw.todict()

    assert isinstance(pv._handler, CompositeHandler)
    assert list(pv._handler.keys()) == ["control", "alarm", "alarm_limit", "timestamp"]
    assert isinstance(pv.nt, NTScalar)
    assert pv.isOpen() is True
    assert pv.current().timestamp == mock_time.return_value
    assert pvdict["value"] == expected_value
    assert pvdict.get("alarm") is not None
    # string PVs shouldn't have any of these fields
    assert pvdict.get("display") is None
    assert pvdict.get("control") is None
    assert pvdict.get("valueAlarm") is None


@pytest.mark.parametrize(
    "pvtype",
    [(PVTypes.DOUBLE), (PVTypes.INTEGER), (PVTypes.STRING)],
)
def test_ntenum_bad_types(pvtype):
    with pytest.raises(ValueError) as e:
        PVEnumRecipe(pvtype, description="test enum", initial_value={"index": 0, "choices": ["OFF", "ON"]})

    assert "Unsupported pv type" in str(e)


@patch("time.time")
def test_ntenum_create_pv(mock_time):
    mock_time.return_value = 123.456

    recipe = PVEnumRecipe(PVTypes.ENUM, description="test enum", initial_value={"index": 0, "choices": ["OFF", "ON"]})

    pv = recipe.create_pv("TEST:PV:ENUM")

    pvdict = pv.current().raw.todict()

    assert pv.isOpen()
    assert isinstance(pv._handler, CompositeHandler)
    assert list(pv.handler.keys()) == ["alarm", "alarmNTEnum", "timestamp"]
    assert pv.nt.type.getID() == "epics:nt/NTEnum:1.0"
    assert pv.isOpen() is True
    assert pv.current().timestamp == mock_time.return_value
    assert pvdict["value"] == {"index": 0, "choices": ["OFF", "ON"]}
    assert pvdict.get("alarm") is not None
    # enum PVs shouldn't have any of these fields
    assert pvdict.get("display") is None
    assert pvdict.get("control") is None
    assert pvdict.get("valueAlarm") is None


def test_ntenum_extras():
    recipe = PVEnumRecipe(PVTypes.ENUM, description="test enum", initial_value={"index": 0, "choices": ["OFF", "ON"]})

    # check display
    assert recipe.display is None
    with pytest.raises(AttributeError):
        recipe.set_display_limits()

    # check control
    assert recipe.control is None
    with pytest.raises(AttributeError):
        recipe.set_control_limits()

    # check valueAlarm
    assert recipe.alarm_limit is None
    with pytest.raises(AttributeError):
        recipe.set_alarm_limits()
