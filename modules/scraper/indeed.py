"""
Indeed scraper — replaced with Glassdoor.

Indeed blocks all headless browsers and RSS requests from cloud IPs (403).
Glassdoor's job search is accessible via simple HTTP requests and covers
the same job market. Same interface as the other scrapers.
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
}


class IndeedScraper(BaseScraper):
    """Scrapes Glassdoor (Indeed replacement — Indeed blocks cloud IPs)."""
    SOURCE = "glassdoor"

    async def scrape(self, search_term: str, location: str) -> list[Job]:
        jobs: list[Job] = []
        city = location.split(",")[0].strip().lower().replace(" ", "-")
        term_slug = search_term.lower().replace(" ", "-")

        url = (
            f"https://www.glassdoor.com/Job/{city}-{term_slug}-jobs-SRCH_IL.0,"
            f"{len(city)}_IC2622109_KO{len(city)+1},{len(city)+1+len(term_slug)}.htm"
            f"?fromAge=1&sortBy=date_desc"
        )

        try:
            async with httpx.AsyncClient(
                headers=HEADERS,
                follow_redirects=True,
                timeout=30,
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return jobs

                soup = BeautifulSoup(resp.text, "html.parser")

                # Glassdoor job cards
                cards = soup.find_all("li", attrs={"data-jobid": True})
                if not cards:
                    # fallback selector
                    cards = soup.find_all("article", class_=lambda c: c and "JobCard" in c)

                for card in cards[:20]:
                    try:
                        title_el   = card.find(["a", "span"], attrs={"data-test": "job-title"}) or \
                                     card.find("a", class_=lambda c: c and "JobCard_jobTitle" in (c or ""))
                        company_el = card.find(["span", "div"], attrs={"data-test": "employer-name"}) or \
                                     card.find(class_=lambda c: c and "EmployerProfile" in (c or ""))
                        loc_el     = card.find(["div", "span"], attrs={"data-test": "emp-location"})
                        link_el    = card.find("a", href=True)

                        title   = title_el.get_text(strip=True)   if title_el   else ""
                        company = company_el.get_text(strip=True)  if company_el else ""
                        loc     = loc_el.get_text(strip=True)      if loc_el     else location
                        href    = link_el["href"]                  if link_el    else ""

                        if not title or not href:
                            continue

                        full_url = f"https://www.glassdoor.com{href}" if href.startswith("/") else href

                        jobs.append(Job(
                            id=make_job_id(company, title, full_url),
                            title=title,
                            company=company or "Unknown",
                            location=loc,
                            url=full_url.split("?")[0],
                            description="",  # Glassdoor requires login for full description
                            source=self.SOURCE,
                        ))
                    except Exception:
                        continue

        except Exception as e:
            print(f"  [glassdoor] Error: {e}")

        return jobs


if __name__ == "__main__":
    async def _test():
        scraper = IndeedScraper()
        jobs = await scraper.scrape("Product Designer", "Berlin, Germany")
        for j in jobs:
            print(f"[{j.source}] {j.title} @ {j.company} — {j.url}")
        print(f"\nTotal: {len(jobs)}")
    asyncio.run(_test())
