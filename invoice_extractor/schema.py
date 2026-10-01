"""Data contract between the pipeline and the LLM.

The model never returns a bare value. Every field comes back as (value, source_text, page) so
the pipeline can check, in plain code, that the value really is printed in the document.
Field descriptions are sent to the model as part of the JSON schema, so they double as
per-field instructions.
"""

from typing import Literal

from pydantic import BaseModel, Field

UtilityType = Literal["electricity", "gas", "water"]

_SOURCE = (
    "The exact characters in the document this value was read from, copied verbatim in the "
    "original language and script (no translation, no reformatting). Keep it short: the value "
    "plus at most its label or unit. null when value is null."
)
_PAGE = "1-based page number where source_text appears. null when value is null."


class SourcedText(BaseModel):
    value: str | None = Field(description="The value, or null if the document does not state it.")
    source_text: str | None = Field(description=_SOURCE)
    page: int | None = Field(description=_PAGE)


class SourcedDate(BaseModel):
    value: str | None = Field(description="Gregorian date as YYYY-MM-DD, or null.")
    source_text: str | None = Field(description=_SOURCE)
    page: int | None = Field(description=_PAGE)


class SourcedNumber(BaseModel):
    value: float | None = Field(
        description="Plain number: '.' as decimal separator, no thousands separators, no unit."
    )
    source_text: str | None = Field(description=_SOURCE)
    page: int | None = Field(description=_PAGE)


class Service(BaseModel):
    utility_type: UtilityType
    usage: SourcedNumber = Field(
        description="Total consumption billed for this utility in this billing period."
    )
    usage_unit: str | None = Field(
        description="Unit exactly as printed next to the usage figure, e.g. kWh, m³, therms, CCF, gallons."
    )
    billing_period_start: SourcedDate
    billing_period_end: SourcedDate
    meter_reading_start: float | None = Field(
        description="Previous/opening meter reading for this service, only if printed and in the same unit as usage."
    )
    meter_reading_end: float | None = Field(
        description="Current/closing meter reading for this service, only if printed and in the same unit as usage."
    )


class InvoiceExtraction(BaseModel):
    is_utility_invoice: bool
    document_language: str = Field(description="ISO 639-1 code of the bill's main language, e.g. en, es, de, ja.")
    country: str | None = Field(
        description="ISO 3166-1 alpha-2 code of the country where the service is delivered."
    )
    vendor_name: SourcedText = Field(description="The utility or supplier that issued the bill.")
    vendor_name_latin: str | None = Field(
        description="Only if vendor_name is in a non-Latin script: its common English/Latin-script name. Else null."
    )
    invoice_number: SourcedText
    invoice_date: SourcedDate = Field(description="The date the bill was issued.")
    service_address: SourcedText = Field(description="The address where the utility is delivered.")
    currency: str | None = Field(description="ISO 4217 code of the amounts on the bill, e.g. USD, EUR, INR.")
    total_amount: SourcedNumber = Field(description="Total amount due on this bill.")
    services: list[Service] = Field(description="One entry per utility type billed on this bill.")
    notes: list[str] = Field(
        description="Short notes on ambiguities, estimated reads, or values that could not be determined."
    )
