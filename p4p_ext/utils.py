"""Utility function for P4P for ISIS"""


def validate_pv_name(pv_name: str):
    """function to determine whether a PV conforms to the ISIS PV naming convention"""
    return pv_name


def time_in_seconds_and_nanoseconds(timestamp: float) -> tuple[int, int]:
    """Convert a timestamp into separate integer seconds and nanoseconds"""
    seconds = int(timestamp // 1)
    nanoseconds = int((timestamp % 1) * 1e9)
    return seconds, nanoseconds
