"""End-to-end pipeline behaviour with a scripted LLM (no network)."""

from datetime import date
from pathlib import Path

from invoice_extractor.cli import write_csv
from invoice_extractor.llm import LLMResult
from invoice_extractor.pipeline import CSV_COLUMNS, process_file
from invoice_extractor.schema import InvoiceExtraction

TODAY = date(2026, 10, 1)

BILL = """\
EDF Energy                        Facture du 12/03/2024
Point de livraison : 8 rue des Lilas, 75011 Paris
Électricité  période du 05/01/2024 au 04/03/2024   Consommation 1 234 kWh
Gaz naturel  période du 05/01/2024 au 04/03/2024   Consommation 2 540,5 kWh
Montant TTC à payer : 412,37 €
"""


def sourced(value, source_text, page=1):
    return {"value": value, "source_text": source_text, "page": page if value is not None else None}


def null():
    return {"value": None, "source_text": None, "page": None}


def service(utility, usage, usage_src, start="2024-01-05", end="2024-03-04"):
    return {
        "utility_type": utility, "usage": sourced(usage, usage_src), "usage_unit": "kWh",
        "billing_period_start": sourced(start, "05/01/2024"), "billing_period_end": sourced(end, "04/03/2024"),
        "meter_reading_start": None, "meter_reading_end": None,
    }


def extraction(**overrides):
    data = {
        "is_utility_invoice": True, "document_language": "fr", "country": "FR",
        "vendor_name": sourced("EDF Energy", "EDF Energy"), "vendor_name_latin": None,
        "invoice_number": null(),
        "invoice_date": sourced("2024-03-12", "Facture du 12/03/2024"),
        "service_address": sourced("8 rue des Lilas, 75011 Paris", "8 rue des Lilas, 75011 Paris"),
        "currency": "EUR", "total_amount": sourced(412.37, "412,37 €"),
        "services": [service("electricity", 1234.0, "1 234 kWh"), service("gas", 2540.5, "2 540,5 kWh")],
        "notes": [],
    }
    data.update(overrides)
    return InvoiceExtraction.model_validate(data)


class ScriptedExtractor:
    model = "scripted"

    def __init__(self, result: InvoiceExtraction):
        self.result = result

    def extract(self, user_prompt: str, label: str = "") -> LLMResult:
        assert label not in user_prompt  # the file name must never reach the model
        return LLMResult(self.result, self.model, 100, 50, 0.1)


def run(tmp_path: Path, result: InvoiceExtraction):
    path = tmp_path / "fr_dual_fuel_bill.txt"
    path.write_text(BILL, encoding="utf-8")
    return process_file(path, ScriptedExtractor(result), TODAY)


def test_dual_fuel_bill_gives_one_row_per_utility(tmp_path):
    result = run(tmp_path, extraction())
    elec, gas = result.rows
    assert (elec["utility_type"], elec["usage_amount"]) == ("electricity", 1234.0)
    assert (gas["utility_type"], gas["usage_amount"]) == ("gas", 2540.5)
    assert elec["vendor_name"] == gas["vendor_name"] == "EDF Energy"
    assert elec["usage_standardized"] == 1234.0 and elec["usage_standardized_unit"] == "kWh"
    assert elec["confidence"] == 1.0 and not elec["needs_review"], elec["review_reasons"]


def test_services_do_not_share_invoice_level_checks(tmp_path):
    result = run(tmp_path, extraction(invoice_date=sourced("2031-03-12", "Facture du 12/03/2024")))
    expected = ["error:invoice_date:implausible_date", "warning:invoice_date:issued_long_after_period"]
    for checks in result.checks:  # each row lists each issue once, not once per service
        assert checks["invoice_date"].issues == expected


def test_hallucinated_usage_is_flagged(tmp_path):
    bad = extraction(services=[service("electricity", 1324.0, "1 324 kWh")])  # not on the bill
    row = run(tmp_path, bad).rows[0]
    assert row["needs_review"]
    assert "usage_amount:quote_not_in_document" in row["review_reasons"]


def test_day_month_swap_is_caught(tmp_path):
    # The model read 05/01/2024 as May 1 (US order) on a French bill.
    bad = extraction(services=[service("electricity", 1234.0, "1 234 kWh", start="2024-05-01")])
    row = run(tmp_path, bad).rows[0]
    assert row["needs_review"]
    assert "billing_period_start:reparse_disagrees" in row["review_reasons"]


def test_missing_optional_address_stays_empty(tmp_path):
    row = run(tmp_path, extraction(service_address=null())).rows[0]
    assert row["service_address"] is None
    assert not row["needs_review"]


def test_not_a_utility_bill(tmp_path):
    result = run(tmp_path, extraction(is_utility_invoice=False, services=[]))
    assert len(result.rows) == 1 and result.rows[0]["review_reasons"] == "not_a_utility_invoice"


def test_csv_has_required_columns_first(tmp_path):
    result = run(tmp_path, extraction())
    out = tmp_path / "out.csv"
    write_csv([result], out)
    header = out.read_text(encoding="utf-8-sig").splitlines()[0].split(",")
    assert header == CSV_COLUMNS
    assert header[:8] == ["vendor_name", "invoice_date", "service_address", "utility_type",
                          "usage_amount", "usage_unit", "billing_period_start", "billing_period_end"]
