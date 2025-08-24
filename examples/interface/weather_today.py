# /// script
# dependencies = [
#   "python-weather",
# ]
# ///

import argparse
import asyncio
import os

import python_weather
import python_weather.forecast

UNIT = python_weather.METRIC


async def get_weather_forecast(city: str) -> python_weather.forecast.Forecast:
    """Get the short-term weather forecast for a city."""
    # Declare the client. The measuring unit used defaults to the metric system (celcius, km/h, etc.)
    async with python_weather.Client(unit=UNIT) as client:
        # Fetch a weather forecast from a city.
        weather = await client.get(city)

    return weather


async def get_today_temperatures(weather: python_weather.forecast.Forecast) -> dict[int, int]:
    """Get the temperatures for today in three-hourly intervals."""
    temperatures: dict[int, int] = {}

    today_weather = weather.daily_forecasts[0]
    for hourly in today_weather:
        temperatures[hourly.time.hour] = hourly.temperature

    return temperatures


async def get_today_rainchances(weather: python_weather.forecast.Forecast) -> dict[int, int]:
    """Get the rain chances for today in three-hourly intervals."""
    rainchances: dict[int, int] = {}

    today_weather = weather.daily_forecasts[0]
    for hourly in today_weather:
        rainchances[hourly.time.hour] = hourly.chances_of_rain

    return rainchances


async def get_umbrella_advice(rainchances: list[int]) -> tuple[int, bool]:
    """Get advice on whether to bring an umbrella based on rain chances."""
    max_rainchance = max(rainchances)
    if max_rainchance > 20:
        return max_rainchance, True
    return max_rainchance, False


async def print_forecast(weather: python_weather.forecast.Forecast) -> None:
    """Print the weather forecast for today to the console."""
    # Fetch the temperature for today.
    print(f"### Today's Weather Forecast for {weather.location} ###")
    print(f"Current temperature: {weather.temperature} {UNIT.temperature}")

    # Fetch weather forecast for upcoming days.
    temperatures = await get_today_temperatures(weather)
    rainchances = await get_today_rainchances(weather)

    hours = list(temperatures.keys())

    print("Hour:   " + "  |  ".join(f"{h:3}" for h in hours))
    print(70 * "-")
    print("Temp:   " + "  |  ".join(f"{t:3}" for t in temperatures.values()))
    print("Rain:   " + "  |  ".join(f"{r:3}" for r in rainchances.values()))

    max_rain_chance, umbrella_needed = await get_umbrella_advice(list(rainchances.values()))
    print(f"Max chance of rain today: {max_rain_chance}%", end="")
    if umbrella_needed:
        print(" (Bring an umbrella!)")
    else:
        print(" (No umbrella needed!)")

    return


async def main():
    parser = argparse.ArgumentParser(prog="weather_today", description="Print today's weather forecast to the console")
    parser.add_argument("city", type=str, help="The city to get the weather forecast for")
    args = parser.parse_args()

    weather = await get_weather_forecast(args.city)
    await print_forecast(weather)


if __name__ == "__main__":
    # See https://stackoverflow.com/questions/45600579/asyncio-event-loop-is-closed-when-getting-loop
    # for more details.
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main())
