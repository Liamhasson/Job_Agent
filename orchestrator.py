"""
Orchestrator — runs the full pipeline end to end.

Flow:
  1. Scrape all sources for all search terms
  2. Deduplicate against seen_jobs.json
  3. Filter for relevance (Claude)
  4. For each relevant job:
     a. Research the company (Playwright + Claude)
     b. Rewrite CV (Claude)
     c. Write cover letter (Claude)
     d. Generate PDFs
     e. Send Gmail notification
  5. Save updated seen_jobs.json

Run modes:
  python orchestrator.py           → full pipeline
  python orchestrator.py --dry-run → scrape + filter only, no emails
  python orchestrator.py --test    → uses fixture data, no scraping
"""

from __future__ import annotations
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import anthropic
import yaml
from dotenv import load_dotenv

from modules import Job, ApplicationPackage
from modules.scraper.linkedin import LinkedInScraper
from modules.scraper.indeed import IndeedScraper
from modules.scraper.stepstone import StepstoneScraper
from modules.filter.relevance import filter_jobs
from modules.research.company_research import research_company
from modules.writer.cv_rewriter import rewrite_cv
from modules.writer.cover_letter import write_cover_letter
from modules.pdf.generator import generate_cv_pdf, generate_cover_letter_pdf
from modules.notifier.gmail import send_notification

ROOT = Path(__file__).parent
SEEN_JOBS_PATH = ROOT / "seen_jobs.json"
CONFIG_PATH = ROOT / "config" / "settings.yaml"
OUTPUT_DIR = ROOT / "output"


def load_seen_jobs() -> set[str]:
    if SEEN_JOBS_PATH.exists():
        data = json.loads(SEEN_JOBS_PATH.read_text())
        return set(data.get("seen", []))
    return set()


def save_seen_jobs(seen: set[str]) -> None:
    SEEN_JOBS_PATH.write_text(json.dumps({"seen": sorted(seen)}, indent=2))


async def scrape_all(config: dict, sources: list[str]) -> list[Job]:
    """Run all enabled scrapers for all search terms and locations."""
    scrapers = {
        "linkedin": LinkedInScraper(),
        "indeed": IndeedScraper(),
        "stepstone": StepstoneScraper(),
    }

    all_jobs: list[Job] = []
    search_terms = config["scraper"]["search_terms"]
    locations = config["scraper"]["locations"]

    for source_name in sources:
        if source_name not in scrapers:
            continue
        scraper = scrapers[source_name]
        for term in search_terms:
            for location in locations:
                print(f"  [{source_name}] Scraping: '{term}' in '{location}'...")
                try:
                    jobs = await scraper.scrape(term, location)
                    all_jobs.extend(jobs)
                    print(f"  [{source_name}] Found {len(jobs)} listings")
                except Exception as e:
                    print(f"  [{source_name}] Error: {e}")

    # Deduplicate by job ID within this run
    seen_ids: set[str] = set()
    unique: list[Job] = []
    for job in all_jobs:
        if job.id not in seen_ids:
            seen_ids.add(job.id)
            unique.append(job)

    print(f"\nTotal unique jobs this run: {len(unique)}")
    return unique


def process_job(
    client: anthropic.Anthropic,
    job: Job,
    filter_result: dict,
    config: dict,
    dry_run: bool,
) -> None:
    """Full pipeline for a single relevant job."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    company_slug = job.company.replace(" ", "_").replace("/", "-")
    job_dir = OUTPUT_DIR / f"{date_str}_{company_slug}_{job.id[:6]}"
    job_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n  → Researching {job.company}...")
    company_profile = research_company(client, job)

    print(f"  → Rewriting CV...")
    cv_md = rewrite_cv(client, job, company_profile)
    (job_dir / "cv.md").write_text(cv_md)

    print(f"  → Writing cover letter...")
    cl_text = write_cover_letter(client, job, company_profile)
    (job_dir / "cover_letter.txt").write_text(cl_text)

    print(f"  → Generating PDFs...")
    cv_pdf = generate_cv_pdf(cv_md, job_dir / "cv.pdf")
    cl_pdf = generate_cover_letter_pdf(cl_text, job_dir / "cover_letter.pdf")

    pkg = ApplicationPackage(
        job=job,
        company_profile=company_profile,
        cv_markdown=cv_md,
        cover_letter_markdown=cl_text,
        cv_pdf_path=str(cv_pdf),
        cover_letter_pdf_path=str(cl_pdf),
    )

    if dry_run:
        print(f"  → [dry-run] Would send email for {job.title} @ {job.company}")
        print(f"     Files saved to: {job_dir}")
        return

    print(f"  → Sending email...")
    send_notification(
        pkg=pkg,
        filter_reason=filter_result["reason"],
        recipient=config["notification"]["recipient_email"],
        sender=config["notification"]["sender_email"],
    )
    print(f"  ✓ Done: {job.title} @ {job.company}")


def main(dry_run: bool = False, test_mode: bool = False) -> None:
    load_dotenv(override=True)

    config = yaml.safe_load(CONFIG_PATH.read_text())
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    print("=" * 60)
    print(f"Job Agent starting — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Mode: {'dry-run' if dry_run else 'live'}")
    print("=" * 60)

    seen_jobs = load_seen_jobs()
    print(f"Seen jobs so far: {len(seen_jobs)}")

    if test_mode:
        # Use a fixture job for testing without scraping
        jobs = [
            Job(
                id="fixture001",
                title="Product Designer",
                company="Blinkist",
                location="Berlin, Germany",
                url="https://blinkist.com/careers/product-designer",
                description=(
                    "Join our mobile team to design features that help 26M users build better habits. "
                    "You'll own onboarding and the daily recommendation flow. "
                    "We ship fast, measure everything, and care deeply about retention."
                ),
                source="test",
            )
        ]
        print(f"\n[test mode] Using {len(jobs)} fixture job(s)")
    else:
        sources = config["scraper"]["sources"]
        print(f"\nScraping from: {', '.join(sources)}")
        jobs = asyncio.run(scrape_all(config, sources))

    # Filter out already-seen jobs
    new_jobs = [j for j in jobs if j.id not in seen_jobs]
    print(f"New jobs (not seen before): {len(new_jobs)}")

    if not new_jobs:
        print("Nothing new today.")
        return

    # Relevance filter
    print(f"\nFiltering {len(new_jobs)} jobs for relevance...")
    relevant = filter_jobs(client, new_jobs)
    print(f"Relevant: {len(relevant)}/{len(new_jobs)}")

    # Mark ALL scraped jobs as seen (relevant or not) so we don't re-check tomorrow
    seen_jobs.update(j.id for j in new_jobs)
    save_seen_jobs(seen_jobs)

    if not relevant:
        print("No relevant jobs today.")
        return

    # Process each relevant job
    print(f"\nProcessing {len(relevant)} relevant job(s)...")
    for job, filter_result in relevant:
        try:
            process_job(client, job, filter_result, config, dry_run)
        except Exception as e:
            print(f"  ✗ Failed on {job.title} @ {job.company}: {e}")
            continue

    print(f"\n{'='*60}")
    print(f"Done. Processed {len(relevant)} job(s).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Job Application Agent")
    parser.add_argument("--dry-run", action="store_true", help="No emails — just generate files")
    parser.add_argument("--test", action="store_true", help="Use fixture data, skip scraping")
    args = parser.parse_args()
    main(dry_run=args.dry_run, test_mode=args.test)
