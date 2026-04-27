"""
PDF generator — HTML → PDF via Playwright (Chromium).

Fonts: uses Arial/DejaVu Sans/Liberation Sans so it renders correctly on both
macOS (local) and Ubuntu Linux (GitHub Actions). No -apple-system.
"""

from __future__ import annotations
import asyncio
import re
from pathlib import Path
import playwright.async_api as pw

OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"

# Safe cross-platform font stack — works on macOS AND Ubuntu (GitHub Actions)
FONT_STACK = '"Arial", "DejaVu Sans", "Liberation Sans", "Helvetica Neue", sans-serif'

CV_CSS = f"""
@page {{ size: A4; margin: 0; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
    font-family: {FONT_STACK};
    font-size: 9.5pt;
    line-height: 1.45;
    color: #1a1a1a;
}}

/* ── CV Header ── */
.cv-name {{
    font-size: 22pt;
    font-weight: 700;
    letter-spacing: -0.5px;
    line-height: 1.1;
    margin-bottom: 3px;
}}
.cv-subtitle {{
    font-size: 10pt;
    font-weight: 400;
    color: #444;
    margin-bottom: 2px;
}}
.cv-contact {{
    font-size: 8.5pt;
    color: #777;
    margin-bottom: 10px;
}}

/* ── Section headers ── */
h2 {{
    font-size: 7.5pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #111;
    border-bottom: 1px solid #ccc;
    padding-bottom: 2px;
    margin-top: 11px;
    margin-bottom: 5px;
}}

/* ── Role header: bold title left, date right ── */
.role-header {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-top: 7px;
    margin-bottom: 2px;
}}
.role-title {{ font-weight: 600; font-size: 9.5pt; }}
.role-date  {{ color: #666; font-size: 8.5pt; white-space: nowrap; padding-left: 8px; }}

/* ── Bullet list ── */
ul {{ list-style: none; padding-left: 0; margin-top: 2px; }}
ul li {{
    padding-left: 11px;
    position: relative;
    margin-bottom: 2px;
    color: #222;
}}
ul li::before {{
    content: "–";
    position: absolute;
    left: 0;
    color: #999;
}}

/* ── Body text ── */
p {{ margin-bottom: 3px; }}
"""

COVER_LETTER_CSS = f"""
@page {{ size: A4; margin: 0; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
    font-family: {FONT_STACK};
    font-size: 10.5pt;
    line-height: 1.65;
    color: #1a1a1a;
}}

/* ── Header block ── */
.cl-header {{ margin-bottom: 32px; }}
.cl-name {{
    font-size: 18pt;
    font-weight: 700;
    letter-spacing: -0.3px;
    margin-bottom: 3px;
}}
.cl-contact {{ font-size: 9pt; color: #777; }}

/* ── Addressee line (company + role) ── */
.cl-addressee {{
    font-size: 10.5pt;
    font-weight: 600;
    margin-bottom: 18px;
}}

/* ── Body ── */
p {{ margin-bottom: 14px; }}
.signature {{ margin-top: 26px; }}
"""


# ─────────────────────────────────────────────
# CV markdown → HTML
# ─────────────────────────────────────────────

def _markdown_cv_to_html(md: str) -> str:
    """
    Converts the CV markdown to HTML.

    The first 3 content lines are always: name / subtitle / contact.
    Claude doesn't add # prefixes to these — we detect them by position
    (before the first ## section header).
    """
    lines = md.split("\n")
    html: list[str] = []
    in_ul = False
    header_lines_seen = 0   # counts name/subtitle/contact lines at top
    in_header = True        # True until we hit the first ## section

    def close_ul():
        nonlocal in_ul
        if in_ul:
            html.append("</ul>")
            in_ul = False

    for line in lines:
        s = line.strip()

        # Skip our own flavour comment lines
        if s.startswith("# CV Flavour") or s.startswith("# Use for:"):
            continue

        if not s:
            close_ul()
            continue

        # ── Section header → end of CV header block ──
        if s.startswith("## "):
            in_header = False
            close_ul()
            html.append(f'<h2>{s[3:]}</h2>')
            continue

        # ── Explicit h1 (in case Claude uses it) ──
        if s.startswith("# "):
            in_header = False
            close_ul()
            html.append(f'<span class="cv-name">{s[2:]}</span>')
            continue

        # ── CV header block: first 3 lines = name / subtitle / contact ──
        if in_header:
            header_lines_seen += 1
            if header_lines_seen == 1:
                html.append(f'<div class="cv-name">{s}</div>')
            elif header_lines_seen == 2:
                html.append(f'<div class="cv-subtitle">{s}</div>')
            else:
                html.append(f'<div class="cv-contact">{s}</div>')
            continue

        # ── Role header: **Title · Company** | 2025–Present ──
        if s.startswith("**") and " | " in s:
            close_ul()
            inner = re.sub(r"\*+", "", s).strip()
            title_part, date_part = inner.rsplit(" | ", 1) if " | " in inner else (inner, "")
            html.append(
                f'<div class="role-header">'
                f'<span class="role-title">{title_part.strip()}</span>'
                f'<span class="role-date">{date_part.strip()}</span>'
                f'</div>'
            )
            continue

        # ── Bullet ──
        if s.startswith("- "):
            if not in_ul:
                html.append("<ul>")
                in_ul = True
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s[2:])
            html.append(f"<li>{content}</li>")
            continue

        # ── Skills lines: **Label:** value ──
        if s.startswith("**") and ":**" in s:
            close_ul()
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
            html.append(f"<p>{content}</p>")
            continue

        # ── Everything else ──
        close_ul()
        content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        html.append(f"<p>{content}</p>")

    close_ul()
    return "\n".join(html)


# ─────────────────────────────────────────────
# Cover letter text → HTML
# ─────────────────────────────────────────────

def _cover_letter_to_html(text: str) -> str:
    """
    Converts cover letter plain text to styled HTML.
    Detects the addressee line (Company — Role) and styles it separately.
    """
    lines = text.strip().split("\n")

    # Collect paragraphs
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        if line.strip() == "":
            if current:
                paragraphs.append(" ".join(current))
                current = []
        else:
            current.append(line.strip())
    if current:
        paragraphs.append(" ".join(current))

    # Strip off any "Liam Hasson / Berlin..." header lines Claude might include
    # (we render our own header)
    while paragraphs and (
        paragraphs[0].startswith("Liam Hasson") or
        paragraphs[0].startswith("Berlin") or
        paragraphs[0].startswith("+49")
    ):
        paragraphs.pop(0)

    parts = [
        '<div class="cl-header">',
        '<div class="cl-name">Liam Hasson</div>',
        '<div class="cl-contact">Berlin, Germany · Liamhasson@gmail.com · liamhasson.figma.site</div>',
        '</div>',
    ]

    for para in paragraphs:
        if para.startswith("Best,") or para.startswith("Best Liam") or para == "Liam Hasson":
            parts.append(f'<p class="signature">{para}</p>')
        else:
            parts.append(f"<p>{para}</p>")

    return "\n".join(parts)


# ─────────────────────────────────────────────
# Render engine
# ─────────────────────────────────────────────

def _build_html(body_html: str, css: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>{css}</style>
</head>
<body>{body_html}</body>
</html>"""


async def _render_pdf_async(html: str, output_path: Path, margins: dict) -> Path:
    """
    Renders HTML to a single A4 page PDF.
    Measures actual content height, auto-scales down if it overflows one page.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    top_mm  = float(margins["top"].replace("mm", ""))
    bot_mm  = float(margins["bottom"].replace("mm", ""))
    a4_usable_px = (297 - top_mm - bot_mm) * 96 / 25.4

    async with pw.async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 760, "height": 5000})
        await page.set_content(html, wait_until="networkidle")

        scroll_height = await page.evaluate("document.body.scrollHeight")

        if scroll_height > a4_usable_px:
            scale = max(0.6, round(a4_usable_px / scroll_height, 3))
            print(f"  [pdf] Scaling to {scale:.0%} ({scroll_height:.0f}px → {a4_usable_px:.0f}px)")
        else:
            scale = 1.0

        await page.pdf(
            path=str(output_path),
            format="A4",
            print_background=True,
            scale=scale,
            margin=margins,
        )
        await browser.close()
    return output_path


def generate_cv_pdf(cv_markdown: str, output_path: Path) -> Path:
    body = _markdown_cv_to_html(cv_markdown)
    html = _build_html(body, CV_CSS)
    margins = {"top": "14mm", "right": "16mm", "bottom": "14mm", "left": "16mm"}
    return asyncio.run(_render_pdf_async(html, output_path, margins))


def generate_cover_letter_pdf(cover_letter_text: str, output_path: Path) -> Path:
    body = _cover_letter_to_html(cover_letter_text)
    html = _build_html(body, COVER_LETTER_CSS)
    margins = {"top": "20mm", "right": "20mm", "bottom": "20mm", "left": "20mm"}
    return asyncio.run(_render_pdf_async(html, output_path, margins))


if __name__ == "__main__":
    base_dir = Path(__file__).parent.parent.parent / "base_documents"
    cv_md = (base_dir / "cv_flavour_a.md").read_text()
    out = generate_cv_pdf(cv_md, OUTPUT_DIR / "test" / "cv_test.pdf")
    print(f"CV PDF → {out}")

    sample = """Hi,

Some companies talk about moving fast. This one actually does.

On Pulse, I rebuilt the onboarding flow after 80% of test participants said the original felt too generic. Redesigned around personalised goal-setting, three rounds of iteration. A/B testing showed 70% preferred unlimited challenges, so I removed the cap entirely.

I shipped Show Date Checker as sole designer and developer — Next.js, Ticketmaster API, Vercel, live in three weeks. Not because I had to, but because I wanted to close the loop between design and reality.

Happy to show you the work.

Best, Liam Hasson"""

    out2 = generate_cover_letter_pdf(sample, OUTPUT_DIR / "test" / "cl_test.pdf")
    print(f"Cover letter PDF → {out2}")
