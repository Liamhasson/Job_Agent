"""
Indeed scraper.

Indeed is more scraping-friendly than LinkedIn. We use the public search page.
Rate limit: wait 2-3 seconds between page loads, don't hammer it.
"""

from __future__ import annotations
import asyncio
from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from modules import Job
from modules.scraper.base import BaseScraper, make_job_id


class IndeedScraper(BaseScraper):
    SOURCE = "indeed"
    BASE_URL = "https://de.indeed.com/jobs"  # German Indeed — covers Berlin well

    async def scrape(self, search_term: str, location: str) -> list[Job]:
        jobs: list[Job] = []
        async with async_playwright() as p:
            browser, page = await self._new_page(p)
            try:
                url = (
                    f"{self.BASE_URL}?q={search_term.replace(' ', '+')}"
                    f"&l={location.replace(' ', '+')}"
                    f"&fromage=1"  # last 24 hours
                    f"&sort=date"
                    f"&lang=en"    # English results
                )
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_timeout(2000)

                # Handle cookie consent if it appears
                try:
                    consent_btn = page.locator("button#onetrust-accept-btn-handler")
                    if await consent_btn.is_visible(timeout=3000):
                        await consent_btn.click()
                        await page.wait_for_timeout(1000)
                except Exception:
                    pass

                cards = await page.query_selector_all(".job_seen_beacon, .jobsearch-ResultsList > li")
                for card in cards[:20]:
                    try:
                        title_el = await card.query_selector("h2.jobTitle span[title], h2.jobTitle a")
                        company_el = await card.query_selector("[data-testid='company-name'], .companyName")
                        location_el = await card.query_selector("[data-testid='text-location'], .companyLocation")
                        link_el = await card.query_selector("h2.jobTitle a")

                        title = (await title_el.inner_text()).strip() if title_el else ""
                        company = (await company_el.inner_text()).strip() if company_el else ""
                        loc = (await location_el.inner_text()).strip() if location_el else location
                        href = await link_el.get_attribute("href") if link_el else ""

                        if not title or not company or not href:
                            continue

                        full_url = f"https://de.indeed.com{href}" if href.startswith("/") else href
                        description = await self._fetch_description(page, full_url)

                        jobs.append(Job(
                            id=make_job_id(company, title, full_url),
                            title=title,
                            company=company,
                            location=loc,
                            url=full_url.split("?")[0],
                            description=description,
                            source=self.SOURCE,
                        ))
                        await page.wait_for_timeout(1500)
                    except Exception:
                        continue

            except PwTimeout:
                print(f"[indeed] Timeout — returning {len(jobs)} jobs.")
            except Exception as e:
                print(f"[indeed] Error: {e}")
            finally:
                await browser.close()

        return jobs

    async def _fetch_description(self, page, url: str) -> str:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            await page.wait_for_timeout(1500)
            desc_el = await page.query_selector("#jobDescriptionText, .jobsearch-jobDescriptionText")
            if desc_el:
                return (await desc_el.inner_text()).strip()[:4000]
        except Exception:
            pass
        return ""


if __name__ == "__main__":
    async def _test():
        scraper = IndeedScraper()
        jobs = await scraper.scrape("UX Designer", "Berlin, Germany")
        for j in jobs:
            print(f"[{j.source}] {j.title} @ {j.company} — {j.url}")
        print(f"\nTotal: {len(jobs)} jobs")

    asyncio.run(_test())
