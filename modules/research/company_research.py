"""
Company research module.

For each relevant job: fetches the company website, about/culture/careers pages,
then asks Claude to synthesise what this company's "perfect candidate" looks like.

This is the context that makes the CV and cover letter feel genuinely tailored,
not just keyword-matched. Claude reads their actual language, values, tone.

Playwright fetches the pages (handles JS-rendered sites). We cap content at
6000 chars per page to keep Claude context manageable and cost low.
"""

from __future__ import annotations
import asyncio
import re
from typing import Optional
import anthropic
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

_stealth = Stealth()
from modules import Job, CompanyProfile


RESEARCH_SYSTEM = """You are a researcher helping a product designer prepare a tailored job application.

Given: a job description + scraped content from the company's website.
Task: synthesise a CompanyProfile that will help write a genuinely tailored CV and cover letter.

Focus on:
- What does this company actually value? (vs what every company says it values)
- What kind of person would thrive here? Be specific.
- What language do they use? (technical, warm, outcome-focused, mission-driven, etc.)
- What are they building and why does it matter to them?
- Any recent notable news, launches, or decisions?

Respond with ONLY valid JSON matching this schema exactly:
{
  "about": "2-3 sentences: what they do and why it matters to them",
  "values": ["up to 5 genuine values inferred from their language, not their boilerplate"],
  "tone": "one phrase describing their communication style, e.g. 'technical and precise' or 'warm and mission-driven'",
  "perfect_candidate": "3-4 sentences describing the ideal person for this role based on everything you've read — skills, mindset, working style",
  "recent_news": "any notable recent news, launches, or context (null if none found)"
}"""


async def _fetch_page(url: str, timeout: int = 15_000) -> str:
    """Fetch a page with Playwright and return its text content."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()
        await _stealth.apply_stealth_async(page)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            await page.wait_for_timeout(2000)
            # Get visible text, skip nav/footer noise
            text = await page.evaluate("""() => {
                const remove = ['nav', 'footer', 'header', 'script', 'style', 'noscript'];
                remove.forEach(tag => {
                    document.querySelectorAll(tag).forEach(el => el.remove());
                });
                return document.body.innerText;
            }""")
            return text[:6000] if text else ""
        except Exception as e:
            print(f"  [research] Could not fetch {url}: {e}")
            return ""
        finally:
            await browser.close()


def _guess_website(company: str, job_url: str) -> Optional[str]:
    """Try to extract or infer the company website from the job URL or name."""
    # For LinkedIn/Indeed, the company name is often enough for a Google-able URL
    # We try a few common patterns
    slug = re.sub(r"[^a-z0-9]", "", company.lower())
    return f"https://www.{slug}.com"  # rough guess — may 404, that's OK


def _find_subpages(base_url: str) -> list[str]:
    """Return candidate about/culture/careers URLs to try."""
    base = base_url.rstrip("/")
    return [
        f"{base}/about",
        f"{base}/about-us",
        f"{base}/culture",
        f"{base}/careers",
        f"{base}/jobs",
        f"{base}/team",
    ]


def research_company(
    client: anthropic.Anthropic,
    job: Job,
    company_website: Optional[str] = None,
) -> CompanyProfile:
    """
    Fetches company pages and asks Claude to build a CompanyProfile.
    company_website is optional — if None, we try to guess it.
    """
    website = company_website or _guess_website(job.company, job.url)
    pages_text: list[str] = []

    # Fetch homepage + up to 2 subpages
    async def fetch_all():
        texts = []
        homepage = await _fetch_page(website)
        if homepage:
            texts.append(f"=== Homepage: {website} ===\n{homepage}")
        for sub in _find_subpages(website)[:2]:
            content = await _fetch_page(sub)
            if content and len(content) > 200:
                texts.append(f"=== {sub} ===\n{content}")
                break  # one good subpage is enough
        return texts

    try:
        pages_text = asyncio.run(fetch_all())
    except Exception as e:
        print(f"  [research] Web fetch failed: {e}")

    company_context = "\n\n".join(pages_text) if pages_text else "(website not accessible)"

    prompt = f"""Company: {job.company}
Job title: {job.title}

Job description:
{job.description or "(not available)"}

---
Company website content:
{company_context}

Build the CompanyProfile. Respond with JSON only."""

    import json
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=800,
        system=RESEARCH_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw.strip())

    return CompanyProfile(
        name=job.company,
        website=website,
        about=data["about"],
        values=data["values"],
        tone=data["tone"],
        perfect_candidate=data["perfect_candidate"],
        recent_news=data.get("recent_news"),
    )


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    test_job = Job(
        id="test123",
        title="Product Designer",
        company="N26",
        location="Berlin, Germany",
        url="https://n26.com/en-eu/careers",
        description="We're looking for a Product Designer to join our mobile banking team...",
        source="test",
    )

    profile = research_company(client, test_job, company_website="https://n26.com")
    import json, dataclasses
    print(json.dumps(dataclasses.asdict(profile), indent=2))
