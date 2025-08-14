from p4p.nt import NTScalar
from p4p.server import Server
from p4p.server.thread import SharedPV

pv = SharedPV(
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


@pv.put
def handle(pv, op):
    pv.post(op.value())  # just store and update subscribers
    op.done()


Server.forever(
    providers=[
        {
            "demo:pv:name": pv,  # PV name only appears here
        }
    ]
)  # runs until KeyboardInterrupt
