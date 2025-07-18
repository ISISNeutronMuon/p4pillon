import logging
import time

from p4p_ext.definitions import PVTypes
from p4p_ext.pvrecipe import PVScalarRecipe
from p4p_ext.server import NTServer

logging.basicConfig(level=logging.DEBUG)

server = NTServer(
    ioc_name="TESTIOC",
    section="controls testing",
    description="server for demonstrating Server use",
    prefix="DEV:",
)
print(server.pvlist)

# create an example PV of each type
# double array type PV
pv_double1 = PVScalarRecipe(PVTypes.DOUBLE, "An example double PV", 5.0)
server.add_pv("DEV:RW:DOUBLE1", pv_double1)
server.add_pv("DEV:RW:DOUBLE2", pv_double1)
pv_double1.initial_value = 17.5
pv_double1.description = "A different default value for the PV"
# try setting a different value for the timestamp
pv_double1.set_timestamp(1729699237.8525229)
pv_double1.set_alarm_limits(low_warning=2, high_alarm=9)
server.add_pv("DEV:RW:DOUBLE3", pv_double1)


server.start()

print(server.pvlist)

try:
    while True:
        # Once the server is running, you should be able to update values of the PVs
        # it is hosting through pvput calls (either directly through CLI, Phoebus or
        # the p4p Client)
        time.sleep(5)
except KeyboardInterrupt:
    pass
finally:
    server.stop()

# NOTE the PVs in the server config are kept even though they aren't being served
# so we don't have to add them again
print(server.pvlist)
