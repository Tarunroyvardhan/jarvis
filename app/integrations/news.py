"""
News via RSS feeds — no API key, no account. Aggregates configured feed
URLs, optionally filters by keyword, and sorts by publish date where the
feed provides one.

feedparser is a synchronous/blocking library; fetches run via
asyncio.to_thread so they don't block the event loop, same principle as
the voice modules' executor pattern.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

FALLBACK_SORT_KEY = time.gmtime(0)  # treat undated items as oldest, not newest


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    source: str
    published: str | None = None


@dataclass(frozen=True)
class NewsResult:
    success: bool
    items: list[NewsItem] = field(default_factory=list)
    error: str | None = None


class NewsService:
    def __init__(self, feed_urls: list[str]) -> None:
        self._feed_urls = feed_urls

    async def get_headlines(self, limit: int = 5, topic: str | None = None) -> NewsResult:
        if not self._feed_urls:
            return NewsResult(success=False, error="No news feeds configured.")

        try:
            import feedparser  # imported lazily; keeps base import light
        except ImportError as exc:
            return NewsResult(success=False, error=f"feedparser is not installed: {exc}")

        all_items: list[tuple[time.struct_time, NewsItem]] = []
        feed_errors: list[str] = []

        for url in self._feed_urls:
            try:
                parsed = await asyncio.to_thread(feedparser.parse, url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to fetch feed %s: %s", url, exc)
                feed_errors.append(f"{url}: {exc}")
                continue

            if getattr(parsed, "bozo", False) and not parsed.entries:
                logger.warning("Feed %s could not be parsed", url)
                feed_errors.append(f"{url}: could not be parsed")
                continue

            source_name = parsed.feed.get("title", url) if hasattr(parsed, "feed") else url

            for entry in parsed.entries:
                title = entry.get("title", "").strip()
                if not title:
                    continue
                if topic and topic.lower() not in title.lower():
                    continue

                sort_key = entry.get("published_parsed") or FALLBACK_SORT_KEY
                all_items.append(
                    (
                        sort_key,
                        NewsItem(
                            title=title,
                            link=entry.get("link", ""),
                            source=source_name,
                            published=entry.get("published"),
                        ),
                    )
                )

        if not all_items:
            if feed_errors and not topic:
                return NewsResult(success=False, error="; ".join(feed_errors))
            if topic:
                return NewsResult(
                    success=False, error=f"No news items found matching '{topic}'."
                )
            return NewsResult(success=False, error="No news items found.")

        all_items.sort(key=lambda pair: pair[0], reverse=True)
        items = [item for _, item in all_items[:limit]]

        return NewsResult(success=True, items=items)
