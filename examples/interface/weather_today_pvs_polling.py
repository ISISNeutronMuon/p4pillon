import asyncio

from p4p.nt import NTEnum, NTScalar
from p4p.server import Server, StaticProvider

from examples.interface.weather_today import (
    get_today_rainchances,
    get_today_temperatures,
    get_umbrella_advice,
    get_weather_forecast,
)
from p4p_ext.asyncio.sharednt import SharedNT


class Updater:
    """
    Update the other PVs when the city changes
    """

    def __init__(self, temperatures_pv: SharedNT, rainchance_pv: SharedNT, umbrella_pv: SharedNT):
        self._temperatures_pv = temperatures_pv
        self._rainchance_pv = rainchance_pv
        self._umbrella_pv = umbrella_pv

    async def update_weather(self, city: str):
        """Update the weather forecast for the selected city, and forward the details to the other PVs."""
        weather = await get_weather_forecast(city)
        temperatures = await get_today_temperatures(weather)
        rainchances = await get_today_rainchances(weather)
        max_rainchance, umbrella_needed = await get_umbrella_advice(rainchances.values())

        self._temperatures_pv.post(list(temperatures.values()))
        self._rainchance_pv.post(max_rainchance)
        self._umbrella_pv.post(umbrella_needed)


async def setup_pvs() -> dict[str, SharedNT]:
    """
    Initialise the PVs and return a StaticProvider ready to go.
    """

    cities = ["New York", "Bergen", "Cairo", "Tokyo", "Auckland"]

    weather = await get_weather_forecast(cities[0])
    temperatures = await get_today_temperatures(weather)
    rainchances = await get_today_rainchances(weather)
    max_rainchance, umbrella_needed = await get_umbrella_advice(list(rainchances.values()))

    temperatures_pv = SharedNT(
        nt=NTScalar("ai", display=True, valueAlarm=True),
        initial={
            "value": list(temperatures.values()),
            "display.description": "Forecast temperature every 3 hours",
            "display.units": "C",
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
        nt=NTScalar("i", display=True, valueAlarm=True),
        initial={
            "value": max_rainchance,
            "display.description": "Forecast maximum chance of rain",
            "display.units": "%",
            "valueAlarm.active": True,
            "valueAlarm.highAlarmLimit": 20,
            "valueAlarm.highAlarmSeverity": 2,
        },
    )
    umbrella_pv = SharedNT(nt=NTEnum(), initial={"index": umbrella_needed, "choices": ["Not Needed", "Needed"]})

    cities_pv = SharedNT(nt=NTEnum(), initial={"index": 0, "choices": cities})

    pvs = {
        "demo:temperatures": temperatures_pv,
        "demo:city": cities_pv,
        "demo:rainchance": rainchance_pv,
        "demo:umbrella": umbrella_pv,
    }

    return pvs


async def main():
    """
    Asynchronous main function.
    Sets up the PVs in a StaticProvider and keeps a Server running until interrupted.
    """
    pvs = await setup_pvs()

    provider = StaticProvider()
    for pv_name, pv in pvs.items():
        provider.add(pv_name, pv)

    updater = Updater(
        pvs["demo:temperatures"],
        pvs["demo:rainchance"],
        pvs["demo:umbrella"],
    )

    previous_city = pvs["demo:city"].value
    try:
        server = Server((provider,))

        print(provider.keys())  # Report available PVs
        with server:
            while True:
                await asyncio.sleep(1)

                current_city = pvs["demo:city"].value
                if current_city != previous_city:
                    await updater.update_weather(current_city)
                    previous_city = current_city
    finally:
        pass


if __name__ == "__main__":
    asyncio.run(main())
