from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Job:
    id: str                    # unique hash of company+title+url
    title: str
    company: str
    location: str
    url: str
    description: str
    source: str                # "linkedin" | "indeed" | "stepstone"
    date_found: str = field(default_factory=lambda: datetime.now().isoformat())
    salary: Optional[str] = None


@dataclass
class CompanyProfile:
    name: str
    website: Optional[str]
    about: str                 # synthesised from about/culture pages
    values: list[str]
    tone: str                  # e.g. "technical and precise", "warm and mission-driven"
    perfect_candidate: str     # Claude's synthesis of what they're really looking for
    recent_news: Optional[str] = None


@dataclass
class ApplicationPackage:
    job: Job
    company_profile: CompanyProfile
    cv_markdown: str
    cover_letter_markdown: str
    cv_pdf_path: str
    cover_letter_pdf_path: str
