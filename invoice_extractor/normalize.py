"""Deterministic, locale-aware parsing of what the LLM copied from the bill.

The LLM is asked for normalized values AND the verbatim text it read them from. This module
re-parses that verbatim text independently, so a date-order swap (03/04 read as March 4 on a
Spanish bill) or a misread decimal comma ("1.234" is 1234 in Germany) is caught by code instead
of being trusted. It also canonicalizes units and converts usage to kWh / m3 where the factor is
fixed (activity data in the shape an emissions calculation needs).
"""

import re
import unicodedata
from dataclasses import dataclass

# ---------------------------------------------------------------- locale conventions

_MDY_COUNTRIES = {"US", "PH", "PR", "GU", "AS", "VI", "FM", "MH", "PW", "BZ"}
_YMD_COUNTRIES = {"JP", "CN", "KR", "TW", "HU", "LT", "MN", "IR"}
_DECIMAL_POINT_COUNTRIES = {
    "US", "GB", "IE", "AU", "NZ", "IN", "JP", "CN", "KR", "TW", "HK", "SG", "MY", "PH", "TH",
    "MX", "CH", "IL", "PK", "BD", "LK", "NG", "KE", "GH",
}
_DECIMAL_COMMA_COUNTRIES = {
    "DE", "FR", "ES", "IT", "PT", "BR", "NL", "BE", "AT", "SE", "NO", "DK", "FI", "PL", "CZ",
    "SK", "HU", "RO", "GR", "TR", "RU", "UA", "AR", "CL", "CO", "UY", "PY", "VE", "EC", "BO",
    "ID", "VN", "ZA",
}
_DECIMAL_COMMA_LANGUAGES = {
    "de", "fr", "es", "it", "pt", "nl", "sv", "da", "no", "nb", "fi", "pl", "cs", "sk", "ru",
    "tr", "id", "vi", "ro", "el", "hu", "uk",
}


def date_order(country: str | None, language: str | None) -> str:
    if country in _MDY_COUNTRIES:
        return "MDY"
    if country in _YMD_COUNTRIES or language in {"ja", "zh", "ko"}:
        return "YMD"
    return "DMY"


def uses_decimal_comma(country: str | None, language: str | None) -> bool:
    if country in _DECIMAL_POINT_COUNTRIES:
        return False
    if country in _DECIMAL_COMMA_COUNTRIES:
        return True
    return language in _DECIMAL_COMMA_LANGUAGES


# ---------------------------------------------------------------- units

_UNIT_ALIASES = {
    "kWh": ["kwh", "kwhr", "kw-h", "kilowatthour", "kilowatthours", "kilowatt-hour", "kilowatt-hours"],
    "MWh": ["mwh"],
    "Wh": ["wh"],
    "therms": ["therm", "therms", "thm", "thms"],
    "CCF": ["ccf", "hcf", "hundredcubicfeet"],
    "MCF": ["mcf"],
    "m3": ["m3", "m^3", "cbm", "mc", "smc", "sm3", "nm3", "cubicmeters", "cubicmetres", "metroscubicos", "metroscúbicos"],
    "kL": ["kl", "kiloliter", "kiloliters", "kilolitre", "kilolitres"],
    "ML": ["ml", "megaliter", "megaliters", "megalitre", "megalitres"],  # on utility bills ML is megalitres
    "L": ["l", "liter", "liters", "litre", "litres", "litros", "litri"],
    "gallons": ["gal", "gals", "gallon", "gallons"],
    "kgal": ["kgal", "kgals", "tgal", "1000gal", "1,000gal", "thousandgallons"],
    "MJ": ["mj"],
    "GJ": ["gj"],
}
_UNIT_LOOKUP = {alias: canonical for canonical, aliases in _UNIT_ALIASES.items() for alias in aliases}

COMPATIBLE_UNITS = {
    "electricity": {"kWh", "MWh", "Wh"},
    "gas": {"kWh", "MWh", "therms", "CCF", "MCF", "m3", "MJ", "GJ"},
    "water": {"m3", "kL", "ML", "L", "gallons", "kgal", "CCF"},
}

# Fixed conversion factors only. Gas volume (m3, CCF) -> kWh needs the calorific value / therm
# factor printed on each bill, so it is deliberately left unconverted rather than guessed.
_ENERGY_TO_KWH = {"kWh": 1.0, "MWh": 1000.0, "Wh": 0.001, "therms": 29.3071, "MJ": 1 / 3.6, "GJ": 277.7778}
_WATER_TO_M3 = {"m3": 1.0, "kL": 1.0, "ML": 1000.0, "L": 0.001, "gallons": 0.003785412, "kgal": 3.785412, "CCF": 2.831685}


def canonical_unit(raw: str | None) -> str | None:
    """'KWH', 'kW h', 'm³', 'Smc', '1,000 Gal' -> canonical spelling, or None if unknown."""
    if not raw:
        return None
    key = re.sub(r"[\s.]", "", unicodedata.normalize("NFKC", raw)).casefold()
    return _UNIT_LOOKUP.get(key)


def standardize_usage(amount: float | None, unit: str | None, utility_type: str) -> tuple[float | None, str | None]:
    """Usage in kWh (electricity, gas) or m3 (water) when the conversion is a fixed factor."""
    if amount is None or unit is None:
        return None, None
    if utility_type in ("electricity", "gas") and unit in _ENERGY_TO_KWH:
        return round(amount * _ENERGY_TO_KWH[unit], 3), "kWh"
    if utility_type == "water" and unit in _WATER_TO_M3:
        return round(amount * _WATER_TO_M3[unit], 3), "m3"
    return None, None


# ---------------------------------------------------------------- numbers

# Not preceded by a Latin letter: after NFKC, "m³" becomes "m3" and "CO₂" becomes "CO2", and
# those digits are part of a unit, not a value. CJK text ("使用量123kWh") still parses.
_NUMBER_TOKEN = re.compile(r"(?<![A-Za-z])[-−]?\d+(?:[.,'’   ]\d+)*")


def parse_numbers(text: str | None, decimal_comma: bool) -> list[float]:
    """Every number in `text`, read with the bill's decimal convention."""
    if not text:
        return []
    values = []
    for token in _NUMBER_TOKEN.findall(unicodedata.normalize("NFKC", text)):
        for piece in _split_space_groups(token):
            value = _interpret_number(piece, decimal_comma)
            if value is not None:
                values.append(value)
    return values


def number_matches(value: float, candidates: list[float]) -> bool:
    def close(a: float, b: float) -> bool:
        return abs(a - b) <= max(0.011, 1e-4 * abs(b))  # rounding only, not "roughly"

    # A total the model summed from tiers or meters is accepted if the printed parts add up.
    return any(close(value, c) for c in candidates) or (len(candidates) > 1 and close(value, sum(candidates)))


def _split_space_groups(token: str) -> list[str]:
    # "1 234,5" is one French number; "30 1234" is two numbers. A space is only a thousands
    # separator when every group after it has exactly three digits.
    parts = re.split(r"[   ]", token)
    if len(parts) == 1 or all(re.fullmatch(r"\d{3}(?:[.,]\d+)?", p) for p in parts[1:]):
        return [token]
    return parts


def _interpret_number(token: str, decimal_comma: bool) -> float | None:
    t = token.replace("−", "-")
    negative = t.startswith("-")
    t = re.sub(r"[-'’   ]", "", t)
    if "." in t and "," in t:  # both present: the last one is the decimal separator
        decimal = "." if t.rfind(".") > t.rfind(",") else ","
        t = t.replace("," if decimal == "." else ".", "").replace(decimal, ".")
    elif "." in t or "," in t:
        sep = "." if "." in t else ","
        head, *rest = t.split(sep)
        if len(rest) > 1:  # repeated separator can only be thousands grouping
            if not all(len(group) == 3 for group in rest):
                return None
            t = head + "".join(rest)
        elif len(rest[0]) == 3 and head not in ("", "0"):  # "1.234" / "1,234": locale decides
            is_decimal = (sep == ",") == decimal_comma
            t = f"{head}.{rest[0]}" if is_decimal else head + rest[0]
        else:
            t = f"{head}.{rest[0]}"
    try:
        value = float(t)
    except ValueError:
        return None
    return -value if negative else value


# ---------------------------------------------------------------- dates


@dataclass(frozen=True)
class PartialDate:
    year: int | None  # None when the bill prints e.g. "Jan 5 - Feb 4, 2024" with one year
    month: int
    day: int

    def matches(self, iso: str) -> bool:
        y, m, d = (int(x) for x in iso.split("-"))
        return (self.year is None or self.year == y) and self.month == m and self.day == d


_MONTHS = {
    1: "january jan enero ene janvier janv janeiro gennaio gen januar jän jänner januari",
    2: "february feb febrero febr février févr fév fevereiro fev febbraio februar februari",
    3: "march mar marzo mars março märz maerz maart mrt",
    4: "april apr abril abr avril avr aprile",
    5: "may mayo mai maio mag maggio mei maj",
    6: "june jun junio juin junho giugno giu juni",
    7: "july jul julio juillet juil julho luglio lug juli",
    8: "august aug agosto ago août aoû augusti",
    9: "september sep sept septiembre setiembre septembre setembro set settembre",
    10: "october oct octubre octobre outubro out ottobre ott oktober okt",
    11: "november nov noviembre novembre novembro",
    12: "december dec diciembre dic décembre déc dezembro dez dicembre dezember",
}


def _fold(word: str) -> str:
    decomposed = unicodedata.normalize("NFKD", word.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).rstrip(".")


_MONTH_LOOKUP = {_fold(w): n for n, words in _MONTHS.items() for w in words.split()}
_ERAS = {"令和": 2018, "平成": 1988}  # Japanese imperial eras: Reiwa 6 = 2024

_DATE_PATTERNS = [
    ("era", re.compile(r"(令和|平成)\s*(\d{1,2}|元)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")),
    ("cjk", re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")),
    ("cjk_no_year", re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日")),
    ("iso", re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b")),
    ("numeric", re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4}|\d{2})\b")),
    ("day_first", re.compile(
        r"\b(\d{1,2})(?:\.|º|°|er|st|nd|rd|th)?\s+(?:de\s+)?([^\W\d_]{3,12})\.?,?(?:\s+(?:de\s+|del\s+)?(\d{4}))?\b")),
    ("month_first", re.compile(r"\b([^\W\d_]{3,12})\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b,?(?:\s+(\d{4}))?")),
]


def parse_dates(text: str | None, order: str) -> list[PartialDate]:
    """Every date in `text`. Numeric dates are read in the bill's order (DMY/MDY/YMD)."""
    if not text:
        return []
    remaining = unicodedata.normalize("NFKC", text)
    found: list[PartialDate] = []
    for kind, pattern in _DATE_PATTERNS:
        for match in pattern.finditer(remaining):
            date = _to_date(kind, match.groups(), order)
            if date:
                found.append(date)
                remaining = remaining.replace(match.group(0), " " * len(match.group(0)), 1)
    return found


def _to_date(kind: str, g: tuple, order: str) -> PartialDate | None:
    if kind == "era":
        year = _ERAS[g[0]] + (1 if g[1] == "元" else int(g[1]))
        return _valid(year, int(g[2]), int(g[3]))
    if kind in ("cjk", "iso"):
        return _valid(int(g[0]), int(g[1]), int(g[2]))
    if kind == "cjk_no_year":
        return _valid(None, int(g[0]), int(g[1]))
    if kind == "numeric":
        a, b, year = int(g[0]), int(g[1]), int(g[2])
        year = year + 2000 if year < 100 else year
        if a > 12:
            day, month = a, b
        elif b > 12:
            month, day = a, b
        else:
            month, day = (a, b) if order == "MDY" else (b, a)
        return _valid(year, month, day)
    if kind == "day_first":
        month = _MONTH_LOOKUP.get(_fold(g[1]))
        return _valid(int(g[2]) if g[2] else None, month, int(g[0])) if month else None
    if kind == "month_first":
        month = _MONTH_LOOKUP.get(_fold(g[0]))
        return _valid(int(g[2]) if g[2] else None, month, int(g[1])) if month else None
    return None


def _valid(year: int | None, month: int, day: int) -> PartialDate | None:
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    if year is not None and not (1990 <= year <= 2100):
        return None
    return PartialDate(year, month, day)


# ---------------------------------------------------------------- text


def compact(text: str) -> str:
    """Whitespace-free, case-folded, NFKC form used to compare quotes against the document."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()
