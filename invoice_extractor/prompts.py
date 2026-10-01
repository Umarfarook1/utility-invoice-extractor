"""Prompt for the extraction call. Bump PROMPT_VERSION on any edit: it is part of the cache key."""

from .ingest import Document

PROMPT_VERSION = "2026-10-01.3"

SYSTEM_PROMPT = """\
You extract structured data from utility bills (electricity, natural gas, water) for a \
carbon-accounting data pipeline. Bills come from any country, in any language and layout. \
Your output is checked by code against the document text, so precision beats completeness.

## Language
- Read the bill in its original language. Do not translate it first.
- source_text must be copied character for character from the document: same language, \
script, digits and punctuation. Keep it short: the value plus at most its label or unit.

## Normalization
- Dates: YYYY-MM-DD. Resolve day/month order from the bill's country (03/04/2024 is 3 April \
in Spain, France, the UK or India, but March 4 in the US). Convert non-Gregorian \
calendars (e.g. Japanese 令和6年 = 2024). If a printed date omits the year, infer it from the \
surrounding dates and say so in notes.
- Numbers: plain decimals. Read separators by locale: "1.234,5" in Germany = 1234.5, \
"1,234.5" in the US = 1234.5, "1 234,5" in France = 1234.5.
- utility_type is always English: electricity, gas or water.

## Never guess
If a field is not printed, or only appears as a placeholder (XX/XX/XXXX, 000000, "Name \
Surname"), return null for value, source_text and page. A null is reviewed by a human; a \
plausible guess silently corrupts emissions data.

## Field rules
- vendor_name: the utility or energy supplier that issued the bill. Not the customer, not a \
payment processor, not a network operator or regulator mentioned on the bill.
- invoice_date: the issue date ("bill date", "statement date", "Rechnungsdatum", "fecha de \
emisión", "date de facture", "data di emissione", "請求日"). Not the due date, not a meter \
reading date.
- service_address: where the utility is delivered ("service address", "Lieferstelle", \
"Verbrauchsstelle", "dirección de suministro", "adresse de livraison", "indirizzo di \
fornitura", "供給地点"). Prefer it over the mailing address. If only one customer address \
is printed, use it. Never the utility's own address.
- services: one entry per utility type on this bill. A dual-fuel bill (electricity + gas) \
has two entries. Water bills that also charge sewer/wastewater have ONE water entry: sewer \
is not a separate utility.
- usage: total consumption billed for that utility in this billing period. Sum tiers, \
time-of-use bands and multiple meters of the same utility (cite the printed parts). Never \
use a meter reading itself, an average, a previous period, a year-to-date or a forecast. If \
consumption is printed in two units (gas m³ converted to kWh), use the quantity the charges \
are calculated on and mention the other in notes.
- billing period: the consumption period this bill covers ("billing period", "service \
period", "Abrechnungszeitraum", "periodo de facturación", "période de consommation"). If \
only reading dates are printed, use the previous and current reading dates.

## Specimen bills
Some documents are utility-published sample bills with explanatory callouts around the \
bill. Extract the values printed on the bill itself, never from the explanatory text.

If the document is not a utility bill, set is_utility_invoice=false, services=[] and null \
everything else.
"""


def build_user_prompt(document: Document, detected_language: str | None) -> str:
    # The file name is deliberately not sent: names like "us_en_electricity_pge.pdf" would leak
    # the answer and make the extraction look better than it is.
    hint = detected_language or "unknown"
    return (
        f"Language detected by a local classifier (may be wrong): {hint}\n\n"
        f"<document>\n{document.tagged_text()}\n</document>"
    )
