from unittest.mock import AsyncMock

import pytest

from app.integrations.news import NewsItem, NewsResult
from app.integrations.weather import WeatherResult
from app.tools.news_tool import GetNewsTool
from app.tools.weather_tool import GetWeatherTool


@pytest.mark.asyncio
async def test_weather_tool_formats_successful_result():
    fake_service = AsyncMock()
    fake_service.get_current_weather.return_value = WeatherResult(
        success=True,
        location_name="Toronto, Ontario, Canada",
        temperature=72.5,
        feels_like=70.0,
        condition="mostly clear",
        humidity=55,
        wind_speed=8.2,
        unit="fahrenheit",
    )

    tool = GetWeatherTool(weather_service=fake_service)
    result = await tool.execute(location="Toronto")

    assert result.success is True
    assert "Toronto" in result.result
    assert "mostly clear" in result.result
    assert "72.5°F" in result.result


@pytest.mark.asyncio
async def test_weather_tool_propagates_service_error():
    fake_service = AsyncMock()
    fake_service.get_current_weather.return_value = WeatherResult(
        success=False, error="Couldn't find a location matching 'Nowhereville'."
    )

    tool = GetWeatherTool(weather_service=fake_service)
    result = await tool.execute(location="Nowhereville")

    assert result.success is False
    assert "Nowhereville" in result.error


@pytest.mark.asyncio
async def test_news_tool_formats_headlines():
    fake_service = AsyncMock()
    fake_service.get_headlines.return_value = NewsResult(
        success=True,
        items=[
            NewsItem(title="Story One", link="http://example.com/1", source="Example News"),
            NewsItem(title="Story Two", link="http://example.com/2", source="Example News"),
        ],
    )

    tool = GetNewsTool(news_service=fake_service)
    result = await tool.execute()

    assert result.success is True
    assert len(result.result) == 2
    assert result.result[0]["title"] == "Story One"


@pytest.mark.asyncio
async def test_news_tool_propagates_service_error():
    fake_service = AsyncMock()
    fake_service.get_headlines.return_value = NewsResult(
        success=False, error="No news items found."
    )

    tool = GetNewsTool(news_service=fake_service)
    result = await tool.execute()

    assert result.success is False
    assert "No news items found" in result.error


@pytest.mark.asyncio
async def test_news_tool_passes_topic_and_limit_through():
    fake_service = AsyncMock()
    fake_service.get_headlines.return_value = NewsResult(success=True, items=[])

    tool = GetNewsTool(news_service=fake_service)
    await tool.execute(topic="AI", limit=3)

    fake_service.get_headlines.assert_called_once_with(limit=3, topic="AI")
