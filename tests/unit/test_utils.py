from p4p_for_isis.utils import time_in_seconds_and_nanoseconds


def test_time_in_seconds_and_nanoseconds():
    seconds, nanoseconds = time_in_seconds_and_nanoseconds(123.456)
    assert seconds == 123
    assert nanoseconds == 456000000
