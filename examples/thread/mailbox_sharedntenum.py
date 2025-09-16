from p4p.server import Server

from p4pillon.definitions import AlarmDict, AlarmSeverity, AlarmStatus
from p4pillon.nt import NTEnum
from p4pillon.thread.sharednt import SharedNT

pv = SharedNT(
    nt=NTEnum(display=True),  # scalar double
    initial={
        "value.index": 0,
        "value.choices": ["STOP", "START", "STANDBY"],
        "display.description": "Pump on/off control word.",
    },
    handler_constructors={
        "alarmNTEnum": {
            "STOP": AlarmDict(
                severity=AlarmSeverity.MAJOR_ALARM, status=AlarmStatus.NO_STATUS, message="Shouldn't be off"
            )
        }
    },
)  # setting initial value also open()'s

Server.forever(
    providers=[
        {
            "demo:pv:name": pv,
        }
    ]
)  # runs until KeyboardInterrupt
