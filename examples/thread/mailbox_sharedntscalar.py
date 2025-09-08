from p4p.nt import NTScalar
from p4p.server import Server

from p4pillon.thread.sharednt import SharedNT

pv = SharedNT(
    nt=NTScalar(
        "d",
        valueAlarm=True,
    ),  # scalar double
    initial={"value": 4.5, "valueAlarm.active": True, "valueAlarm.highAlarmLimit": 17},
)  # setting initial value also open()'s


Server.forever(
    providers=[
        {
            "demo:pv:name": pv,  # PV name only appears here
        }
    ]
)  # runs until KeyboardInterrupt
