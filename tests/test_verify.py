from datetime import date

from invoice_extractor.verify import FieldCheck, Grounder, Issue, score_field, validate_row

TODAY = date(2026, 10, 1)


def good_row(**overrides):
    row = {
        "vendor_name": "Stadtwerke Beispiel", "invoice_date": "2024-02-10", "utility_type": "gas",
        "usage_amount": 4512.0, "usage_unit": "kWh", "usage_unit_raw": "kWh",
        "billing_period_start": "2023-01-01", "billing_period_end": "2023-12-31",
        "meter_reading_start": None, "meter_reading_end": None,
    }
    row.update(overrides)
    return row


def codes(issues):
    return {i.code for i in issues}


def test_clean_row_has_no_issues():
    assert validate_row(good_row(), TODAY) == []


def test_missing_required_field():
    assert "missing" in codes(validate_row(good_row(invoice_date=None), TODAY))


def test_period_inverted():
    row = good_row(billing_period_start="2024-01-31", billing_period_end="2024-01-01")
    assert "period_end_before_start" in codes(validate_row(row, TODAY))


def test_unit_must_fit_utility():
    issues = validate_row(good_row(utility_type="water", usage_unit="kWh"), TODAY)
    assert "unit_kWh_not_valid_for_water" in codes(issues)


def test_meter_reads_cross_check():
    ok = good_row(usage_amount=120.0, usage_unit="m3", utility_type="water",
                  meter_reading_start=1000.0, meter_reading_end=1120.0)
    off = dict(ok, meter_reading_end=1500.0)
    assert validate_row(ok, TODAY) == []
    assert "meter_reads_do_not_match_usage" in codes(validate_row(off, TODAY))


def test_future_dates_are_implausible():
    assert "implausible_date" in codes(validate_row(good_row(invoice_date="2031-01-01"), TODAY))


def test_grounding_tolerates_layout_whitespace_but_not_invention():
    doc = "Rechnungsdatum:      10.02.2024\nVerbrauch    4.512   kWh\nLieferstelle\nMusterweg 1"
    g = Grounder(doc)
    assert g.check("Rechnungsdatum: 10.02.2024") == "exact"   # whitespace differs, span is there
    assert g.check("Lieferstelle Musterweg 1") == "exact"
    assert g.check("Musterweg 1 Lieferstelle") == "words"     # words present, not as one span
    assert g.check("4.612 kWh") == "missing"                  # a hallucinated number
    assert g.check(None) == "missing"


def test_confidence_drops_for_each_failed_check():
    perfect = score_field(FieldCheck(present=True, grounding="exact", parse="agrees"), [], "invoice_date")
    hallucinated = score_field(FieldCheck(present=True, grounding="missing", parse="agrees"), [], "invoice_date")
    swapped = score_field(FieldCheck(present=True, grounding="exact", parse="disagrees"), [], "invoice_date")
    invalid = score_field(FieldCheck(present=True, grounding="exact", parse="agrees"),
                          [Issue("error", "invoice_date", "implausible_date")], "invoice_date")
    assert perfect.confidence == 1.0
    assert hallucinated.confidence == 0.4
    assert swapped.confidence == 0.5
    assert invalid.confidence == 0.5 and invalid.issues == ["error:invoice_date:implausible_date"]
    assert score_field(FieldCheck(present=False), [], "invoice_date").confidence == 0.0
