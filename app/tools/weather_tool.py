from __future__ import annotations

from typing import Any

from app.integrations.weather import WeatherService
from app.security.permissions import PermissionLevel
from app.tools.base import Tool, ToolParameter, ToolResult


class GetWeatherTool(Tool):
    name = "get_weather"
    description = "Get current weather conditions for a location."
    permission_level = PermissionLevel.READ_ONLY
    parameters = [
        ToolParameter(
            name="location",
            type="string",
            description="City or place name, e.g. 'Toronto' or 'Welland, Ontario'.",
        ),
    ]

    def __init__(self, weather_service: WeatherService) -> None:
        self._service = weather_service

    async def execute(self, location: str, **kwargs: Any) -> ToolResult:
        result = await self._service.get_current_weather(location)
        if not result.success:
            return ToolResult(success=False, error=result.error)

        unit_symbol = "°F" if result.unit == "fahrenheit" else "°C"
        summary = (
            f"{result.location_name}: {result.condition}, {result.temperature}{unit_symbol} "
            f"(feels like {result.feels_like}{unit_symbol}), "
            f"humidity {result.humidity}%, wind {result.wind_speed} "
            f"{'mph' if result.unit == 'fahrenheit' else 'km/h'}"
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
