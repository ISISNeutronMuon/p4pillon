from p4p.nt import NTScalar
from p4p.server import Server

from p4p_ext.thread.sharednt import SharedNT

pv = SharedNT(
    nt=NTScalar("d", control=True, valueAlarm=True),  # scalar double
    initial={
        "value": 2.2,  # setting initial value also open()'s
        "control.limitHigh": 10,
        "valueAlarm.active": True,
        "valueAlarm.highWarningLimit": 5,
        "valueAlarm.highWarningSeverity": 1,
        "valueAlarm.highAlarmLimit": 8,
        "valueAlarm.highAlarmSeverity": 2,
    },
)  # setting initial value also open()'s

Server.forever(
    providers=[
        {
            "demo:pv:name": pv,  # PV name only appears here
        }
    ]
)  # runs until KeyboardInterrupt
