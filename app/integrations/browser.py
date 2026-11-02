"""
Browser automation via Playwright.

Drives a real browser window (Microsoft Edge by default, already installed
on Windows, so no browser download is needed) with its own persistent
profile under data/browser_profile — log in to a site once and the
session sticks.

The model works from "snapshots": readable page text plus a numbered list
of the interactive elements currently visible (links, buttons, inputs).
It then clicks or types by number. Numbers are stamped onto the elements
as a data attribute, so they stay valid until the next snapshot.

Playwright is optional (`pip install -e ".[browser]"`); without it the
browser tools are simply not registered.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_PAGE_TEXT_CHARS = 15_000
MAX_ELEMENTS = 150

# Marks visible interactive elements with data-jarvis-id and describes them.
_SNAPSHOT_JS = r"""
(maxElements) => {
  document.querySelectorAll('[data-jarvis-id]').forEach(e => e.removeAttribute('data-jarvis-id'));
  const selector = 'a[href], button, input:not([type=hidden]), textarea, select, [role=button], [role=link], [role=tab], [role=menuitem], [role=checkbox], [role=option], [contenteditable=true], summary';
  const out = [];
  let id = 1;
  for (const el of document.querySelectorAll(selector)) {
    const r = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    if (r.width === 0 || r.height === 0 || style.visibility === 'hidden' || style.display === 'none') continue;
    if (r.bottom < 0 || r.top > window.innerHeight * 3) continue;
    el.setAttribute('data-jarvis-id', String(id));
    const tag = el.tagName.toLowerCase();
    const type = el.getAttribute('type') || el.getAttribute('role') || '';
    let label = (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('title') || el.getAttribute('name') || '').trim().replace(/\s+/g, ' ');
    if (label.length > 80) label = label.slice(0, 77) + '...';
    let extra = '';
    if (tag === 'a') { const h = el.getAttribute('href') || ''; extra = h.startsWith('javascript') ? '' : ' -> ' + h.slice(0, 80); }
    out.push(`[${id}] ${tag}${type ? '(' + type + ')' : ''} "${label}"${extra}`);
    id++;
    if (id > maxElements) break;
  }
  return out;
}
"""


class BrowserError(Exception):
    pass


class BrowserSession:
    def __init__(self, profile_dir: Path, channel: str = "msedge", headless: bool = False) -> None:
        self._profile_dir = profile_dir
        self._channel = channel
        self._headless = headless
        self._playwright = None
        self._context = None
        self._page = None

    @staticmethod
    def available() -> bool:
        try:
            import playwright.async_api  # noqa: F401
        except ImportError:
            return False
        return True

    async def _ensure_page(self):
        if self._page is not None and not self._page.is_closed():
            return self._page
        if self._context is None:
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise BrowserError(
                    "Playwright is not installed. Install with: pip install -e \".[browser]\""
                ) from exc
            self._profile_dir.mkdir(parents=True, exist_ok=True)
            self._playwright = await async_playwright().start()
            launch_kwargs = {"headless": self._headless, "viewport": {"width": 1280, "height": 900}}
            try:
                self._context = await self._playwright.chromium.launch_persistent_context(
                    str(self._profile_dir), channel=self._channel or None, **launch_kwargs
                )
            except Exception as first_exc:  # noqa: BLE001
                # Fall back to Playwright's bundled Chromium if the system
                # browser channel isn't available.
                logger.warning("Could not launch %s (%s); trying bundled Chromium.", self._channel, first_exc)
                try:
                    self._context = await self._playwright.chromium.launch_persistent_context(
                        str(self._profile_dir), **launch_kwargs
                    )
                except Exception as exc:  # noqa: BLE001
                    await self.close()
                    raise BrowserError(
                        f"Could not start a browser: {exc}. If Edge isn't installed, run: "
                        "python -m playwright install chromium"
                    ) from exc
        pages = [p for p in self._context.pages if not p.is_closed()]
        self._page = pages[-1] if pages else await self._context.new_page()
        return self._page

    async def _settle(self, page) -> None:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10_000)
            await page.wait_for_load_state("networkidle", timeout=3_000)
        except Exception:  # noqa: BLE001 - busy pages never go idle; that's fine
            pass

    async def navigate(self, url: str) -> str:
        url = url.strip()
        if "://" not in url:
            url = "https://" + url
        if not url.startswith(("http://", "https://")):
            raise BrowserError("Only http(s) URLs can be opened.")
        page = await self._ensure_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:  # noqa: BLE001
            raise BrowserError(f"Could not load {url}: {exc}") from exc
        await self._settle(page)
        return await self.snapshot()

    async def snapshot(self) -> str:
        page = await self._ensure_page()
        try:
            elements = await page.evaluate(_SNAPSHOT_JS, MAX_ELEMENTS)
            text = await page.evaluate("() => document.body ? document.body.innerText : ''")
        except Exception as exc:  # noqa: BLE001
            raise BrowserError(f"Could not read the page: {exc}") from exc
        text = "\n".join(line.strip() for line in (text or "").splitlines() if line.strip())
        if len(text) > MAX_PAGE_TEXT_CHARS:
            text = text[:MAX_PAGE_TEXT_CHARS] + f"\n[... {len(text) - MAX_PAGE_TEXT_CHARS} more characters; scroll or use web_fetch for the rest]"
        title = await page.title()
        return (
            f"URL: {page.url}\nTitle: {title}\n\n"
            f"Interactive elements (use these numbers with browser_click / browser_type):\n"
            + ("\n".join(elements) if elements else "(none visible)")
            + f"\n\nPage text:\n{text}"
        )

    async def _locate(self, element_id: int):
        page = await self._ensure_page()
        locator = page.locator(f'[data-jarvis-id="{int(element_id)}"]')
        if await locator.count() == 0:
            raise BrowserError(f"Element [{element_id}] isn't on the page any more — take a new browser_snapshot.")
        return page, locator.first

    async def click(self, element_id: int | None = None, text: str | None = None) -> str:
        page = await self._ensure_page()
        try:
            if element_id is not None:
                _, target = await self._locate(element_id)
            elif text:
                target = page.get_by_text(text, exact=False).first
            else:
                raise BrowserError("Give an element number or the visible text to click.")
            await target.scroll_into_view_if_needed(timeout=5_000)
            await target.click(timeout=10_000)
        except BrowserError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BrowserError(f"Click failed: {exc}") from exc
        await self._settle(page)
        # A click may have opened a new tab; follow it.
        self._page = self._context.pages[-1]
        return await self.snapshot()

    async def type_text(self, element_id: int, text: str, submit: bool = False) -> str:
        page, target = await self._locate(element_id)
        try:
            await target.fill(text, timeout=10_000)
            if submit:
                await target.press("Enter")
        except Exception as exc:  # noqa: BLE001
            raise BrowserError(f"Typing failed: {exc}") from exc
        await self._settle(page)
        return await self.snapshot()

    async def press_key(self, key: str) -> str:
        page = await self._ensure_page()
        try:
            await page.keyboard.press(key)
        except Exception as exc:  # noqa: BLE001
            raise BrowserError(f"Key press failed: {exc}") from exc
        await self._settle(page)
        return await self.snapshot()

    async def scroll(self, direction: str = "down") -> str:
        page = await self._ensure_page()
        delta = -800 if direction == "up" else 800
        await page.mouse.wheel(0, delta)
        await page.wait_for_timeout(500)
        return await self.snapshot()

    async def back(self) -> str:
        page = await self._ensure_page()
        await page.go_back(timeout=15_000)
        await self._settle(page)
        return await self.snapshot()

    async def screenshot(self) -> dict:
        page = await self._ensure_page()
        data = await page.screenshot(type="jpeg", quality=70)
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(data).decode("ascii")},
        }

    async def close(self) -> None:
        try:
            if self._context is not None:
                await self._context.close()
            if self._playwright is not None:
                await self._playwright.stop()
        except Exception:  # noqa: BLE001
            logger.debug("Error closing browser", exc_info=True)
        finally:
            self._context = None
            self._playwright = None
            self._page = None
