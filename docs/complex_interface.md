# Adding an EPICS Interface to existing Python Code
Let's work through an example of using p4p_ext to add an EPICS interface to existing Python code. By necessity this will be a relatively simple example, but should give an idea of the kind of approach that may be used.

## Forecast and Umbrella
For our example, we will be adapting a program that informs a user about the probability of rain today and whether they will need an umbrella. Run `weather_today` with your local city as an argument to see its output, e.g.
```shell
$  python -m examples.asyncio.weather_today "Oxford"
### Today's Weather Forecast for Oxford ###
Current temperature: 25 C
Hour:     0  |    3  |    6  |    9  |   12  |   15  |   18  |   21
----------------------------------------------------------------------
Temp:    12  |   11  |   12  |   19  |   25  |   25  |   26  |   18
Rain:     0  |    0  |    0  |    0  |    0  |    0  |    0  |    0
Max chance of rain today: 0% (No umbrella needed!)
```
In the example output above, it is a warm and dry day in Oxford and the forecast is that no umbrella is needed.

The `weather_today` program relies on the [python_weather](https://pypi.org/project/python-weather/) package. The full source code is available in the `examples/` directory; we give only a brief synopsis of four key functions here.
```py
async def get_weather_forecast(city: str) -> python_weather.forecast.Forecast:
```
Generate a Forecast object for the specified city. As we can see above the city is specified by the user as a command line argument.
```py
async def get_today_temperatures(weather: python_weather.forecast.Forecast) -> dict[int, int]:
```
Given a Forecast object (from the prior `get_weather_forecast`) return a dictionary with hours as the keys and forecast temperatures as the values.
```py
async def get_today_rainchances(weather: python_weather.forecast.Forecast) -> dict[int, int]:
```
Given a Forecast object (from the prior `get_weather_forecast`) return a dictionary with hours as the keys and the forecast probabilities of rain as the values.
```py
async def get_umbrella_advice(rainchances: list[int]) -> tuple[int, bool]:
```
Given a list of rain probabilities (i.e. the values from the dict returned by `get_today_rainchances`) return a tuple with the maximum probability and whether that means an umbrella should be brought. In this case we advise bringing an umbrella if the chance of rain is >=20% at any point in the day.

There are also `print_forecast` and `main` functions, but these will not be relevant to adapting the existing code with an EPICS interface.

## What the EPICS Interface will look like
We need to decide what our EPICS interface will look like. Some of these decisions will be motivated by needing to demonstrate aspects of p4p_ext, but they should still make sense.

Here's our design:
* input a city name. We will restrict the allowed cities to a pre-defined set of cities. This means that we can reduce our error-handling (how do we indicate a problem with getting a forecast for "New Frozenburg"?) and will also allow us to demonstrate use of an NTEnum. This PV will be called `demo:city` and will support puts, i.e is writeable. 
* output the forecast temperatures of the city as an array, i.e. NTScalarArray. This PV will be called `demo:temperatures` and will not support puts, i.e. will be read only. We will set this PV to generate a warning if the temperature during a day is less than 5 C or greater than 18 C. The PV will generate an alarm if the temperature is less than 0 C or greater than 25 C.
* output the maximum forecast probability of rain, i.e. a single number and therefore an NTScalar. This PV will be called `demo:rainchance` and will be read only. The PV will alarm if the chance of rain is greater than 20%.
* output whether an umbrella is needed. We could use a binary NTScalar, but it is generally preferable to use an NTEnum instead as it includes an explanation of what the true and false states mean. This PV will be called `demo:umbrella` and will be read only.

It's not obvious but all the figures returned from the `python_weather` Forecast are integers, so we will make our NTScalar and NTScalarArrays integers too.

## Initial Implementation 
Let's start with a script that simply sets up a single PV, `demo:city`, which we'll later use to select the city. There is an asyncio `main` function which runs a Server with a (SharedNT) PV produced by `setup_pvs`. The initial version of `setup_pvs` below only generates the NTEnum `demo:city`, which has a choice of five cities and defaults to the first in the list.
```py
import asyncio

from p4p import Value
from p4p.nt import NTEnum, NTScalar
from p4p.server import Server, StaticProvider
from p4p.server.raw import Handler

from p4p_ext.asyncio.sharednt import SharedNT

async def setup_pvs() -> StaticProvider:
    """
    Initialise the PVs and return a StaticProvider ready to go.
    """
    provider = StaticProvider()

    cities = ["New York", "Bergen", "Cairo", "Tokyo", "Auckland"]
    cities_pv = SharedNT(
        nt=NTEnum(), initial={"index": 0, "choices": cities}
    )

    provider.add("demo:city", cities_pv)

    return provider


async def main():
    """
    Asynchronous main function.
    Sets up the PVs in a StaticProvider and keeps a Server running until interrupted.
    """
    provider = await setup_pvs()

    try:
        server = Server((provider,))
        with server:
            while True:
                await asyncio.sleep(1)
    finally:
        pass


if __name__ == "__main__":
    asyncio.run(main())
```
This is a program that can already be run. If you do so you can use
```shell
$ python -m p4p.client.cli put demo:city=Cairo
```
to set a city and 
```shell
$ python -m p4p.client.cli get demo:city
```
to check the PV has changed as expected.

## Adding the Other PVs
Let's modify the `setup_pvs` function to add the other PVs discussed. We will initialise their values based on the value of the `demo:city` PV, so this will also be our first time interfacing with the weather code we are going to adapt.
```py
async def setup_pvs() -> StaticProvider:
    """
    Initialise the PVs and return a StaticProvider ready to go.
    """
    provider = StaticProvider()

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
    umbrella_pv = SharedNT(
        nt=NTEnum(), 
        initial={
            "index": umbrella_needed, 
            "choices": ["Not Needed", "Needed"]
        },
    )
    cities_pv = SharedNT(
        nt=NTEnum(), 
        initial={
            "index": 0, 
            "choices": cities
        },
    )

    provider.add("demo:temperatures", temperatures_pv)
    provider.add("demo:city", cities_pv)
    provider.add("demo:rainchance", rainchance_pv)
    provider.add("demo:umbrella", umbrella_pv)

    return provider
```
The code above is verbose but not hard to follow. We setup the list of cities and then get the forecast information for the first one. `temperatures_pv` / `demo:temperatures` is setup with the list of temperatures, some display information is set, and importantly we configure the valueAlarms so that we are warned/alarmed about cold and hot days. `rainchance_pv` / `demo:rainchance` is similar. `umbrella_pv`/ `demo:umbrella` is an NTEnum similar to `cities_pv` / `demo:city` which remains unchanged. 

We can check everything is working as expected:
```shell
$ python -m p4p.client.cli get demo:city demo:temperatures demo:rainchance 
demo:city New York
demo:temperatures Tue Aug 19 21:31:23 2025 ntnumericarray([20, 19, 19, 21, 23, 24, 22, 21], dtype=int32)
demo:rainchance Tue Aug 19 21:31:23 2025 0
demo:umbrella Not Needed
```
This doesn't show if the alarms have worked as expected, but we can check using the `--raw` flag. We heavily truncate the resulting output:
```shell
$ python -m p4p.client.cli --raw get demo:temperatures demo:rainchance
demo:temperatures struct "epics:nt/NTScalarArray:1.0" {
    int32_t[] value = {8}[20, 19, 19, 21, 23, 24, 22, 21]
    struct "alarm_t" {
        int32_t severity = 1
        int32_t status = 0
        string message = "highWarning"
    } alarm
}

demo:rainchance struct "epics:nt/NTScalar:1.0" {
    int32_t value = 0
    struct "alarm_t" {
        int32_t severity = 0
        int32_t status = 0
        string message = ""
    } alarm
}
```
We can see in the example above that, by our criteria, New York is warm (warning) but dry (no alarm).

## Making it interactive
It should already be obvious that there is a problem. If we change the `demo:city` to one of it's other options, e.g. Cairo, the other PVs will not update. There are two approaches we can use to resolve this. Let's try the more straightforward one first.

We can periodically check the value of `demo:city` and, if it has changed, we update the other PVs. This is a polling stategy. Let's start by writing a class we'll use to update the other PVs. It's a class so we can easily track the :
```py
class Updater:
    """
    Update the other PVs when the city changes
    """

    def __init__(self, temperatures_pv: SharedNT, rainchance_pv: SharedNT, umbrella_pv: SharedNT):
        self._temperatures_pv = temperatures_pv
        self._rainchance_pv = rainchance_pv
        self._umbrella_pv = umbrella_pv

    def update_weather(city: str):
        """Update the weather forecast for the selected city, and forward the details to the other PVs."""
        print(city)
        weather = await get_weather_forecast(city)
        temperatures = await get_today_temperatures(weather)
        rainchances = await get_today_rainchances(weather)
        max_rainchance, umbrella_needed = await get_umbrella_advice(rainchances.values())

        self._temperatures_pv.post(list(temperatures.values()))
        self._rainchance_pv.post(max_rainchance)
        self._umbrella_pv.post(umbrella_needed)
```
We now need to make some changes to initialise the `Updater` and then to use. Let's start by modifying the `setup_pvs` function to initialise and return it.
```py
async def setup_pvs() -> tuple[StaticProvider, Updater]:
    [...]

    updater = Updater(temperatures_pv, rainchance_pv, umbrella_pv)
    return (provider, updater) 
```
And then we update the `main` function.
```py
async def main():
    """
    Asynchronous main function.
    Sets up the PVs in a StaticProvider and keeps a Server running until interrupted.
    """
    (provider, updater) = await setup_pvs()

    try:
        server = Server((provider,))
        with server:
            while True:
                await asyncio.sleep(1)
    finally:
        pass
```