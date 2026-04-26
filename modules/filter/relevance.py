"""
Relevance filter — asks Claude to score each job against Liam's criteria.

WHY Claude instead of keyword matching: keyword matching misses context.
"5 years experience" buried in a paragraph, German fluency implied but not
explicit, "design-led" companies that use the word "engineer" for everyone.
Claude reads the full description and makes a judgement call, just like a
person would.

Each API call is cheap (small prompt, structured output). We run one call
per job. At 20 jobs/day across 3 sources = ~60 calls/day, negligible cost.
"""

import json
import anthropic
from modules import Job


SYSTEM_PROMPT = """You are a job relevance filter for Liam Hasson, a Product/UX Designer based in Berlin.

Your job: read a job posting and decide whether Liam should apply.

## Liam's profile
- Product Designer / UX Designer / UI Designer / Interaction Designer
- 7+ years in visual design, ~1 year formal UX experience
- Strengths: mobile-first design, AI-native workflows, shipping fast, engagement/retention thinking
- Based in Berlin, open to remote/hybrid
- Junior to mid-level (0-4 years expected in JD)
- Does NOT speak fluent German

## Filter IN — apply if the job involves:
- Product Designer, UX Designer, UI Designer, UX/UI, Interaction Designer titles
- Mobile-first, consumer apps, B2C, gaming, social, health/fitness products
- Companies that signal: shipping speed, outcome thinking, AI-native, engagement/retention
- Berlin-based or remote/hybrid
- 0-4 years experience required

## Filter OUT — reject if:
- Pure frontend or engineering role (no design responsibility)
- Explicitly requires 5+ years experience
- Explicitly requires fluent German / Deutschkenntnisse erforderlich / Deutsch fließend
- Enterprise software with zero design culture signal
- Role is clearly senior leadership (Head of Design, VP, Director) or intern-only

## Output format
Respond with ONLY valid JSON. No explanation outside the JSON.
{
  "is_relevant": true | false,
  "score": 1-10,
  "reason": "2-3 sentence plain explanation of why relevant or not",
  "deal_breakers": ["list any hard disqualifiers found, empty array if none"]
}"""


def filter_job(client: anthropic.Anthropic, job: Job) -> dict:
    """
    Returns a dict with keys: is_relevant (bool), score (int), reason (str),
    deal_breakers (list[str]).
    """
    prompt = f"""Job title: {job.title}
Company: {job.company}
Location: {job.location}
Source: {job.source}

Job description:
{job.description or "(no description available)"}

Is this relevant for Liam? Respond with JSON only."""

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    # Strip markdown code fences if Claude wraps the JSON
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def filter_jobs(client: anthropic.Anthropic, jobs: list[Job]) -> list[tuple[Job, dict]]:
    """
    Returns only the relevant jobs as (job, filter_result) tuples, sorted by score desc.
    """
    results = []
    for job in jobs:
        try:
            result = filter_job(client, job)
            print(
                f"  {'✓' if result['is_relevant'] else '✗'} "
                f"[{result['score']}/10] {job.title} @ {job.company}"
            )
            if result["is_relevant"]:
                results.append((job, result))
        except Exception as e:
            print(f"  [filter] Error on {job.title} @ {job.company}: {e}")
            continue

    results.sort(key=lambda x: x[1]["score"], reverse=True)
    return results


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Test with a fake job
    test_job = Job(
        id="test123",
        title="Product Designer",
        company="Acme Berlin",
        location="Berlin, Germany",
        url="https://example.com/job/123",
        description="""
        We are looking for a Product Designer to join our mobile-first consumer app team.
        You'll work on engagement features, onboarding flows, and the core booking experience.
        2-3 years of UX/product design experience required. Figma expert.
        Nice to have: experience with A/B testing, design systems.
        English working environment. Berlin office, hybrid ok.
        """,
        source="test",
    )

    result = filter_job(client, test_job)
    print(json.dumps(result, indent=2))
