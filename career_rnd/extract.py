"""Text extraction from PDF/HTML/text and section detection."""

import re
import sqlite3
from pathlib import Path


# Section patterns and their weights
SECTION_PATTERNS = {
    "must": {
        "weight": 1.0,
        "patterns_en": [
            r"(?i)must[\s-]*have",
            r"(?i)required?\s*(skills?|qualifications?|experience)",
            r"(?i)minimum\s*(requirements?|qualifications?)",
            r"(?i)essential",
        ],
        "patterns_ja": [
            r"必須",
            r"必要な",
            r"要件",
        ],
    },
    "want": {
        "weight": 0.6,
        "patterns_en": [
            r"(?i)nice[\s-]*to[\s-]*have",
            r"(?i)preferred",
            r"(?i)desired",
            r"(?i)bonus",
            r"(?i)plus",
            r"(?i)optional",
        ],
        "patterns_ja": [
            r"歓迎",
            r"あれば",
            r"尚可",
        ],
    },
    "responsibility": {
        "weight": 0.8,
        "patterns_en": [
            r"(?i)responsibilit",
            r"(?i)duties",
            r"(?i)what\s+you.ll\s+do",
            r"(?i)role\s+description",
            r"(?i)job\s+description",
        ],
        "patterns_ja": [
            r"職務",
            r"業務内容",
            r"担当",
        ],
    },
    "profile": {
        "weight": 0.5,
        "patterns_en": [
            r"(?i)about\s+you",
            r"(?i)who\s+you\s+are",
            r"(?i)traits?",
            r"(?i)personality",
            r"(?i)mindset",
        ],
        "patterns_ja": [
            r"求める人物像",
            r"人物",
        ],
    },
}

DEFAULT_WEIGHT = 0.3  # "other" sections


def extract_text(file_path: str) -> str:
    """Extract raw text from a file (PDF, HTML, or plain text).

    Args:
        file_path: Path to the file.

    Returns:
        Extracted text as a string.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return _extract_pdf(path)
    elif suffix in (".html", ".htm"):
        return _extract_html(path)
    else:
        return path.read_text(encoding="utf-8")


def _extract_pdf(path: Path) -> str:
    """Extract text from a PDF file using PyMuPDF."""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(str(path))
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return "\n".join(text_parts)
    except ImportError:
        raise ImportError("PyMuPDF (fitz) is required for PDF extraction. Install with: pip install pymupdf")


def _extract_html(path: Path) -> str:
    """Extract text from an HTML file using BeautifulSoup."""
    from bs4 import BeautifulSoup

    html_content = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html_content, "lxml")

    # Remove script and style elements
    for element in soup(["script", "style", "nav", "footer", "header"]):
        element.decompose()

    return soup.get_text(separator="\n", strip=True)


def sectionize(text: str) -> list[dict]:
    """Detect sections in job description text and assign weights.

    Returns a list of dicts with keys: text, section, weight.
    Each item represents a line/phrase within a detected section.
    """
    lines = text.strip().split("\n")
    results = []
    current_section = "other"
    current_weight = DEFAULT_WEIGHT

    for line in lines:
        stripped = line.strip()
        if not stripped or len(stripped) < 2:
            continue

        # Check if this line is a section header
        detected = _detect_section(stripped)
        if detected:
            current_section = detected
            current_weight = SECTION_PATTERNS.get(detected, {}).get("weight", DEFAULT_WEIGHT)
            continue

        # Skip header-like lines (company, location, title)
        if _is_metadata_line(stripped):
            continue

        # It's a content line within the current section
        # Clean up bullet points
        content = re.sub(r"^[-•·*]\s*", "", stripped)
        if content and len(content) > 2:
            results.append({
                "text": content,
                "section": current_section,
                "weight": current_weight,
            })

    return results


def _detect_section(line: str) -> str | None:
    """Detect if a line is a section header. Returns section type or None."""
    for section_type, config in SECTION_PATTERNS.items():
        for pattern in config.get("patterns_en", []) + config.get("patterns_ja", []):
            if re.search(pattern, line):
                return section_type
    return None


def _is_metadata_line(line: str) -> bool:
    """Check if a line is metadata (company, location, etc.) rather than content."""
    metadata_patterns = [
        r"(?i)^(company|location|salary|contract|employment)\s*:",
        r"(?i)^(会社|勤務地|給与|雇用形態)\s*:",
    ]
    for pattern in metadata_patterns:
        if re.search(pattern, line):
            return True
    return False


def extract_and_store(conn: sqlite3.Connection, do_sectionize: bool = True) -> int:
    """Extract text for all roles that haven't been extracted yet.

    This is a preliminary extraction step. The actual phrase storage
    happens during LLM skill extraction (career skills extract).

    Returns the number of roles processed.
    """
    cursor = conn.execute(
        "SELECT role_id, raw_text_path FROM roles WHERE raw_text_path IS NOT NULL"
    )
    roles = cursor.fetchall()
    count = 0

    for role in roles:
        role_id = role[0] if isinstance(role, tuple) else role["role_id"]
        raw_path = role[1] if isinstance(role, tuple) else role["raw_text_path"]

        # Check if phrases already exist for this role
        existing = conn.execute(
            "SELECT COUNT(*) FROM phrases WHERE role_id=?", (role_id,)
        ).fetchone()[0]
        if existing > 0:
            continue

        # Verify we can extract text from this file
        text = extract_text(raw_path)
        if not text or len(text.strip()) < 10:
            continue

        count += 1

    return count
