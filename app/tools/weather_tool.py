from __future__ import annotations

from typing import Any

from app.integrations.weather import WeatherService
from app.security.permissions import PermissionLevel
from app.tools.base import Tool, ToolParameter, ToolResult


class GetWeatherTool(Tool):
    name = "get_weather"
    description = "Get current weather for a location, plus an optional multi-day forecast."
    permission_level = PermissionLevel.READ_ONLY
    parameters = [
        ToolParameter(
            name="location",
            type="string",
            description="City or place name, e.g. 'Toronto' or 'Welland, Ontario'.",
        ),
        ToolParameter(
            name="forecast_days",
            type="integer",
            description="Days of forecast to include (0 = current only, 1 = today, up to 16).",
            required=False,
        ),
    ]

    def __init__(self, weather_service: WeatherService) -> None:
        self._service = weather_service

    async def execute(self, location: str, forecast_days: int = 0, **kwargs: Any) -> ToolResult:
        result = await self._service.get_current_weather(location, forecast_days=forecast_days)
        if not result.success:
            return ToolResult(success=False, error=result.error)

        unit_symbol = "°F" if result.unit == "fahrenheit" else "°C"
        summary = (
            f"{result.location_name}: {result.condition}, {result.temperature}{unit_symbol} "
            f"(feels like {result.feels_like}{unit_symbol}), "
            f"humidity {result.humidity}%, wind {result.wind_speed} "
            f"{'mph' if result.unit == 'fahrenheit' else 'km/h'}"
        )
        for day in result.daily:
            rain = day["precipitation_chance"]
            summary += (
                f"\n{day['date']}: {day['condition']}, high {day['high']}{unit_symbol}, "
                f"low {day['low']}{unit_symbol}" + (f", {rain}% chance of precipitation" if rain is not None else "")
            )
        return ToolResult(
            success=True,
            result=summary,
            metadata={
                "location": result.location_name,
                "temperature": result.temperature,
                "condition": result.condition,
            },
        )
