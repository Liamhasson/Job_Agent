"""
LinkedIn scraper — uses the public guest jobs API (no login, no Playwright).

WHY guest API over Playwright:
LinkedIn blocks headless browsers on cloud server IPs (GitHub Actions ranges
are well-known). The guest API at /jobs-guest/jobs/api/... returns HTML
fragments that BeautifulSoup can parse with a simple HTTP request — no browser
fingerprinting, no JS execution, much harder to block.

KNOWN LIMITS:
- Still rate-limited if called too aggressively. One request per search term
  with a short delay is fine for daily use.
- LinkedIn may return fewer results outside business hours.
"""

from __future__ import annotations
import asyncio
import httpx
from bs4 import BeautifulSoup
from modules import Job
from modules.scraper.base import BaseScraper, make_job_id

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.linkedin.com/",
}


class LinkedInScraper(BaseScraper):
    SOURCE = "linkedin"
    GUEST_API = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

    async def scrape(self, search_term: str, location: str) -> list[Job]:
        jobs: list[Job] = []
        params = {
            "keywords": search_term,
            "location": location,
            "f_TPR": "r86400",   # last 24 hours
            "sortBy": "DD",
            "start": "0",
        }

        try:
            async with httpx.AsyncClient(
                headers=HEADERS,
                follow_redirects=True,
                timeout=30,
            ) as client:
                resp = await client.get(self.GUEST_API, params=params)
                if resp.status_code != 200 or not resp.text.strip():
                    print(f"  [linkedin] No results (status {resp.status_code})")
                    return jobs

                soup = BeautifulSoup(resp.text, "html.parser")
                cards = soup.find_all("div", class_="base-card")

                for card in cards[:20]:
                    try:
                        title_el  = card.find("h3", class_="base-search-card__title")
                        company_el = card.find("h4", class_="base-search-card__subtitle")
                        loc_el    = card.find("span", class_="job-search-card__location")
                        link_el   = card.find("a", class_="base-card__full-link")

                        title   = title_el.get_text(strip=True)   if title_el   else ""
                        company = company_el.get_text(strip=True)  if company_el else ""
                        loc     = loc_el.get_text(strip=True)      if loc_el     else location
                        url     = link_el.get("href", "")          if link_el    else ""

                        if not title or not company or not url:
                            continue

                        desc = await self._fetch_description(client, url)
                        await asyncio.sleep(1.5)

                        jobs.append(Job(
                            id=make_job_id(company, title, url),
                            title=title,
                            company=company,
                            location=loc,
                            url=url.split("?")[0],
                            description=desc,
                            source=self.SOURCE,
                        ))
                    except Exception:
                        continue

        except Exception as e:
            print(f"  [linkedin] Error: {e}")

        return jobs

    async def _fetch_description(self, client: httpx.AsyncClient, url: str) -> str:
        try:
            resp = await client.get(url, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                desc = soup.find("div", class_="description__text")
                if desc:
                    return desc.get_text(strip=True)[:4000]
        except Exception:
            pass
        return ""


if __name__ == "__main__":
    async def _test():
        scraper = LinkedInScraper()
        jobs = await scraper.scrape("Product Designer", "Berlin, Germany")
        for j in jobs:
            print(f"[{j.source}] {j.title} @ {j.company} — {j.url}")
        print(f"\nTotal: {len(jobs)}")
    asyncio.run(_test())
