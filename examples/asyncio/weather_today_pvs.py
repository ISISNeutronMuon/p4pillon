import asyncio

from p4p import Value
from p4p.nt import NTEnum, NTScalar
from p4p.server import Server, StaticProvider
from p4p.server.asyncio import SharedPV
from p4p.server.raw import Handler

from examples.asyncio.weather_today import (
    get_today_rainchances,
    get_today_temperatures,
    get_umbrella_advice,
    get_weather_forecast,
)
from p4p_ext.asyncio.sharednt import SharedNT


class CitiesHandler(Handler):
    """
    This handler allows the city to be selected by implementing a put() method.
    When the city is changed, it fetches the new weather forecast and updates the
    temperatures and rain chances PVs accordingly.
    """

    def __init__(self, temperatures_pv: SharedPV, rainchance_pv: SharedPV, umbrella_pv: SharedPV):
        self._temperatures_pv = temperatures_pv
        self._rainchance_pv = rainchance_pv
        self._umbrella_pv = umbrella_pv

    async def update_weather(self, city: str):
        """Update the weather forecast for the selected city, and forward the details to the other PVs."""
        print(city)
        weather = await get_weather_forecast(city)
        temperatures = await get_today_temperatures(weather)
        rainchances = await get_today_rainchances(weather)
        max_rainchance, umbrella_needed = await get_umbrella_advice(rainchances.values())

        self._temperatures_pv.post(list(temperatures.values()))
        self._rainchance_pv.post(max_rainchance)
        self._umbrella_pv.post(umbrella_needed)

    async def post_async(self, pv: SharedPV, value: Value):
        """Handle the post operation task asynchronously."""
        if value.changed("value.index"):
            cities = pv.current().raw["value.choices"]
            city = cities[value["value.index"]]

            await self.update_weather(city)

    def open(self, value: Value):
        cities = value["value.choices"]
        city = cities[value["value.index"]]

        loop = asyncio.get_running_loop()
        task = loop.create_task(self.update_weather(city))
        task.add_done_callback(lambda x: x)

    def post(self, pv: SharedPV, value):
        loop = asyncio.get_running_loop()
        task = loop.create_task(self.post_async(pv, value))
        task.add_done_callback(lambda x: x)

    def put(self, pv: SharedPV, op):
        # This simply enables the put operation to work for the NTEnum PV.
        # pv.post(op.value())
        op.done()


class SetupPVs:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._provider = StaticProvider()

        self._loop.run_until_complete(asyncio.wait_for(self.asyncSetUp(), 5))

    @property
    def providers(self) -> tuple[StaticProvider]:
        return (self._provider,)

    async def asyncSetUp(self):
        cities = ["New York", "Bergen", "Cairo", "Tokyo", "Auckland"]

        weather = await get_weather_forecast(cities[0])
        temperatures = await get_today_temperatures(weather)
        rainchances = await get_today_rainchances(weather)
        max_rainchance, umbrella_needed = await get_umbrella_advice(list(rainchances.values()))

        temperatures_pv = SharedNT(
            nt=NTScalar("ai", valueAlarm=True),
            initial={
                "value": list(temperatures.values()),
                "valueAlarm.active": True,
                "valueAlarm.highAlarmLimit": 25,
                "valueAlarm.highAlarmSeverity": 2,
                "valueAlarm.highWarningLimit": 18,
                "valueAlarm.highWarningSeverity": 1,
                "valueAlarm.lowWarningLimit": 5,
                "valueAlarm.lowWarningSeverity": 1,
                "valueAlarm.lowAlarmLimit": 0,
                "valueAlarm.lowAlarmSeverity": 2,
            },
        )
        rainchance_pv = SharedNT(
            nt=NTScalar("d", valueAlarm=True),
            initial={
                "value": max_rainchance,
                "valueAlarm.active": True,
                "valueAlarm.highAlarmLimit": 20,
                "valueAlarm.highAlarmSeverity": 2,
            },
        )
        umbrella_pv = SharedNT(nt=NTEnum(), initial={"index": umbrella_needed, "choices": ["Not Needed", "Needed"]})

        cities_handler = CitiesHandler(temperatures_pv, rainchance_pv, umbrella_pv)
        cities_pv = SharedNT(
            nt=NTEnum(), initial={"index": 0, "choices": cities}, user_handlers={"city_change": cities_handler}
        )

        self._provider.add("demo:temperatures", temperatures_pv)
        self._provider.add("demo:city", cities_pv)
        self._provider.add("demo:rainchance", rainchance_pv)
        self._provider.add("demo:umbrella", umbrella_pv)


def main():
    loop = asyncio.new_event_loop()
    provider_wrapper = SetupPVs(loop)

    try:
        # `Server.forever()` is for p4p threading and shouldn't
        # be used with async.
        server = Server(provider_wrapper.providers)
        with server:
            done = asyncio.Event()

            # loop.add_signal_handler(signal.SIGINT, done.set)
            # loop.add_signal_handler(signal.SIGTERM, done.set)
            loop.run_until_complete(done.wait())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
