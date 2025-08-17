# Adding an EPICS Interface to existing Python Code
Let's work through an example of using p4p_ext to add an EPICS interface to existing Python code. By necessity this will be a relatively simple example, but should give an idea of the kind of approach that may be used.

## Forecast and Umbrella
For our example, we will be adapting a program that informs a user about the probability of rain today and whether they will need an umbrella. Run `weather_today` with your local city to see its output, e.g.
```
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
```
async def get_weather_forecast(city: str) -> python_weather.forecast.Forecast:
```
Generate a Forecast object for the specified city. As we can see above the city is specified by the user as a command line argument.
```
async def get_today_temperatures(weather: python_weather.forecast.Forecast) -> dict[int, int]:
```
Given a Forecast object (from the prior `get_weather_forecast`) return a dictionary with hours as the keys and forecast temperatures as the values.
```
async def get_today_rainchances(weather: python_weather.forecast.Forecast) -> dict[int, int]:
```
Given a Forecast object (from the prior `get_weather_forecast`) return a dictionary with hours as the keys and the forecast probabilities of rain as the values.
```
async def get_umbrella_advice(rainchances: list[int]) -> tuple[int, bool]:
```
Given a list of rain probabilities (i.e. the values from the dict returned by `get_today_rainchances`) return a tuple with the maximum probability and whether that means an umbrella should be brought. In this case we advise bringing an umbrella if the chance of rain is >=20% at any point in the day.

There are also `print_forecast` and `main` functions, but these will not be relevant to adapting the existing code with an EPICS interface.

## What the EPICS Interface will look like
We need to decide what our EPICS interface will look like. Some of these decisions will be motivated by needed to demonstrate aspects of p4p_ext, but they should still make sense.

Here's our design:
* input a city name. We will restrict the allowed cities to a pre-defined set of cities. This means that we can reduce our error-handling (how do we indicate a problem with getting a forecast for "New Frozenburg"?) and will also allow us to demonstrate use of an NTEnum. This PV will be called `demo:city` and will support puts. 
* output the forecast temperatures of the city as an array, i.e. NTScalarArray. This PV will be called `demo:temperatures` and will not support puts, i.e. will be read only. We will set this PV to generate a warning if the temperature during a day is less than 5 C or greater than 18 C. The PV will generate an alarm if the temperature is less than 0 C or greater than 25 C.
* output the maximum forecast probability of rain, i.e. a single number and therefore an NTScalar. This PV will be called `demo:rainchance` and will be read only. The PV will alarm if the chance of rain is greater than 20%.
* output whether an umbrella is needed. We could use a binary NTScalar, but it is generally preferable to use an NTEnum instead as it includes an explanation of what the true and false states mean. This PV will be called `demo:umbrella` and will be read only.

## Initial Implementation 
Let's start with a script that simply sets up a single PV, `demo:city`, which we'll later use to select the city  

```
import asyncio

from p4p import Value
from p4p.nt import NTEnum, NTScalar
from p4p.server import Server, StaticProvider
from p4p.server.asyncio import SharedPV
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