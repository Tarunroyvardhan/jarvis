import sys
import time
import types
from unittest.mock import MagicMock

import pytest

from app.integrations.news import NewsService


def _make_entry(title: str, link: str, published_parsed=None, published=None) -> dict:
    entry = {"title": title, "link": link}
    if published_parsed is not None:
        entry["published_parsed"] = published_parsed
    if published is not None:
        entry["published"] = published
    return entry


def _fake_parsed_feed(feed_title: str, entries: list[dict], bozo: bool = False):
    feed = types.SimpleNamespace(bozo=bozo, feed={"title": feed_title}, entries=entries)
    return feed


@pytest.mark.asyncio
async def test_get_headlines_returns_items_sorted_newest_first(monkeypatch):
    older = _make_entry("Older story", "http://example.com/1", time.gmtime(1000))
    newer = _make_entry("Newer story", "http://example.com/2", time.gmtime(2000))

    fake_feed = _fake_parsed_feed("Example News", [older, newer])

    fake_feedparser = types.ModuleType("feedparser")
    fake_feedparser.parse = MagicMock(return_value=fake_feed)
    monkeypatch.setitem(sys.modules, "feedparser", fake_feedparser)

    service = NewsService(feed_urls=["http://example.com/rss"])
    result = await service.get_headlines(limit=5)

    assert result.success is True
    assert [item.title for item in result.items] == ["Newer story", "Older story"]


@pytest.mark.asyncio
async def test_get_headlines_respects_limit(monkeypatch):
    entries = [
        _make_entry(f"Story {i}", f"http://example.com/{i}", time.gmtime(i))
        for i in range(10)
    ]
    fake_feed = _fake_parsed_feed("Example News", entries)

    fake_feedparser = types.ModuleType("feedparser")
    fake_feedparser.parse = MagicMock(return_value=fake_feed)
    monkeypatch.setitem(sys.modules, "feedparser", fake_feedparser)

    service = NewsService(feed_urls=["http://example.com/rss"])
    result = await service.get_headlines(limit=3)

    assert len(result.items) == 3


@pytest.mark.asyncio
async def test_get_headlines_filters_by_topic(monkeypatch):
    entries = [
        _make_entry("AI breakthrough announced", "http://example.com/1"),
        _make_entry("Local sports update", "http://example.com/2"),
    ]
    fake_feed = _fake_parsed_feed("Example News", entries)

    fake_feedparser = types.ModuleType("feedparser")
    fake_feedparser.parse = MagicMock(return_value=fake_feed)
    monkeypatch.setitem(sys.modules, "feedparser", fake_feedparser)

    service = NewsService(feed_urls=["http://example.com/rss"])
    result = await service.get_headlines(topic="AI")

    assert result.success is True
    assert len(result.items) == 1
    assert "AI" in result.items[0].title


@pytest.mark.asyncio
async def test_get_headlines_reports_no_match_for_topic(monkeypatch):
    entries = [_make_entry("Local sports update", "http://example.com/2")]
    fake_feed = _fake_parsed_feed("Example News", entries)

    fake_feedparser = types.ModuleType("feedparser")
    fake_feedparser.parse = MagicMock(return_value=fake_feed)
    monkeypatch.setitem(sys.modules, "feedparser", fake_feedparser)

    service = NewsService(feed_urls=["http://example.com/rss"])
    result = await service.get_headlines(topic="quantum computing")

    assert result.success is False
    assert "quantum computing" in result.error


@pytest.mark.asyncio
async def test_get_headlines_no_feeds_configured():
    service = NewsService(feed_urls=[])
    result = await service.get_headlines()
    assert result.success is False
    assert "No news feeds configured" in result.error


@pytest.mark.asyncio
async def test_get_headlines_aggregates_multiple_feeds(monkeypatch):
    feed_a = _fake_parsed_feed("Feed A", [_make_entry("From A", "http://a.com/1", time.gmtime(100))])
    feed_b = _fake_parsed_feed("Feed B", [_make_entry("From B", "http://b.com/1", time.gmtime(200))])

    fake_feedparser = types.ModuleType("feedparser")
    fake_feedparser.parse = MagicMock(side_effect=[feed_a, feed_b])
    monkeypatch.setitem(sys.modules, "feedparser", fake_feedparser)

    service = NewsService(feed_urls=["http://a.com/rss", "http://b.com/rss"])
    result = await service.get_headlines()

    assert result.success is True
    assert {item.title for item in result.items} == {"From A", "From B"}


@pytest.mark.asyncio
async def test_get_headlines_one_feed_failing_does_not_block_others(monkeypatch):
    good_feed = _fake_parsed_feed("Good Feed", [_make_entry("Good story", "http://good.com/1")])

    def side_effect(url):
        if url == "http://bad.com/rss":
            raise RuntimeError("connection refused")
        return good_feed

    fake_feedparser = types.ModuleType("feedparser")
    fake_feedparser.parse = MagicMock(side_effect=side_effect)
    monkeypatch.setitem(sys.modules, "feedparser", fake_feedparser)

    service = NewsService(feed_urls=["http://bad.com/rss", "http://good.com/rss"])
    result = await service.get_headlines()

    assert result.success is True
    assert len(result.items) == 1
    assert result.items[0].title == "Good story"


@pytest.mark.asyncio
async def test_get_headlines_all_feeds_failing_reports_error(monkeypatch):
    def side_effect(url):
        raise RuntimeError("connection refused")

    fake_feedparser = types.ModuleType("feedparser")
    fake_feedparser.parse = MagicMock(side_effect=side_effect)
    monkeypatch.setitem(sys.modules, "feedparser", fake_feedparser)

    service = NewsService(feed_urls=["http://bad.com/rss"])
    result = await service.get_headlines()

    assert result.success is False
    assert "connection refused" in result.error


@pytest.mark.asyncio
async def test_get_headlines_reports_missing_dependency_honestly(monkeypatch):
    monkeypatch.setitem(sys.modules, "feedparser", None)

    service = NewsService(feed_urls=["http://example.com/rss"])
    result = await service.get_headlines()

    assert result.success is False
    assert "feedparser is not installed" in result.error
