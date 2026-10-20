"""Turn an SEC filing (an HTML document) into labelled passages the assistant can cite.

Steps
1. Strip the HTML: hidden XBRL data is removed, and each table row becomes one line with
   cells separated by " | ", so tables stay readable.
2. Follow the filing's structure: "Item 7." style headings (with "Part II" in 10-Qs) and
   ALL-CAPS subheadings, so every passage knows where it came from.
3. Cut the text into passages of a few hundred words that never cross an Item boundary.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "filings"
PASSAGE_WORDS = 450        # target size of each passage
MIN_PASSAGE_WORDS = 30     # smaller fragments (page footers, table-of-contents lines) are dropped

_ITEM = re.compile(r"^item\s+(\d{1,2}[a-c]?)\s*[\.\:\-–—]?\s*(.*)$", re.IGNORECASE)
_PART = re.compile(r"^part\s+(i{1,3}|iv)\b", re.IGNORECASE)
_PAGE_NOISE = re.compile(r"^(\d{1,3}|page \d+|table of contents|table of|contents|index)$",
                         re.IGNORECASE)   # page numbers and repeated page headers


@dataclass
class Passage:
    filing: str        # e.g. "10-K for the period ending 2025-12-31 (filed 2026-02-07)"
    section: str       # e.g. "Item 7. Management's discussion and analysis › Credit quality"
    text: str
    url: str


def html_to_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    for hidden in soup.find_all(style=re.compile(r"display:\s*none", re.IGNORECASE)):
        hidden.decompose()                       # inline XBRL's hidden data section
    for tag in soup(["script", "style"]):
        tag.decompose()
    for row in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
        cells = [c for c in cells if c and c not in {"$", "%", ")"}]
        row.replace_with(soup.new_string(("\n" + " | ".join(cells) + "\n") if cells else "\n"))
    text = soup.get_text("\n").replace("\xa0", " ")
    lines = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line and not _PAGE_NOISE.match(line):
            lines.append(line)
    return lines


def _sentence_case(text: str) -> str:
    text = text.strip(" .:")
    return text[:1].upper() + text[1:].lower() if text.isupper() else text


def _is_heading(line: str) -> bool:
    letters = re.sub(r"[^A-Za-z]", "", line)
    return (line.isupper() and 4 <= len(line) <= 90 and len(letters) >= 4
            and not _ITEM.match(line) and " | " not in line)


def _item_title(title: str) -> str:
    """Tidy an item title: "| Financial Statements | 77" -> "Financial statements"."""
    title = re.sub(r"\s*\|\s*\d*\s*$", "", title.strip(" |"))
    title = title.replace(" | ", " ").strip()
    if title.upper().startswith(("MANAGEMENT’S DISCUSSION", "MANAGEMENT'S DISCUSSION")):
        return "Management’s discussion and analysis (MD&A)"
    title = _sentence_case(title)
    return title if len(title) <= 70 else title[:67].rsplit(" ", 1)[0] + "…"


def split_passages(lines: list[str], filing: str, url: str, form: str = "",
                   target_words: int = PASSAGE_WORDS) -> list[Passage]:
    passages: list[Passage] = []
    part, item, heading = "", "", ""
    table_header = ""
    buffer: list[str] = []

    def section_label() -> str:
        label = item or "Cover and introduction"
        if part == "II" and item and form.startswith("10-Q"):   # 10-Q item numbers repeat
            label = f"Part II, {label}"
        return f"{label} › {heading}" if heading and heading.lower() not in label.lower() else label

    def flush():
        words = sum(len(l.split()) for l in buffer)
        if words >= MIN_PASSAGE_WORDS:
            passages.append(Passage(filing, section_label(), "\n".join(buffer), url))
        buffer.clear()

    for i, line in enumerate(lines):
        if (m := _PART.match(line)) and len(line) < 80:
            flush()
            part = m.group(1).upper()
            continue
        if (m := _ITEM.match(line)) and len(line) < 200:
            flush()
            title = m.group(2)
            if not title and i + 1 < len(lines) and len(lines[i + 1]) < 120:
                title = lines[i + 1]            # title on the next line ("Item 1." / "Business")
            item = f"Item {m.group(1).upper()}. {_item_title(title)}".rstrip(". ")
            heading = ""
            continue
        if _is_heading(line):
            if sum(len(l.split()) for l in buffer) >= MIN_PASSAGE_WORDS:
                flush()
            heading = _sentence_case(line)[:60]
            continue
        # Remember the first row of each table: it usually holds the column headings
        # (which year each number belongs to).
        if " | " in line and not (buffer and " | " in buffer[-1]):
            table_header = line
        elif " | " not in line:
            table_header = ""
        buffer.append(line)
        words = sum(len(l.split()) for l in buffer)
        # Prefer not to cut a table in half; allow up to 3x the target to finish it. If a
        # table is longer still, the next passage starts by repeating its heading row.
        in_table = " | " in line and i + 1 < len(lines) and " | " in lines[i + 1]
        if words >= target_words and (not in_table or words >= 3 * target_words):
            flush()
            if in_table and table_header:
                buffer.append(f"{table_header} (table continued)")
    flush()
    return passages


def filing_passages(download_text, url: str, filing: str, form: str = "") -> list[Passage]:
    """Passages for one filing. `download_text(url) -> str` fetches the HTML; the cleaned
    text is saved so each filing is downloaded and parsed only once."""
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    cache_file = CACHE_DIR / f"{key}.txt"
    if cache_file.exists():
        lines = cache_file.read_text(encoding="utf-8").splitlines()
    else:
        lines = html_to_lines(download_text(url))
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("\n".join(lines), encoding="utf-8")
    return split_passages(lines, filing, url, form)
