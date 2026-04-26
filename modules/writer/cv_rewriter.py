"""
CV rewriter module.

Claude reads both CV flavours, the job description, and the company profile,
then decides:
  1. Which flavour to lead with (A = AI/shipping, B = mobile/engagement, or blend)
  2. How to reorder bullets to lead with the most relevant experience
  3. What to cut to keep it exactly one page worth of content

Output: markdown CV ready to be rendered to PDF.

Rules enforced in the prompt:
- Never invent experience or skills
- Never change job titles
- Always one page — cut ruthlessly
- Reorder bullets within each role, don't reorder roles unless it's a flavour swap
"""

from __future__ import annotations
import anthropic
from pathlib import Path
from modules import Job, CompanyProfile

BASE_DIR = Path(__file__).parent.parent.parent / "base_documents"


def _load_base_documents() -> dict[str, str]:
    return {
        "cv_a": (BASE_DIR / "cv_flavour_a.md").read_text(),
        "cv_b": (BASE_DIR / "cv_flavour_b.md").read_text(),
    }


SYSTEM_PROMPT = """You are a CV writer for Liam Hasson, a Product/UX Designer.

Your job: take Liam's base CV documents and rewrite a tailored version for a specific job and company.

## STRICT RULES — never break these:
1. ONE PAGE maximum. Cut ruthlessly. Every word must earn its place.
2. Never invent experience, skills, or tools that don't appear in the base CVs.
3. Never change job titles.
4. Only reframe what exists — same facts, different emphasis.
5. Do not add a section or bullet that doesn't have a basis in the source documents.

## What you're deciding:
- FLAVOUR: Use CV Flavour A (AI-native/shipping) or Flavour B (mobile/engagement) or blend both.
  - Flavour A → for: AI-native companies, generalist product roles, fast startups, Bending Spoons-type orgs
  - Flavour B → for: consumer apps, mobile-first, gaming, social, fitness, retention-focused products
  - When in doubt: lead with whichever About section fits better, then pick the best bullets from each
- BULLET ORDER: within each role, reorder bullets so the most relevant one to this specific job leads
- CUTS: if content won't fit on one page, cut the least relevant bullets first; BIMM/band details are lowest priority for pure tech roles

## Output format
Return ONLY the tailored CV in markdown. No explanation, no commentary, no wrapping.
Start with the name line, end with Languages. Use the exact same markdown structure as the input."""


def rewrite_cv(
    client: anthropic.Anthropic,
    job: Job,
    company_profile: CompanyProfile,
) -> str:
    """Returns the tailored CV as a markdown string."""
    docs = _load_base_documents()

    prompt = f"""## Job details
Title: {job.title}
Company: {job.company}
Location: {job.location}

## Company profile
About: {company_profile.about}
Values: {", ".join(company_profile.values)}
Tone: {company_profile.tone}
Perfect candidate: {company_profile.perfect_candidate}

## Job description
{job.description or "(not available)"}

---

## CV Flavour A — AI-native / Shipping
{docs["cv_a"]}

---

## CV Flavour B — Mobile / Engagement
{docs["cv_b"]}

---

Write the tailored one-page CV now. Return markdown only."""

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text.strip()


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    test_job = Job(
        id="test",
        title="Product Designer",
        company="Duolingo",
        location="Berlin, Germany (Remote)",
        url="https://duolingo.com/jobs/123",
        description="Design engaging, habit-forming learning experiences for our mobile app. "
                    "You'll work on onboarding, streaks, and notifications — features that bring "
                    "40M daily users back every day. Mobile-first, data-informed, fast iteration.",
        source="test",
    )
    test_profile = CompanyProfile(
        name="Duolingo",
        website="https://duolingo.com",
        about="Duolingo makes language learning free, fun, and effective through gamification and AI.",
        values=["Engagement", "Habit formation", "Accessibility", "Delight", "Data-driven"],
        tone="playful and outcome-focused",
        perfect_candidate=(
            "Someone who thinks in engagement loops and retention mechanics. "
            "Loves mobile-first design. Has shipped consumer-facing features and measured their impact."
        ),
        recent_news="Duolingo recently launched its AI-powered conversation feature.",
    )

    cv_md = rewrite_cv(client, test_job, test_profile)
    print(cv_md)
