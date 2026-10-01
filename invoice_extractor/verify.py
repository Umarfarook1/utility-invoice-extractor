"""Checks that do not trust the LLM: grounding, cross-parsing, business rules, confidence.

Confidence is computed, not self-reported. LLM self-confidence is poorly calibrated, so each
field starts at 1.0 and loses weight for every check it fails:
  - its quote is not in the document (likely hallucinated)       x0.4
  - the quote is only loosely present (words found, not the span) x0.9
  - re-parsing the quote disagrees with the normalized value      x0.5
  - the quote has no parseable value to cross-check               x0.85
  - a validation rule fails on this field                         x0.5 (error) / x0.8 (warning)
A row is as trustworthy as its weakest required field.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from .normalize import COMPATIBLE_UNITS, compact

REVIEW_THRESHOLD = 0.75
REQUIRED_FIELDS = (
    "vendor_name", "invoice_date", "utility_type", "usage_amount", "usage_unit",
    "billing_period_start", "billing_period_end",
)


@dataclass
class FieldCheck:
    present: bool
    grounding: str = "n/a"   # exact | words | missing | n/a
    parse: str = "n/a"       # agrees | disagrees | unparsed | n/a
    issues: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass(frozen=True)
class Issue:
    level: str  # error | warning
    field: str
    code: str

    def __str__(self) -> str:
        return f"{self.level}:{self.field}:{self.code}"


class Grounder:
    """Finds the model's quotes in the document text it was given."""

    def __init__(self, document_text: str):
        self._compact = compact(document_text)

    def check(self, source_text: str | None) -> str:
        if not source_text:
            return "missing"
        if compact(source_text) in self._compact:
            return "exact"
        # Layout extraction can put a label and its value on different lines or columns. If
        # every word of the quote is in the document it is still grounded, just less tightly.
        words = [compact(w) for w in source_text.split() if compact(w)]
        if words and all(w in self._compact for w in words):
            return "words"
        return "missing"


def validate_row(row: dict, today: date | None = None) -> list[Issue]:
    today = today or date.today()
    issues: list[Issue] = []

    def add(level: str, name: str, code: str) -> None:
        issues.append(Issue(level, name, code))

    for name in REQUIRED_FIELDS:
        if row.get(name) in (None, ""):
            add("error", name, "missing")

    start, end, issued = (_to_date(row.get(k)) for k in ("billing_period_start", "billing_period_end", "invoice_date"))
    for name, value in (("billing_period_start", start), ("billing_period_end", end), ("invoice_date", issued)):
        if value and not (date(2000, 1, 1) <= value <= today + timedelta(days=60)):
            add("error", name, "implausible_date")
    if start and end:
        if start > end:
            add("error", "billing_period_end", "period_end_before_start")
        elif (end - start).days > 400:
            add("warning", "billing_period_end", "period_longer_than_400_days")
    if issued and start and issued < start - timedelta(days=31):
        add("warning", "invoice_date", "issued_before_period")
    if issued and end and issued > end + timedelta(days=120):
        add("warning", "invoice_date", "issued_long_after_period")

    usage, unit, utility = row.get("usage_amount"), row.get("usage_unit"), row.get("utility_type")
    if usage is not None and usage < 0:
        add("error", "usage_amount", "negative_usage")
    elif usage == 0:
        add("warning", "usage_amount", "zero_usage")
    if unit and utility in COMPATIBLE_UNITS and unit not in COMPATIBLE_UNITS[utility]:
        add("error", "usage_unit", f"unit_{unit}_not_valid_for_{utility}")
    if row.get("usage_unit_raw") and not unit:
        add("warning", "usage_unit", "unrecognized_unit")

    read_start, read_end = row.get("meter_reading_start"), row.get("meter_reading_end")
    if usage and read_start is not None and read_end is not None and read_end >= read_start:
        if abs((read_end - read_start) - usage) > max(1.0, 0.02 * usage):
            add("warning", "usage_amount", "meter_reads_do_not_match_usage")  # a multiplier may apply
    return issues


def score_field(check: FieldCheck, issues: list[Issue], name: str) -> FieldCheck:
    if not check.present:
        check.confidence = 0.0
        return check
    score = 1.0
    score *= {"exact": 1.0, "words": 0.9, "missing": 0.4}.get(check.grounding, 1.0)
    score *= {"agrees": 1.0, "disagrees": 0.5, "unparsed": 0.85}.get(check.parse, 1.0)
    for issue in issues:
        if issue.field == name:
            check.issues.append(str(issue))
            score *= 0.5 if issue.level == "error" else 0.8
    check.confidence = round(score, 2)
    return check


def _to_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None
