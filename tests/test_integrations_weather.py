import httpx
import pytest

from app.integrations.weather import WeatherService


def _mock_transport(geo_response: dict, forecast_response: dict | None = None, status_code: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        if "geocoding-api" in str(request.url):
            return httpx.Response(status_code, json=geo_response, request=request)
        return httpx.Response(status_code, json=forecast_response or {}, request=request)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_get_current_weather_success():
    geo_response = {
        "results": [
            {"name": "Toronto", "admin1": "Ontario", "country": "Canada",
             "latitude": 43.7, "longitude": -79.4}
        ]
    }
    forecast_response = {
        "current": {
            "temperature_2m": 72.5,
            "apparent_temperature": 70.0,
            "relative_humidity_2m": 55,
            "weather_code": 1,
            "wind_speed_10m": 8.2,
        }
    }
    transport = _mock_transport(geo_response, forecast_response)

    service = WeatherService(temperature_unit="fahrenheit", transport=transport)
    result = await service.get_current_weather("Toronto")

    assert result.success is True
    assert "Toronto" in result.location_name
    assert result.temperature == 72.5
    assert result.condition == "mostly clear"
    assert result.humidity == 55


@pytest.mark.asyncio
async def test_get_current_weather_location_not_found():
    transport = _mock_transport({"results": []})

    service = WeatherService(transport=transport)
    result = await service.get_current_weather("Nonexistentplacexyz")

    assert result.success is False
    assert "Couldn't find" in result.error


@pytest.mark.asyncio
async def test_get_current_weather_rejects_empty_location():
    service = WeatherService()
    result = await service.get_current_weather("   ")
    assert result.success is False
    assert "No location" in result.error


@pytest.mark.asyncio
async def test_get_current_weather_reports_request_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(handler)
    service = WeatherService(transport=transport)
    result = await service.get_current_weather("Toronto")

    assert result.success is False
    assert "Could not reach weather service" in result.error


@pytest.mark.asyncio
async def test_get_current_weather_reports_http_status_error():
    transport = _mock_transport({"results": []}, status_code=500)

    service = WeatherService(transport=transport)
    result = await service.get_current_weather("Toronto")

    assert result.success is False
    assert "Weather service error" in result.error


@pytest.mark.asyncio
async def test_unknown_weather_code_falls_back_gracefully():
    geo_response = {
        "results": [{"name": "Nowhere", "latitude": 0, "longitude": 0}]
    }
    forecast_response = {
        "current": {
            "temperature_2m": 50.0,
            "apparent_temperature": 48.0,
            "relative_humidity_2m": 40,
            "weather_code": 9999,  # not in our mapping
            "wind_speed_10m": 5.0,
        }
    }
    transport = _mock_transport(geo_response, forecast_response)

    service = WeatherService(transport=transport)
    result = await service.get_current_weather("Nowhere")

    assert result.success is True
    assert result.condition == "unknown conditions"
