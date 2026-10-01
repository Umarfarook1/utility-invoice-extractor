"""Package pipeline outputs for the static showcase site.

    python web/build.py      # after running the pipeline and the evaluation

Writes web/public/data.json and copies the sample PDFs and the CSV next to it. Evidence
highlights are located here with the same whitespace-insensitive matching the grounder uses,
so a quote is highlighted exactly when the pipeline considered it grounded.
"""

import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from invoice_extractor.ingest import load_document  # noqa: E402
from invoice_extractor.normalize import date_order, uses_decimal_comma  # noqa: E402
from invoice_extractor.prompts import PROMPT_VERSION  # noqa: E402

PUBLIC = ROOT / "web" / "public"
INVOICE_FIELDS = ["vendor_name", "invoice_number", "invoice_date", "service_address", "total_amount"]
SERVICE_FIELDS = ["usage", "billing_period_start", "billing_period_end"]


def quote_pattern(quote: str) -> re.Pattern | None:
    chars = [re.escape(c) for c in re.sub(r"\s+", "", quote)]
    return re.compile(r"\s*".join(chars), re.IGNORECASE) if chars else None


def segments(page_text: str, quotes: list[tuple[str, str]]) -> list[dict]:
    """Split a page into runs of text, each tagged with the fields whose quote covers it."""
    marks = [set() for _ in page_text]
    for field, quote in quotes:
        pattern = quote_pattern(quote)
        match = pattern.search(page_text) if pattern else None
        if match:
            for i in range(match.start(), match.end()):
                marks[i].add(field)
    out: list[dict] = []
    for char, fields in zip(page_text, marks):
        key = sorted(fields)
        if out and out[-1]["f"] == key:
            out[-1]["t"] += char
        else:
            out.append({"t": char, "f": key})
    return out


def collect_quotes(extraction: dict) -> dict[int, list[tuple[str, str]]]:
    by_page: dict[int, list[tuple[str, str]]] = {}

    def add(field: str, sourced: dict) -> None:
        if sourced and sourced.get("source_text") and sourced.get("page"):
            by_page.setdefault(sourced["page"], []).append((field, sourced["source_text"]))

    for name in INVOICE_FIELDS:
        add(name, extraction.get(name))
    for index, service in enumerate(extraction.get("services", [])):
        for name in SERVICE_FIELDS:
            add(f"s{index}.{name}", service.get(name))
    return by_page


def main() -> int:
    records = [json.loads(l) for l in (ROOT / "output" / "extractions.jsonl").read_text(encoding="utf-8").splitlines()]
    labels = json.loads((ROOT / "ground_truth" / "labels.json").read_text(encoding="utf-8"))["invoices"]
    summary_path = ROOT / "output" / "eval_summary.json"
    evaluation = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else None
    sources = (ROOT / "samples" / "SOURCES.md").read_text(encoding="utf-8")

    (PUBLIC / "invoices").mkdir(parents=True, exist_ok=True)
    invoices = []
    for record in records:
        path = ROOT / "samples" / "invoices" / record["source_file"]
        shutil.copy2(path, PUBLIC / "invoices" / path.name)
        document = load_document(path)
        extraction = record.get("extraction") or {}
        quotes = collect_quotes(extraction)
        url_match = re.search(rf"{re.escape(path.name)}.*?(https?://\S+?)\s*\|", sources)
        invoices.append({
            "file": path.name,
            "source_url": url_match.group(1) if url_match else None,
            "detected_language": record["detected_language"],
            "detected_language_prob": record["detected_language_prob"],
            "model": record["model"],
            "input_tokens": record["input_tokens"],
            "output_tokens": record["output_tokens"],
            "latency_s": record["latency_s"],
            "extraction": extraction,
            "rows": record["rows"],
            "label": labels.get(path.name),
            "locale": {
                "date_order": date_order(extraction.get("country"), extraction.get("document_language")),
                "decimal_comma": uses_decimal_comma(extraction.get("country"), extraction.get("document_language")),
            },
            "pages": [segments(text, quotes.get(i, [])) for i, text in enumerate(document.pages, start=1)],
        })

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "prompt_version": PROMPT_VERSION,
        "evaluation": evaluation,
        "invoices": invoices,
    }
    (PUBLIC / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    shutil.copy2(ROOT / "output" / "invoices.csv", PUBLIC / "invoices.csv")
    print(f"wrote {PUBLIC / 'data.json'} ({len(invoices)} invoices)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
