from p4p.nt import NTScalar
from p4p.server import Server

from p4p_ext.thread.sharednt import SharedNT

pv = SharedNT(
    nt=NTScalar(
        "d",
        valueAlarm=True,
    ),  # scalar double
    initial=0.0,
)  # setting initial value also open()'s
pv.post(
    {"valueAlarm.active": True, "valueAlarm.highAlarmLimit": 17},
)

Server.forever(
    providers=[
        {
            "demo:pv:name": pv,  # PV name only appears here
        }
    ]
)  # runs until KeyboardInterrupt
