"""
Stepstone scraper.

Stepstone is Germany's largest job board and the most scraper-friendly of the
three. Good coverage of Berlin design roles. No login required.
"""

from __future__ import annotations
import asyncio
from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from modules import Job
from modules.scraper.base import BaseScraper, make_job_id


class StepstoneScraper(BaseScraper):
    SOURCE = "stepstone"
    BASE_URL = "https://www.stepstone.de/jobs"

    async def scrape(self, search_term: str, location: str) -> list[Job]:
        jobs: list[Job] = []
        async with async_playwright() as p:
            browser, page = await self._new_page(p)
            try:
                # Stepstone uses URL-encoded search
                url = (
                    f"{self.BASE_URL}/{search_term.replace(' ', '-').lower()}"
                    f"/in-{location.split(',')[0].strip().replace(' ', '-').lower()}"
                    f"?radius=30&datePosted=1"  # 30km radius, last 24h
                )
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_timeout(2000)

                # Accept cookies if prompted
                try:
                    consent = page.locator("button[data-at='ccmgt_explicit_accept'], #ccmgt_explicit_accept")
                    if await consent.is_visible(timeout=3000):
                        await consent.click()
                        await page.wait_for_timeout(1000)
                except Exception:
                    pass

                cards = await page.query_selector_all(
                    "article[data-at='job-item'], [data-testid='job-item']"
                )
                for card in cards[:20]:
                    try:
                        title_el = await card.query_selector(
                            "[data-at='job-item-title'], h2[data-at='job-item-title']"
                        )
                        company_el = await card.query_selector(
                            "[data-at='job-item-company-name'], [data-testid='job-item-company-name']"
                        )
                        location_el = await card.query_selector(
                            "[data-at='job-item-location'], [data-testid='job-item-location']"
                        )
                        link_el = await card.query_selector("a[data-at='job-item-title']")

                        title = (await title_el.inner_text()).strip() if title_el else ""
                        company = (await company_el.inner_text()).strip() if company_el else ""
                        loc = (await location_el.inner_text()).strip() if location_el else location
                        href = await link_el.get_attribute("href") if link_el else ""

                        if not title or not company or not href:
                            continue

                        full_url = f"https://www.stepstone.de{href}" if href.startswith("/") else href
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
                print(f"[stepstone] Timeout — returning {len(jobs)} jobs.")
            except Exception as e:
                print(f"[stepstone] Error: {e}")
            finally:
                await browser.close()

        return jobs

    async def _fetch_description(self, page, url: str) -> str:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            await page.wait_for_timeout(1500)
            desc_el = await page.query_selector(
                "[data-at='jobad-description'], .at-section-text-description"
            )
            if desc_el:
                return (await desc_el.inner_text()).strip()[:4000]
        except Exception:
            pass
        return ""


if __name__ == "__main__":
    async def _test():
        scraper = StepstoneScraper()
        jobs = await scraper.scrape("UX Designer", "Berlin")
        for j in jobs:
            print(f"[{j.source}] {j.title} @ {j.company} — {j.url}")
        print(f"\nTotal: {len(jobs)} jobs")

    asyncio.run(_test())
