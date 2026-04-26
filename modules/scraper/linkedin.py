"""
LinkedIn scraper — uses the public job board (no login required).

WHY no login: LinkedIn's logged-in scraping detection is much more aggressive.
The public board at linkedin.com/jobs/search is slower to block and doesn't
risk account suspension. Trade-off: less data (no easy apply button state,
no connection info), but all the info we actually need is here.

KNOWN LIMITS:
- LinkedIn aggressively rate-limits. If you run this too often (>3x/day),
  expect CAPTCHAs. Daily is fine.
- playwright-stealth helps but isn't a guarantee. If blocked, the scraper
  returns an empty list rather than crashing the pipeline.
"""

from __future__ import annotations
import asyncio
from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from modules import Job
from modules.scraper.base import BaseScraper, make_job_id


class LinkedInScraper(BaseScraper):
    SOURCE = "linkedin"
    BASE_URL = "https://www.linkedin.com/jobs/search/"

    async def scrape(self, search_term: str, location: str) -> list[Job]:
        jobs: list[Job] = []
        async with async_playwright() as p:
            browser, page = await self._new_page(p)
            try:
                url = (
                    f"{self.BASE_URL}?keywords={search_term.replace(' ', '%20')}"
                    f"&location={location.replace(' ', '%20')}"
                    f"&f_TPR=r86400"  # posted in last 24 hours
                    f"&sortBy=DD"
                )
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_timeout(3000)

                # Scroll to load more results
                for _ in range(3):
                    await page.keyboard.press("End")
                    await page.wait_for_timeout(1500)

                cards = await page.query_selector_all(".job-search-card")
                for card in cards[:20]:  # cap at 20 per search term
                    try:
                        title_el = await card.query_selector(".base-search-card__title")
                        company_el = await card.query_selector(".base-search-card__subtitle")
                        location_el = await card.query_selector(".job-search-card__location")
                        link_el = await card.query_selector("a.base-card__full-link")

                        title = (await title_el.inner_text()).strip() if title_el else ""
                        company = (await company_el.inner_text()).strip() if company_el else ""
                        loc = (await location_el.inner_text()).strip() if location_el else location
                        url_href = await link_el.get_attribute("href") if link_el else ""

                        if not title or not company or not url_href:
                            continue

                        description = await self._fetch_description(page, url_href)

                        jobs.append(Job(
                            id=make_job_id(company, title, url_href),
                            title=title,
                            company=company,
                            location=loc,
                            url=url_href.split("?")[0],  # strip tracking params
                            description=description,
                            source=self.SOURCE,
                        ))
                    except Exception:
                        continue

            except PwTimeout:
                print(f"[linkedin] Timeout — LinkedIn may be blocking. Returning {len(jobs)} jobs.")
            except Exception as e:
                print(f"[linkedin] Error: {e}")
            finally:
                await browser.close()

        return jobs

    async def _fetch_description(self, page, url: str) -> str:
        """Open each job page in the same tab and grab the description."""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            await page.wait_for_timeout(2000)
            desc_el = await page.query_selector(".description__text")
            if desc_el:
                return (await desc_el.inner_text()).strip()[:4000]
        except Exception:
            pass
        return ""


if __name__ == "__main__":
    async def _test():
        scraper = LinkedInScraper()
        jobs = await scraper.scrape("Product Designer", "Berlin, Germany")
        for j in jobs:
            print(f"[{j.source}] {j.title} @ {j.company} — {j.url}")
        print(f"\nTotal: {len(jobs)} jobs")

    asyncio.run(_test())
