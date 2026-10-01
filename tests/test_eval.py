from eval.evaluate import field_correct


def test_abstaining_is_correct_only_when_nothing_was_printed():
    assert field_correct("service_address", None, None)
    assert not field_correct("service_address", "1 Main St", None)  # invented address is wrong
    assert not field_correct("invoice_date", None, "2024-01-01")


def test_vendor_matches_any_accepted_alias():
    assert field_correct("vendor_name", "Iberdrola Clientes, S.A.U.", ["Iberdrola"])
    assert field_correct("vendor_name", "Électricité de France", ["Electricite de France", "EDF"])
    assert not field_correct("vendor_name", "Energy", ["EDF Energy"])


def test_address_tolerates_formatting():
    assert field_correct("service_address", "8 Rue des Lilas, 75011 PARIS", "8 rue des Lilas 75011 Paris")
    assert not field_correct("service_address", "PO Box 997300, Sacramento", "8 rue des Lilas 75011 Paris")


def test_address_numbers_must_match_exactly():
    # Billing address vs supply address on the same specimen: 6 of 7 words overlap.
    supply = "456 Sample Street, Sampleton, Sampleshire, AB12 3AB"
    assert not field_correct("service_address", "6 Sample Street, Sampleton, Sampleshire, AB12 3AB", supply)


def test_label_can_accept_conflicting_printed_values():
    # A specimen that prints two issue dates for one bill: either is a correct reading.
    assert field_correct("invoice_date", "2023-06-01", ["2023-06-02", "2023-06-01"])
    assert not field_correct("invoice_date", "2023-05-17", ["2023-06-02", "2023-06-01"])


def test_units_and_amounts():
    assert field_correct("usage_unit", "m³", "m3")
    assert field_correct("usage_amount", 1234.0, 1234)
    assert not field_correct("usage_amount", 1243.0, 1234)
