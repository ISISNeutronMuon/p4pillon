"""
Specifications for various Normative Type fields
"""

alarm_typespec = [
    (
        "alarm",
        (
            "S",
            "alarm_t",
            [
                ("severity", "i"),
                ("status", "i"),
                ("message", "s"),
            ],
        ),
    )
]

valuealarm_typespec = [
    (
        "valueAlarm",
        (
            "S",
            "valueAlarm_t",
            [
                ("active", "b"),
                ("lowAlarmLimit", "d"),
                ("lowWarningLimit", "d"),
                ("highWarningLimit", "d"),
                ("highAlarmLimit", "d"),
                ("lowAlarmSeverity", "i"),
                ("lowWarningSeverity", "i"),
                ("highWarningSeverity", "i"),
                ("highAlarmSeverity", "i"),
                ("hysteresis", "d"),
            ],
        ),
    )
]

control_typespec = [
    (
        "control",
        (
            "S",
            "control_t",
            [
                ("limitLow", "d"),
                ("limitHigh", "d"),
                ("minStep", "d"),
            ],
        ),
    )
]

timestamp_typespec = [
    (
        "timeStamp",
        (
            "S",
            "time_t",
            [
                ("secondsPastEpoch", "l"),
                ("nanoseconds", "i"),
            ],
        ),
    )
]
