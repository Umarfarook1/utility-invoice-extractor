import pytest

from invoice_extractor.normalize import (
    PartialDate, canonical_unit, date_order, number_matches, parse_dates, parse_numbers,
    standardize_usage, uses_decimal_comma,
)


@pytest.mark.parametrize("text, decimal_comma, expected", [
    ("1.234,56 kWh", True, [1234.56]),        # German
    ("1,234.56 kWh", False, [1234.56]),       # US
    ("1 234,5 kWh", True, [1234.5]),          # French, space as thousands separator
    ("1'234.5", False, [1234.5]),             # Swiss
    ("1.234 kWh", True, [1234.0]),            # ambiguous: thousands in Germany...
    ("1.234 kWh", False, [1.234]),            # ...a decimal in the US
    ("0,123 m³", False, [0.123]),             # leading zero is always a decimal
    ("１２３ kWh", False, [123.0]),            # full-width digits (Japanese bills)
    ("30 Tage 4.512 kWh", True, [30.0, 4512.0]),
    ("2024 1234", False, [2024.0, 1234.0]),   # space between unrelated numbers is not grouping
])
def test_parse_numbers_by_locale(text, decimal_comma, expected):
    assert parse_numbers(text, decimal_comma) == pytest.approx(expected)


def test_number_matches_summed_tiers():
    # Model sums two printed tiers into the total; still counts as verified.
    assert number_matches(451.0, [300.0, 151.0])
    assert not number_matches(452.5, [300.0, 151.0])


@pytest.mark.parametrize("text, order, expected", [
    ("03/04/2024", "DMY", PartialDate(2024, 4, 3)),
    ("03/04/2024", "MDY", PartialDate(2024, 3, 4)),
    ("13/04/2024", "MDY", PartialDate(2024, 4, 13)),   # day > 12 overrides the locale
    ("15.01.2024", "DMY", PartialDate(2024, 1, 15)),
    ("2024-02-29", "MDY", PartialDate(2024, 2, 29)),
    ("5 de enero de 2024", "DMY", PartialDate(2024, 1, 5)),
    ("1er février 2024", "DMY", PartialDate(2024, 2, 1)),
    ("5. März 2024", "DMY", PartialDate(2024, 3, 5)),
    ("January 5, 2024", "MDY", PartialDate(2024, 1, 5)),
    ("2024年3月15日", "YMD", PartialDate(2024, 3, 15)),
    ("令和6年3月15日", "YMD", PartialDate(2024, 3, 15)),  # Japanese era: Reiwa 6 = 2024
    ("10 set 2024", "DMY", PartialDate(2024, 9, 10)),     # Portuguese/Italian abbreviation
])
def test_parse_single_dates(text, order, expected):
    assert parse_dates(text, order) == [expected]


def test_parse_date_range_with_single_year():
    dates = parse_dates("Jan 5 - Feb 4, 2024", "MDY")
    assert dates == [PartialDate(None, 1, 5), PartialDate(2024, 2, 4)]
    assert dates[0].matches("2024-01-05")


def test_parse_dates_ignores_amounts():
    assert parse_dates("Total 12.50 EUR, 1.234,56 kWh", "DMY") == []


@pytest.mark.parametrize("raw, canonical", [
    ("kWh", "kWh"), ("KWH", "kWh"), ("kW h", "kWh"), ("m³", "m3"), ("Smc", "m3"), ("mc", "m3"),
    ("Therms", "therms"), ("CCF", "CCF"), ("HCF", "CCF"), ("gal.", "gallons"), ("kgal", "kgal"),
    ("KL", "kL"), ("ML", "ML"), ("Megalitres", "ML"), ("ｋＷｈ", "kWh"), ("parsecs", None), (None, None),
])
def test_canonical_unit(raw, canonical):
    assert canonical_unit(raw) == canonical


def test_standardize_usage_only_with_fixed_factors():
    assert standardize_usage(100, "therms", "gas") == (2930.71, "kWh")
    assert standardize_usage(2, "MWh", "electricity") == (2000.0, "kWh")
    assert standardize_usage(1000, "gallons", "water") == (3.785, "m3")
    assert standardize_usage(150, "ML", "water") == (150000.0, "m3")
    # Gas volume needs the bill's calorific value: never guessed.
    assert standardize_usage(100, "m3", "gas") == (None, None)


def test_locale_rules():
    assert date_order("US", "en") == "MDY"
    assert date_order("GB", "en") == "DMY"
    assert date_order("JP", "ja") == "YMD"
    assert uses_decimal_comma("DE", "de") and not uses_decimal_comma("MX", "es")
    assert uses_decimal_comma(None, "fr") and not uses_decimal_comma(None, "en")
