from __future__ import annotations
import hashlib
from abc import ABC, abstractmethod
from playwright.async_api import async_playwright, Page
from playwright_stealth import Stealth
from modules import Job

_stealth = Stealth()


def make_job_id(company: str, title: str, url: str) -> str:
    """Stable unique ID so we never send the same job twice."""
    raw = f"{company.lower().strip()}{title.lower().strip()}{url.strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class BaseScraper(ABC):
    SOURCE: str = ""

    async def _new_page(self, playwright) -> tuple:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = await context.new_page()
        await _stealth.apply_stealth_async(page)
        return browser, page

    @abstractmethod
    async def scrape(self, search_term: str, location: str) -> list[Job]:
        """Return a list of Job objects for the given search term and location."""
        ...
