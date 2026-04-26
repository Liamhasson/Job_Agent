"""
Cover letter writer module.

This is the hardest module to get right. The goal is to sound like Liam wrote it —
not like an AI generated a cover letter. The system prompt loads both example
letters and the voice rules, so Claude has concrete examples of the actual voice,
not an abstract description of it.

Key technique: we show Claude the real letters as "what to sound like", then
explicitly tell it NOT to copy their content — only the voice and structure.
"""

from __future__ import annotations
import anthropic
from pathlib import Path
from modules import Job, CompanyProfile

BASE_DIR = Path(__file__).parent.parent.parent / "base_documents"


def _load_voice_materials() -> dict[str, str]:
    return {
        "rules": (BASE_DIR / "voice_rules.md").read_text(),
        "example_a": (BASE_DIR / "cover_letter_gameduel.md").read_text(),
        "example_b": (BASE_DIR / "cover_letter_avaloq.md").read_text(),
    }


SYSTEM_PROMPT = """You are writing a cover letter for Liam Hasson, a Product/UX Designer based in Berlin.

Your single most important job: sound exactly like Liam. Not like an AI. Not like a generic cover letter.

You have two real letters Liam wrote as examples. Study them carefully — the voice, the structure,
the specificity, the confidence, the self-awareness. Then write a new letter for a new company.

## What you must NOT do:
- Copy sentences or paragraphs from the example letters
- Open with "I am writing to apply" or "I am excited to" or any corporate opener
- Say "I would be a great fit" or "I am passionate about"
- Pad with filler sentences
- End with grovelling ("I hope to hear from you", "Thank you for your consideration")
- Exceed 400 words
- Reference skills or experience that don't appear in Liam's CV

## What you MUST do:
- Open with a hook: an insight about the company, a reframe of their mission, a bold claim about Liam's approach
- Reference something genuinely specific about this company (from the company profile provided)
- Tell 1-2 project stories that are most relevant to this specific role
- Use real numbers and specific outcomes where they exist (80%, 70%, 6 participants, 4 failures, etc.)
- End with a short, confident close — one line + "Best, Liam Hasson"
- Keep it under 400 words

## Tone calibration:
- Engagement/gaming/consumer apps → narrative, personal, warm (GameDuell example style)
- AI/product/shipping/generalist → punchy, outcome-led, self-aware (Avaloq example style)
- Default when unsure: bold opening claim + 2 relevant project stories + specific company hook + confident close

## Greeting:
- If you know the hiring manager's name from the job description, use "Hi [Name],"
- Otherwise use "Hi," — never "Dear Hiring Manager" or "To Whom It May Concern"

## Structure (loose guide, not rigid template):
Line 1-2: The hook — ties directly to the company
Para 2: The most relevant project story with specifics
Para 3 (optional): Second story or broader context (band, shipping own product, AI workflow)
Final line: Short, confident close
Signature: "Best, Liam Hasson"

Output ONLY the letter text. No subject line, no address block, no commentary."""


def write_cover_letter(
    client: anthropic.Anthropic,
    job: Job,
    company_profile: CompanyProfile,
) -> str:
    """Returns the tailored cover letter as a plain text string."""
    materials = _load_voice_materials()

    prompt = f"""## Example letter A (GameDuell — engagement/narrative style):
{materials["example_a"]}

---

## Example letter B (Avaloq — punchy/outcome style):
{materials["example_b"]}

---

## Voice rules:
{materials["rules"]}

---

## Now write a NEW letter for this job. Do NOT copy from the examples — match the voice only.

Job: {job.title} at {job.company}
Location: {job.location}

Company profile:
- About: {company_profile.about}
- Values: {", ".join(company_profile.values)}
- Tone: {company_profile.tone}
- What they want: {company_profile.perfect_candidate}
{f"- Recent context: {company_profile.recent_news}" if company_profile.recent_news else ""}

Job description:
{job.description or "(not available)"}

Write the letter now. Under 400 words. Sound like a real person."""

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1500,
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
        title="UX Designer — Mobile",
        company="Blinkist",
        location="Berlin, Germany",
        url="https://blinkist.com/careers/123",
        description=(
            "Join our mobile team to design features that help 26M users build better reading habits. "
            "You'll own the onboarding experience and the daily recommendation flow. "
            "We ship fast, measure everything, and care deeply about habit formation."
        ),
        source="test",
    )
    test_profile = CompanyProfile(
        name="Blinkist",
        website="https://blinkist.com",
        about="Blinkist distils key ideas from nonfiction books into 15-minute reads, helping people learn faster.",
        values=["Habit formation", "Learning", "Accessibility", "Speed", "Impact"],
        tone="warm and outcome-focused",
        perfect_candidate=(
            "A mobile-first designer who thinks in habits and feedback loops. "
            "Someone who measures the impact of their work and iterates based on real data. "
            "Comfortable with ambiguity, fast shipping cycles, and cross-functional collaboration."
        ),
        recent_news="Blinkist was acquired by Go1 in 2023 and has been expanding its content library.",
    )

    letter = write_cover_letter(client, test_job, test_profile)
    print(letter)
    print(f"\n--- Word count: {len(letter.split())} ---")
