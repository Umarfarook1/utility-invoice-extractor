"""Score the pipeline's output against hand-labelled ground truth.

    python -m eval.evaluate            # reads output/extractions.jsonl + ground_truth/labels.json

Reports field-level accuracy, and whether the review flag catches the errors that remain: a
confidence score is only useful if wrong values land in the "needs review" pile.
"""

import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

from invoice_extractor.normalize import canonical_unit

ROOT = Path(__file__).resolve().parent.parent
FIELDS = [
    "vendor_name", "invoice_date", "service_address", "utility_type", "usage_amount", "usage_unit",
    "billing_period_start", "billing_period_end",
]
SERVICE_FIELDS = FIELDS[3:]


def _norm(text) -> str:
    text = unicodedata.normalize("NFKD", str(text).casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.findall(r"\w+", text))


def field_correct(name: str, predicted, expected) -> bool:
    if expected is None:  # nothing printed: the only right answer is an empty field
        return predicted in (None, "")
    if predicted in (None, ""):
        return False
    if name == "usage_amount":
        return abs(float(predicted) - float(expected)) <= max(0.011, 1e-3 * abs(float(expected)))
    if name == "usage_unit":
        return (canonical_unit(str(predicted)) or predicted) == (canonical_unit(str(expected)) or expected)
    if name == "vendor_name":  # label lists acceptable names; prediction must contain one of them
        return any(_norm(alias) in _norm(predicted) for alias in expected)
    if name == "service_address":
        # Formatting varies, so 80% of the label's words must be present, but every number must
        # match exactly: "6 Sample Street" is a different address from "456 Sample Street".
        label_tokens = _norm(expected).split()
        found = set(_norm(predicted).split())
        numbers_match = all(t in found for t in label_tokens if any(c.isdigit() for c in t))
        return numbers_match and sum(t in found for t in label_tokens) / len(label_tokens) >= 0.8
    if isinstance(expected, list):  # the bill itself prints conflicting values; any of them is right
        return str(predicted) in {str(e) for e in expected}
    return str(predicted) == str(expected)


def evaluate(extractions_path: Path, labels_path: Path) -> dict:
    labels = json.loads(labels_path.read_text(encoding="utf-8"))["invoices"]
    records = {}
    for line in extractions_path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        records[record["source_file"]] = record

    per_field = defaultdict(lambda: [0, 0])
    invoices, misses, extra_rows = [], [], []
    flagged_wrong = unflagged_wrong = flagged_rows = flagged_rows_with_error = 0

    for source_file, label in labels.items():
        rows = [r["values"] for r in records.get(source_file, {}).get("rows", [])]
        by_type = {r.get("utility_type"): r for r in rows}
        correct = total = 0
        for service in label["services"]:
            row = by_type.get(service["utility_type"], {})
            expected = {**{k: label[k] for k in FIELDS[:3]}, **service}
            row_has_error = False
            for name in FIELDS:
                ok = field_correct(name, row.get(name), expected[name])
                per_field[name][0] += ok
                per_field[name][1] += 1
                correct, total = correct + ok, total + 1
                if not ok:
                    row_has_error = True
                    misses.append({"file": source_file, "utility": service["utility_type"], "field": name,
                                   "expected": expected[name], "got": row.get(name),
                                   "flagged": bool(row.get("needs_review", True))})
                    if row.get("needs_review", True):
                        flagged_wrong += 1
                    else:
                        unflagged_wrong += 1
            if row.get("needs_review", True):
                flagged_rows += 1
                flagged_rows_with_error += row_has_error
        expected_types = {s["utility_type"] for s in label["services"]}
        extra_rows += [f"{source_file}:{t}" for t in by_type if t and t not in expected_types]
        invoices.append({"file": source_file, "language": label.get("language"),
                         "correct": correct, "total": total})

    total_correct = sum(c for c, _ in per_field.values())
    total_fields = sum(t for _, t in per_field.values())
    wrong = flagged_wrong + unflagged_wrong
    return {
        "field_accuracy": round(total_correct / total_fields, 4) if total_fields else None,
        "fields_correct": total_correct,
        "fields_total": total_fields,
        "per_field": {k: {"correct": c, "total": t, "accuracy": round(c / t, 4)} for k, (c, t) in per_field.items()},
        "invoices": invoices,
        "misses": misses,
        "extra_rows": extra_rows,
        "errors_caught_by_review_flag": f"{flagged_wrong}/{wrong}" if wrong else "no errors",
        "flagged_rows_that_had_an_error": f"{flagged_rows_with_error}/{flagged_rows}",
    }


def to_markdown(report: dict) -> str:
    lines = [
        "# Evaluation report", "",
        f"**Field accuracy: {report['fields_correct']}/{report['fields_total']} "
        f"({report['field_accuracy']:.1%})** across {len(report['invoices'])} invoices.", "",
        f"- Wrong values that the `needs_review` flag caught: {report['errors_caught_by_review_flag']}",
        f"- Rows flagged for review that really had an error: {report['flagged_rows_that_had_an_error']}",
        f"- Extra service rows not in the labels: {', '.join(report['extra_rows']) or 'none'}", "",
        "## Per field", "", "| field | correct | accuracy |", "|---|---|---|",
    ]
    lines += [f"| {k} | {v['correct']}/{v['total']} | {v['accuracy']:.0%} |" for k, v in report["per_field"].items()]
    lines += ["", "## Per invoice", "", "| invoice | language | fields correct |", "|---|---|---|"]
    lines += [f"| {i['file']} | {i['language']} | {i['correct']}/{i['total']} |" for i in report["invoices"]]
    lines += ["", "## Misses", ""]
    if not report["misses"]:
        lines.append("None.")
    else:
        lines += ["| invoice | utility | field | expected | got | flagged for review |", "|---|---|---|---|---|---|"]
        lines += [f"| {m['file']} | {m['utility']} | {m['field']} | {m['expected']} | {m['got']} | "
                  f"{'yes' if m['flagged'] else 'NO'} |" for m in report["misses"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    out = ROOT / "output"
    report = evaluate(out / "extractions.jsonl", ROOT / "ground_truth" / "labels.json")
    (out / "eval_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "eval_report.md").write_text(to_markdown(report), encoding="utf-8")
    print(to_markdown(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
