from p4p.server import Server

from p4pillon.nt import NTEnum
from p4pillon.thread.sharednt import SharedNT

pv = SharedNT(
    nt=NTEnum(display=True),  # scalar double
    initial={
        "value.index": 0,
        "value.choices": ["STOP", "START", "STANDBY"],
        "display.description": "Pump on/off control word.",
    },
)  # setting initial value also open()'s

Server.forever(
    providers=[
        {
            "demo:pv:name": pv,
        }
    ]
)  # runs until KeyboardInterrupt
