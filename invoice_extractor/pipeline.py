"""Ingest -> detect language -> LLM extraction -> verify -> one row per (invoice, utility service)."""

from dataclasses import asdict, dataclass, field, replace
from datetime import date
from pathlib import Path

from .ingest import Document, load_document
from .language import detect_language
from .llm import Extractor, LLMResult
from .normalize import (
    canonical_unit, date_order, number_matches, parse_dates, parse_numbers,
    standardize_usage, uses_decimal_comma,
)
from .prompts import build_user_prompt
from .schema import InvoiceExtraction, Service, SourcedDate, SourcedNumber, SourcedText
from .verify import REQUIRED_FIELDS, REVIEW_THRESHOLD, FieldCheck, Grounder, score_field, validate_row

CSV_COLUMNS = [
    # Required by the brief
    "vendor_name", "invoice_date", "service_address", "utility_type", "usage_amount", "usage_unit",
    "billing_period_start", "billing_period_end",
    # Activity data in standard units, ready for an emissions factor
    "usage_standardized", "usage_standardized_unit",
    # Context and trust
    "source_file", "invoice_number", "total_amount", "currency", "language", "country",
    "confidence", "needs_review", "review_reasons", "notes", "model",
]


@dataclass
class InvoiceResult:
    source_file: str
    rows: list[dict]
    checks: list[dict[str, FieldCheck]] = field(default_factory=list)
    detected_language: str | None = None
    detected_language_prob: float = 0.0
    llm: LLMResult | None = None
    error: str | None = None

    def audit_record(self) -> dict:
        """Everything needed to explain each CSV value: quotes, pages, checks, cost."""
        return {
            "source_file": self.source_file,
            "error": self.error,
            "detected_language": self.detected_language,
            "detected_language_prob": self.detected_language_prob,
            "model": self.llm.model if self.llm else None,
            "input_tokens": self.llm.input_tokens if self.llm else None,
            "output_tokens": self.llm.output_tokens if self.llm else None,
            "latency_s": self.llm.latency_s if self.llm else None,
            "extraction": self.llm.extraction.model_dump() if self.llm else None,
            "rows": [
                {"values": row, "checks": {k: asdict(c) for k, c in checks.items()}}
                for row, checks in zip(self.rows, self.checks)
            ],
        }


def process_file(path: Path, extractor: Extractor, today: date | None = None) -> InvoiceResult:
    try:
        document = load_document(path)
        language, probability = detect_language(document.text)
        llm = extractor.extract(build_user_prompt(document, language), label=path.name)
    except Exception as exc:  # one bad file must not sink the batch; it becomes a review row
        row = _empty_row(path.name, f"error:{type(exc).__name__}: {exc}")
        return InvoiceResult(path.name, [row], [{}], error=str(exc))
    result = InvoiceResult(path.name, [], [], language, probability, llm)
    for row, checks in build_rows(document, llm.extraction, language, today):
        row["model"] = llm.model
        result.rows.append(row)
        result.checks.append(checks)
    return result


def build_rows(document: Document, x: InvoiceExtraction, detected_language: str | None,
               today: date | None = None) -> list[tuple[dict, dict[str, FieldCheck]]]:
    if not x.is_utility_invoice:
        return [(_empty_row(document.path.name, "not_a_utility_invoice"), {})]

    country = x.country.upper() if x.country else None
    language = x.document_language or detected_language
    reader = _Reader(Grounder(document.text), date_order(country, language), uses_decimal_comma(country, language))

    invoice_values, invoice_checks = {}, {}
    for name, sourced in (("vendor_name", x.vendor_name), ("invoice_number", x.invoice_number),
                          ("service_address", x.service_address)):
        invoice_values[name], invoice_checks[name] = reader.text(sourced)
    invoice_values["invoice_date"], invoice_checks["invoice_date"] = reader.date(x.invoice_date)
    invoice_values["total_amount"], invoice_checks["total_amount"] = reader.number(x.total_amount)

    if not x.services:
        row = _empty_row(document.path.name, "no_service_found")
        row.update(invoice_values)
        return [(row, invoice_checks)]

    results = []
    for service in x.services:
        # Fresh FieldCheck copies: scoring mutates them, and services must not share issues.
        row = dict(invoice_values)
        checks = {name: replace(check, issues=[]) for name, check in invoice_checks.items()}
        row.update(source_file=document.path.name, currency=x.currency, language=language,
                   country=country, notes=" | ".join(x.notes))
        _add_service(row, checks, service, reader)
        _score(row, checks, today)
        results.append((row, checks))
    return results


class _Reader:
    """Turns a sourced LLM field into (value, FieldCheck) by grounding and re-parsing it."""

    def __init__(self, grounder: Grounder, order: str, decimal_comma: bool):
        self.grounder, self.order, self.decimal_comma = grounder, order, decimal_comma

    def text(self, f: SourcedText) -> tuple[str | None, FieldCheck]:
        value = ", ".join(line.strip() for line in (f.value or "").splitlines() if line.strip()) or None
        if value is None:
            return None, FieldCheck(present=False)
        return value, FieldCheck(present=True, grounding=self.grounder.check(f.source_text))

    def date(self, f: SourcedDate) -> tuple[str | None, FieldCheck]:
        try:
            value = date.fromisoformat(f.value).isoformat() if f.value else None
        except ValueError:
            value = None
        if value is None:
            return None, FieldCheck(present=False)
        candidates = parse_dates(f.source_text, self.order)
        parse = "unparsed" if not candidates else ("agrees" if any(c.matches(value) for c in candidates) else "disagrees")
        return value, FieldCheck(present=True, grounding=self.grounder.check(f.source_text), parse=parse)

    def number(self, f: SourcedNumber) -> tuple[float | None, FieldCheck]:
        if f.value is None:
            return None, FieldCheck(present=False)
        candidates = parse_numbers(f.source_text, self.decimal_comma)
        parse = "unparsed" if not candidates else ("agrees" if number_matches(f.value, candidates) else "disagrees")
        return f.value, FieldCheck(present=True, grounding=self.grounder.check(f.source_text), parse=parse)


def _add_service(row: dict, checks: dict, service: Service, reader: _Reader) -> None:
    row["utility_type"] = service.utility_type
    checks["utility_type"] = FieldCheck(present=True)
    row["usage_amount"], checks["usage_amount"] = reader.number(service.usage)
    unit = canonical_unit(service.usage_unit)
    row["usage_unit_raw"] = service.usage_unit
    row["usage_unit"] = unit or service.usage_unit
    checks["usage_unit"] = FieldCheck(present=bool(service.usage_unit), parse="agrees" if unit else "unparsed")
    row["billing_period_start"], checks["billing_period_start"] = reader.date(service.billing_period_start)
    row["billing_period_end"], checks["billing_period_end"] = reader.date(service.billing_period_end)
    row["meter_reading_start"] = service.meter_reading_start
    row["meter_reading_end"] = service.meter_reading_end
    row["usage_standardized"], row["usage_standardized_unit"] = standardize_usage(
        row["usage_amount"], unit, service.utility_type)


def _score(row: dict, checks: dict[str, FieldCheck], today: date | None) -> None:
    issues = validate_row(row, today)
    for name, check in checks.items():
        score_field(check, issues, name)
    scored = [checks[n].confidence for n in REQUIRED_FIELDS]
    if checks["service_address"].present:  # optional, but a hallucinated address still counts
        scored.append(checks["service_address"].confidence)
    row["confidence"] = round(min(scored), 2)

    reasons = [str(i) for i in issues]
    for name, check in checks.items():
        if check.present and check.grounding == "missing":
            reasons.append(f"{name}:quote_not_in_document")
        if check.parse == "disagrees":
            reasons.append(f"{name}:reparse_disagrees")
    row["needs_review"] = row["confidence"] < REVIEW_THRESHOLD or any(i.level == "error" for i in issues)
    row["review_reasons"] = "; ".join(dict.fromkeys(reasons))


def _empty_row(source_file: str, reason: str) -> dict:
    row = {column: None for column in CSV_COLUMNS}
    row.update(source_file=source_file, confidence=0.0, needs_review=True, review_reasons=reason)
    return row
