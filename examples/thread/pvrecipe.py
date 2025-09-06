import logging

from p4p.server import Server

from p4pillon.definitions import PVTypes
from p4pillon.thread.pvrecipe import PVScalarRecipe

logging.basicConfig(level=logging.DEBUG)

# create an example PV of each type
# double array type PV
pvrecipe_double1 = PVScalarRecipe(PVTypes.DOUBLE, "An example double PV", 5.0)
pvrecipe_double1.initial_value = 17.5
pvrecipe_double1.description = "A different default value for the PV"
# try setting a different value for the timestamp
pvrecipe_double1.set_timestamp(1729699237.8525229)
pvrecipe_double1.set_alarm_limits(low_warning=2, high_alarm=9)

pv_double1 = pvrecipe_double1.create_pv()

Server.forever(
    providers=[
        {
            "demo:pv:name": pv_double1,  # PV name only appears here
        }
    ]
)
