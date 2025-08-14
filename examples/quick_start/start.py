import asyncio

from p4p.server import Server, StaticProvider

from p4p_ext.asyncio.pvrecipe import PVScalarRecipe
from p4p_ext.definitions import PVTypes

loop = asyncio.new_event_loop()  # create the asyncio event loop

pvrecipe_double = PVScalarRecipe(PVTypes.DOUBLE, "An example double PV", 5.0)
pvrecipe_double.initial_value = 17.5
pvrecipe_double.set_alarm_limits(low_warning=2, high_alarm=9)
pvrecipe_double.set_control_limits(low=-10, high=100)

pv_double1 = pvrecipe_double.create_pv()

pvrecipe_double.initial_value = -15.5
pvrecipe_double.read_only = True

pv_double2 = pvrecipe_double.create_pv()

provider = StaticProvider()
provider.add("demo:pv:1", pv_double1)
provider.add("demo:pv:2", pv_double2)

try:
    server = Server((provider,))
    with server:
        done = asyncio.Event()

        loop.run_until_complete(done.wait())
finally:
    loop.close()
