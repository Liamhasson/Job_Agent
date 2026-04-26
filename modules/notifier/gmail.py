"""
Gmail notifier module.

Sends an email to Liam with:
  - Subject: "Job match: [Title] @ [Company]"
  - Body: why it's relevant, company summary, word count on cover letter
  - Attachments: tailored CV (PDF) + cover letter (PDF)
  - Apply link: direct link to the job posting

Authentication:
  Uses OAuth2 via google-auth. On first run, you complete a browser flow once
  and the token is saved. After that it auto-refreshes silently.

  In GitHub Actions: credentials and token are stored as secrets, passed as
  JSON env vars (see .env.example).
"""

from __future__ import annotations
import base64
import json
import os
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from modules import ApplicationPackage

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
TOKEN_PATH = Path(__file__).parent.parent.parent / "config" / "gmail_token.json"
CREDENTIALS_PATH = Path(__file__).parent.parent.parent / "config" / "gmail_credentials.json"


def _get_credentials() -> Credentials:
    """
    Load credentials from:
    1. GMAIL_TOKEN_JSON env var (GitHub Actions / production)
    2. config/gmail_token.json file (local dev, after first auth)
    Falls back to OAuth browser flow if neither exists.
    """
    creds = None

    # Production: credentials come from environment variables
    token_env = os.environ.get("GMAIL_TOKEN_JSON")
    creds_env = os.environ.get("GMAIL_CREDENTIALS_JSON")

    if token_env:
        creds = Credentials.from_authorized_user_info(json.loads(token_env), SCOPES)

    elif TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Save refreshed token locally if we're in local mode
        if not token_env and TOKEN_PATH.parent.exists():
            TOKEN_PATH.write_text(creds.to_json())
        return creds

    if creds and creds.valid:
        return creds

    # First-time local setup: browser OAuth flow
    if creds_env:
        creds_info = json.loads(creds_env)
    elif CREDENTIALS_PATH.exists():
        creds_info = json.loads(CREDENTIALS_PATH.read_text())
    else:
        raise RuntimeError(
            "No Gmail credentials found. "
            "Set GMAIL_CREDENTIALS_JSON env var or place credentials at "
            f"{CREDENTIALS_PATH}. See README for setup instructions."
        )

    flow = InstalledAppFlow.from_client_config(creds_info, SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json())
    print(f"[gmail] Token saved to {TOKEN_PATH}")
    return creds


def _build_email_body(pkg: ApplicationPackage, filter_reason: str) -> str:
    profile = pkg.company_profile
    job = pkg.job

    word_count = len(pkg.cover_letter_markdown.split())

    return f"""<html><body style="font-family: -apple-system, Helvetica, Arial, sans-serif; font-size: 14px; color: #1a1a1a; max-width: 600px; margin: 0 auto; padding: 20px;">

<h2 style="margin-bottom: 4px;">{job.title} @ {job.company}</h2>
<p style="color: #666; margin-top: 0;">{job.location} · via {job.source}</p>

<hr style="border: none; border-top: 1px solid #eee; margin: 16px 0;">

<h3 style="margin-bottom: 6px;">Why it matched</h3>
<p>{filter_reason}</p>

<h3 style="margin-bottom: 6px;">Company</h3>
<p>{profile.about}</p>
<p><strong>Values:</strong> {", ".join(profile.values)}</p>
<p><strong>Tone:</strong> {profile.tone}</p>
{f'<p><strong>Recent context:</strong> {profile.recent_news}</p>' if profile.recent_news else ''}

<hr style="border: none; border-top: 1px solid #eee; margin: 16px 0;">

<h3 style="margin-bottom: 6px;">What was generated</h3>
<ul>
  <li>Tailored CV — attached as <strong>CV_{job.company.replace(" ", "_")}.pdf</strong></li>
  <li>Cover letter — attached as <strong>CoverLetter_{job.company.replace(" ", "_")}.pdf</strong> ({word_count} words)</li>
</ul>

<hr style="border: none; border-top: 1px solid #eee; margin: 16px 0;">

<p>
  <a href="{job.url}" style="display: inline-block; background: #000; color: #fff; padding: 10px 20px; text-decoration: none; border-radius: 4px; font-weight: 600;">
    Apply → {job.url}
  </a>
</p>

<p style="color: #999; font-size: 12px; margin-top: 20px;">
  Job found on {job.date_found[:10]} via {job.source}
</p>

</body></html>"""


def send_notification(
    pkg: ApplicationPackage,
    filter_reason: str,
    recipient: str,
    sender: str,
) -> None:
    """Send the application package as an email with PDF attachments."""
    creds = _get_credentials()
    service = build("gmail", "v1", credentials=creds)

    job = pkg.job
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"Job match: {job.title} @ {job.company}"
    msg["From"] = sender
    msg["To"] = recipient

    # HTML body
    html_body = _build_email_body(pkg, filter_reason)
    msg.attach(MIMEText(html_body, "html"))

    # Attach CV PDF
    cv_path = Path(pkg.cv_pdf_path)
    if cv_path.exists():
        with open(cv_path, "rb") as f:
            pdf = MIMEApplication(f.read(), _subtype="pdf")
            pdf.add_header(
                "Content-Disposition",
                "attachment",
                filename=f"CV_{job.company.replace(' ', '_')}.pdf",
            )
            msg.attach(pdf)

    # Attach cover letter PDF
    cl_path = Path(pkg.cover_letter_pdf_path)
    if cl_path.exists():
        with open(cl_path, "rb") as f:
            pdf = MIMEApplication(f.read(), _subtype="pdf")
            pdf.add_header(
                "Content-Disposition",
                "attachment",
                filename=f"CoverLetter_{job.company.replace(' ', '_')}.pdf",
            )
            msg.attach(pdf)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    print(f"[gmail] Email sent for {job.title} @ {job.company}")


if __name__ == "__main__":
    """
    First-time setup test. Run this locally once to authenticate and verify
    Gmail is wired up correctly. It sends a test email to yourself.
    """
    import os
    from dotenv import load_dotenv
    from modules import Job, CompanyProfile, ApplicationPackage
    load_dotenv()

    test_pkg = ApplicationPackage(
        job=Job(
            id="test",
            title="Product Designer",
            company="Test Company",
            location="Berlin, Germany",
            url="https://example.com/jobs/123",
            description="Test job",
            source="test",
        ),
        company_profile=CompanyProfile(
            name="Test Company",
            website="https://example.com",
            about="A test company for testing the email pipeline.",
            values=["Testing", "Quality"],
            tone="test tone",
            perfect_candidate="A tester who likes testing.",
        ),
        cv_markdown="# Liam Hasson\nTest CV content",
        cover_letter_markdown="Test cover letter content",
        cv_pdf_path="/tmp/test_cv.pdf",
        cover_letter_pdf_path="/tmp/test_cl.pdf",
    )

    recipient = os.environ.get("RECIPIENT_EMAIL", "liamhasson@gmail.com")
    sender = os.environ.get("SENDER_EMAIL", "liamhasson@gmail.com")

    print("[gmail] Sending test email...")
    send_notification(test_pkg, "This is a test — no real job match.", recipient, sender)
    print("[gmail] Done.")
