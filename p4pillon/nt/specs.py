"""
Specifications for various Normative Type types and fields
"""

import re

###
# NTBase_required are used for identification.
# The key:value pairs are required_field:regex
ntscalar_required = {"value": re.compile("[?sbBhHiIlLfd]{1}")}

ntscalararray_required = {"value": re.compile("a[?sbBhHiIlLfd]{1}")}

ntenum_required = {
    "value": {
        "index": re.compile("i"),
        "choices": re.compile("as"),
    }
}

ntndarray_required = {
    "value": {
        "booleanValue": "a?",
        "byteValue": "ab",
        "shortValue": "ah",
        "intValue": "ai",
        "longValue": "al",
        "ubyteValue": "aB",
        "ushortValue": "aH",
        "uintValue": "aI",
        "ulongValue": "aL",
        "floatValue": "af",
        "doubleValue": "ad",
    },
    "codec": {"name": re.compile("s")},
    "compressedSize": re.compile("l"),
    "uncompressedSize": re.compile("l"),
    "dimension": {
        "size": "i",
        "offset": "i",
        "fullSize": "i",
        "binning": "i",
        "reverse": "?",
    },
    "uniqueId": re.compile("i"),
    "dataTimeStamp": {"secondsPastEpoch": re.compile("l"), "nanoseconds": re.compile("i")},
    "attribute": re.compile(".*"),
}

nttable_required = {"labels": re.compile("as"), "value": {}}

###
# Fieldspecs can be used to construct Types
alarm_fieldspec = [
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

valuealarm_fieldspec = [
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

control_fieldspec = [
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

timestamp_fieldspec = [
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
