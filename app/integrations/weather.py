"""
Weather via Open-Meteo — free, no API key, no account.

Two calls: geocode a place name to coordinates, then fetch current
conditions for those coordinates. Kept as a plain service class (not
behind a provider interface like LLM/STT/TTS) since there's only one
reasonable free option here and no obvious reason to swap it yet; if that
changes, wrapping it behind an interface later is a small refactor, not
a rewrite of callers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo's numeric weather codes, condensed to plain-English. Not
# exhaustive of every WMO code, but covers the common ones.
WEATHER_CODE_DESCRIPTIONS = {
    0: "clear sky",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    61: "light rain",
    63: "moderate rain",
    65: "heavy rain",
    71: "light snow",
    73: "moderate snow",
    75: "heavy snow",
    80: "light rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    95: "thunderstorm",
    96: "thunderstorm with light hail",
    99: "thunderstorm with heavy hail",
}


@dataclass(frozen=True)
class WeatherResult:
    success: bool
    location_name: str | None = None
    temperature: float | None = None
    feels_like: float | None = None
    condition: str | None = None
    humidity: int | None = None
    wind_speed: float | None = None
    unit: str = "fahrenheit"
    error: str | None = None


class WeatherService:
    def __init__(
        self,
        temperature_unit: str = "fahrenheit",
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._unit = temperature_unit
        self._timeout = timeout_seconds
        # transport is exposed purely for testability — tests inject an
        # httpx.MockTransport instead of monkeypatching AsyncClient
        # internals, which otherwise breaks raise_for_status()'s binding
        # of the response to its originating request.
        self._transport = transport

    async def get_current_weather(self, location: str) -> WeatherResult:
        if not location or not location.strip():
            return WeatherResult(success=False, error="No location provided.")

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                geo_response = await client.get(
                    GEOCODING_URL, params={"name": location.strip(), "count": 1}
                )
                geo_response.raise_for_status()
                geo_data = geo_response.json()

                results = geo_data.get("results")
                if not results:
                    return WeatherResult(
                        success=False, error=f"Couldn't find a location matching '{location}'."
                    )

                place = results[0]
                lat, lon = place["latitude"], place["longitude"]
                resolved_name = ", ".join(
                    part
                    for part in [place.get("name"), place.get("admin1"), place.get("country")]
                    if part
                )

                forecast_response = await client.get(
                    FORECAST_URL,
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
                        "temperature_unit": self._unit,
                    },
                )
                forecast_response.raise_for_status()
                forecast_data = forecast_response.json()
        except httpx.HTTPStatusError as exc:
            logger.error("Weather API returned an error: %s", exc)
            return WeatherResult(success=False, error=f"Weather service error: {exc}")
        except httpx.RequestError as exc:
            logger.error("Weather API request failed: %s", exc)
            return WeatherResult(success=False, error=f"Could not reach weather service: {exc}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error fetching weather")
            return WeatherResult(success=False, error=f"Unexpected error: {exc}")

        current = forecast_data.get("current")
        if not current:
            return WeatherResult(success=False, error="Weather service returned no current data.")

        code = current.get("weather_code")
        condition = WEATHER_CODE_DESCRIPTIONS.get(code, "unknown conditions")

        return WeatherResult(
            success=True,
            location_name=resolved_name or location,
            temperature=current.get("temperature_2m"),
            feels_like=current.get("apparent_temperature"),
            condition=condition,
            humidity=current.get("relative_humidity_2m"),
            wind_speed=current.get("wind_speed_10m"),
            unit=self._unit,
        )
