import time
from typing import Any

from p4p.client.thread import Context


def put_different_value_scalar(ctx: Context, pvname: str) -> tuple[str | Any, float]:
    """
    Change the value of a process variable (PV) to ensure it is different from its current value.

    Parameters:
    -----------
    ctx : Context
        The context object that provides methods to get and put the value of the PV.
    pvname : str
        The name of the PV whose value is to be changed.

    Returns:
    --------
    tuple
        A tuple containing the new value of the PV and the Unix timestamp when the update was made.

    Example:
    --------
    >>> ctx = Context()
    >>> pvname = "temperature_sensor_1"
    >>> new_value, timestamp = put_different_value(ctx, pvname)
    >>> print(f"New value: {new_value}, Updated at: {timestamp}")
    """
    current_val = ctx.get(pvname).raw.todict()["value"]
    if isinstance(current_val, str):
        put_val = current_val + "1"
    else:
        put_val = current_val + 1
    put_timestamp = time.time()
    ctx.put(pvname, put_val)
    time.sleep(0.1)
    return put_val, put_timestamp


def put_metadata(ctx: Context, pvname: str, field: str, value):
    """
    Update the metadata of a process variable in the given context and return the timestamp of the update.

    Parameters:
    -----------
    ctx : Context
        The context object that provides the method to update the PV.
    pvname : str
        The name of the PV whose metadata is to be updated.
    field : str
        The specific metadata field that needs to be updated. For subfields use dot notation e.g. valueAlarm.highAlarmLimit
    value
        The value to set for the specified metadata field. The type of this value can vary based on the field.

    Returns:
    --------
    float
        The Unix timestamp when the metadata was updated.

    Example:
    --------
    >>> ctx = Context()
    >>> pvname = "temperature_sensor_1"
    >>> field = "display.units"
    >>> value = "Celsius"
    >>> timestamp = put_metadata(ctx, pvname, field, value)
    >>> print(f"Metadata updated at {timestamp}")
    """
    put_timestamp = time.time()
    ctx.put(
        pvname,
        {field: value},
    )
    time.sleep(0.1)
    return put_timestamp


def put_different_value_enum(ctx: Context, pvname: str) -> tuple[dict | Any, float]:
    """
    Change the value of an Enum process variable (PV) to ensure it is different from its current value.

    Parameters:
    -----------
    ctx : Context
        The context object that provides methods to get and put the value of the PV.
    pvname : str
        The name of the PV whose value is to be changed.

    Returns:
    --------
    tuple
        A tuple containing the new value of the PV and the Unix timestamp when the update was made.

    Example:
    --------
    >>> ctx = Context()
    >>> pvname = "valve_status_1"
    >>> new_value, timestamp = put_different_value(ctx, pvname)
    >>> print(f"New value: {new_value}, Updated at: {timestamp}")
    """
    current_val = ctx.get(pvname).raw.todict()["value"]
    current_val["index"] = not (current_val["index"])
    # put_val = {"index": , "choices": current_val["choices"]}
    put_timestamp = time.time()
    ctx.put(pvname, current_val["index"])
    time.sleep(0.1)
    return current_val, put_timestamp
