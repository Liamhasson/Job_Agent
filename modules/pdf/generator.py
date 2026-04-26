"""
PDF generator — HTML → PDF via Playwright (Chromium).

WHY Playwright instead of WeasyPrint: WeasyPrint requires GTK system libraries
(pango, gobject) that aren't available on stock macOS or minimal Linux. Since
we already have Playwright installed for scraping, we use its built-in
page.pdf() which leverages Chromium's print engine — full CSS support, no
extra system deps, and the same output quality as "Print to PDF" in Chrome.
"""

from __future__ import annotations
import asyncio
import re
from pathlib import Path
import playwright.async_api as pw

OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"

CV_CSS = """
@page {
    size: A4;
    margin: 0;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: -apple-system, "Helvetica Neue", Arial, sans-serif;
    font-size: 9.5pt;
    line-height: 1.45;
    color: #1a1a1a;
}

h1 {
    font-size: 18pt;
    font-weight: 700;
    letter-spacing: -0.3px;
    margin-bottom: 2px;
}

.subtitle {
    font-size: 9pt;
    color: #555;
    margin-bottom: 8px;
}

h2 {
    font-size: 8pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    border-bottom: 1px solid #ddd;
    padding-bottom: 2px;
    margin-top: 10px;
    margin-bottom: 5px;
}

.role-header {
    display: flex;
    justify-content: space-between;
    margin-top: 6px;
    margin-bottom: 2px;
}

.role-title { font-weight: 600; font-size: 9.5pt; }
.role-date  { color: #666; font-size: 8.5pt; white-space: nowrap; }

ul {
    list-style: none;
    padding-left: 0;
    margin-top: 2px;
}

ul li {
    padding-left: 10px;
    position: relative;
    margin-bottom: 1.5px;
}

ul li::before {
    content: "–";
    position: absolute;
    left: 0;
    color: #999;
}

p { margin-bottom: 3px; }
"""

COVER_LETTER_CSS = """
@page {
    size: A4;
    margin: 0;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: -apple-system, "Helvetica Neue", Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.65;
    color: #1a1a1a;
}

.header { margin-bottom: 28px; }
.header .name { font-size: 13pt; font-weight: 700; margin-bottom: 2px; }
.header .contact { font-size: 9pt; color: #666; }

p { margin-bottom: 13px; }
.signature { margin-top: 24px; }
"""


def _markdown_cv_to_html(md: str) -> str:
    lines = md.split("\n")
    html = []
    in_ul = False

    def close_ul():
        nonlocal in_ul
        if in_ul:
            html.append("</ul>")
            in_ul = False

    for line in lines:
        s = line.strip()

        # Skip flavour comment lines
        if s.startswith("# CV Flavour") or s.startswith("# Use for:"):
            continue

        if not s:
            close_ul()
            continue

        if s.startswith("# "):
            close_ul()
            html.append(f"<h1>{s[2:]}</h1>")

        elif s.startswith("## "):
            close_ul()
            html.append(f"<h2>{s[3:]}</h2>")

        elif s.startswith("**") and " | " in s:
            close_ul()
            inner = s.strip("*").strip()
            title_part, date_part = inner.rsplit(" | ", 1) if " | " in inner else (inner, "")
            title_clean = re.sub(r"\*+", "", title_part).strip()
            html.append(
                f'<div class="role-header">'
                f'<span class="role-title">{title_clean}</span>'
                f'<span class="role-date">{date_part}</span>'
                f'</div>'
            )

        elif s.startswith("- "):
            if not in_ul:
                html.append("<ul>")
                in_ul = True
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s[2:])
            html.append(f"<li>{content}</li>")

        elif s.startswith("**") and ":**" in s:
            close_ul()
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
            html.append(f"<p>{content}</p>")

        else:
            close_ul()
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
            html.append(f"<p>{content}</p>")

    close_ul()
    return "\n".join(html)


def _cover_letter_to_html(text: str) -> str:
    parts = [
        '<div class="header">',
        '<div class="name">Liam Hasson</div>',
        '<div class="contact">Berlin, Germany · Liamhasson@gmail.com · liamhasson.figma.site</div>',
        "</div>",
    ]
    paragraphs: list[str] = []
    current: list[str] = []
    for line in text.strip().split("\n"):
        if line.strip() == "":
            if current:
                paragraphs.append(" ".join(current))
                current = []
        else:
            current.append(line.strip())
    if current:
        paragraphs.append(" ".join(current))

    for para in paragraphs:
        css_class = "signature" if para.startswith("Best,") else ""
        attr = f' class="{css_class}"' if css_class else ""
        parts.append(f"<p{attr}>{para}</p>")

    return "\n".join(parts)


def _build_html(body_html: str, css: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>{css}</style>
</head>
<body>{body_html}</body>
</html>"""


async def _render_pdf_async(
    html: str,
    output_path: Path,
    margins: dict,
    a4_usable_height_mm: float,
) -> Path:
    """
    Renders HTML to a single A4 page PDF.

    Strategy: render at a tall viewport first to measure true content height,
    then calculate a scale factor so everything fits in one page without
    cutting anything off. Scale only shrinks (never upscales).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # A4 usable height in pixels at 96dpi: (297mm - top_margin - bottom_margin) * 96/25.4
    top_mm = float(margins["top"].replace("mm", ""))
    bot_mm = float(margins["bottom"].replace("mm", ""))
    usable_mm = 297 - top_mm - bot_mm
    a4_usable_px = usable_mm * 96 / 25.4

    async with pw.async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Tall viewport so nothing is clipped during height measurement
        page = await browser.new_page(viewport={"width": 760, "height": 5000})
        await page.set_content(html, wait_until="networkidle")

        scroll_height = await page.evaluate("document.body.scrollHeight")

        if scroll_height > a4_usable_px:
            scale = a4_usable_px / scroll_height
            scale = max(0.6, round(scale, 3))  # floor at 60% — Claude should keep content tight
            print(f"  [pdf] Scaling to {scale:.0%} to fit A4 ({scroll_height:.0f}px → {a4_usable_px:.0f}px)")
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
    return asyncio.run(_render_pdf_async(html, output_path, margins, a4_usable_height_mm=269))


def generate_cover_letter_pdf(cover_letter_text: str, output_path: Path) -> Path:
    body = _cover_letter_to_html(cover_letter_text)
    html = _build_html(body, COVER_LETTER_CSS)
    margins = {"top": "20mm", "right": "20mm", "bottom": "20mm", "left": "20mm"}
    return asyncio.run(_render_pdf_async(html, output_path, margins, a4_usable_height_mm=257))


if __name__ == "__main__":
    base_dir = Path(__file__).parent.parent.parent / "base_documents"
    cv_md = (base_dir / "cv_flavour_a.md").read_text()
    out = generate_cv_pdf(cv_md, OUTPUT_DIR / "test" / "cv_test.pdf")
    print(f"CV PDF → {out}")

    sample = """Hi,

Some companies talk about moving fast. This one actually does — shipping weekly, measuring what changes, cutting what doesn't.

On Pulse, I rebuilt the onboarding flow after 80% of test participants said the original felt too generic. Redesigned around personalised goal-setting, three rounds of iteration. A/B testing on the challenge system showed 70% preferred unlimited, so I removed the cap entirely.

I also shipped Show Date Checker as sole designer and developer — Next.js, Ticketmaster API, Vercel, live in three weeks. Not because I had to, but because I wanted to close the loop between design and reality.

Happy to show you the work.

Best, Liam Hasson"""

    out2 = generate_cover_letter_pdf(sample, OUTPUT_DIR / "test" / "cl_test.pdf")
    print(f"Cover letter PDF → {out2}")
