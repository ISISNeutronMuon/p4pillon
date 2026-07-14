import time

from p4p.nt import NTScalar

from p4pillon.asyncio.server import Server
from p4pillon.asyncio.sharednt import SharedNT  # type: ignore

pv = SharedNT(
    nt=NTScalar(
        "d",
        valueAlarm=True,
    ),  # scalar double
    initial={"value": 4.5, "valueAlarm.active": True, "valueAlarm.highAlarmLimit": 17},
)  # setting initial value also open()'s

my_server = Server(prefix="DEV:")
my_server._pvs["demo:pv:name"] = pv
my_server.start()

print(my_server.pvlist)

try:
    while True:
        # Once the server is running, you should be able to update values of the PVs
        # it is hosting through pvput calls (either directly through CLI, Phoebus or
        # the p4p Client)
        time.sleep(5)
except KeyboardInterrupt:
    pass
finally:
    my_server.stop()
