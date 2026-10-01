"""Turn an invoice file into page-tagged plain text.

OCR is out of scope (the brief says text is available), so PDFs are read from their text layer.
pypdf's layout mode keeps label/value pairs on the same line, which matters for table-heavy bills.
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md"}
logging.getLogger("pypdf").setLevel(logging.ERROR)  # font warnings are expected; completeness is checked below


@dataclass(frozen=True)
class Document:
    path: Path
    pages: list[str]

    @property
    def text(self) -> str:
        return "\n\n".join(self.pages)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def tagged_text(self) -> str:
        """Pages wrapped in tags so the model can cite page numbers."""
        return "\n".join(
            f'<page number="{i}">\n{page}\n</page>' for i, page in enumerate(self.pages, start=1)
        )


def load_document(path: Path) -> Document:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        pages = [_clean(_pdf_page_text(page)) for page in PdfReader(path).pages]
    elif suffix in {".txt", ".md"}:
        pages = [_clean(path.read_text(encoding="utf-8"))]
    else:
        raise ValueError(f"Unsupported file type: {path.name}")
    if not any(pages):
        raise ValueError(f"No text layer in {path.name} (scanned image? OCR is out of scope)")
    return Document(path=path, pages=pages)


def find_documents(inputs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for item in inputs:
        if item.is_dir():
            files.extend(sorted(p for p in item.iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES))
        else:
            files.append(item)
    return files


def _pdf_page_text(page) -> str:
    """Layout mode when it is complete, plain mode otherwise.

    Layout mode keeps labels beside their values, but it silently drops rotated text: on two of
    the sample bills it kept under 25% of the characters. So it is only used when it retains
    almost everything plain mode finds.
    """
    plain = page.extract_text() or ""
    try:
        layout = page.extract_text(extraction_mode="layout") or ""
    except Exception:  # layout mode trips on some malformed fonts
        return plain
    if _visible_chars(layout) >= 0.95 * _visible_chars(plain):
        return layout
    return plain


def _visible_chars(text: str) -> int:
    return len(re.sub(r"\s", "", text))


def _clean(text: str) -> str:
    # Layout mode pads columns with long runs of spaces; three keep columns readable at a
    # fraction of the tokens.
    text = re.sub(r"[ \t]{4,}", "   ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
