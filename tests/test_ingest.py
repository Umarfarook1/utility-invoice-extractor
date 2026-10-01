from invoice_extractor.ingest import _clean, _pdf_page_text


class FakePage:
    def __init__(self, plain, layout):
        self.plain, self.layout = plain, layout

    def extract_text(self, extraction_mode="plain"):
        return self.layout if extraction_mode == "layout" else self.plain


def test_layout_mode_used_when_complete():
    page = FakePage(plain="Usage 120 kWh Total 30.00", layout="Usage     120 kWh\nTotal     30.00")
    assert _pdf_page_text(page) == page.layout


def test_plain_mode_used_when_layout_drops_text():
    # Layout mode silently drops rotated text; it kept under 25% of two real sample bills.
    page = FakePage(plain="Billing period Jan 5 - Feb 4 Usage 451 kWh Amount due 98.20", layout="Usage 451 kWh")
    assert _pdf_page_text(page) == page.plain


def test_clean_compacts_layout_padding():
    assert _clean("Total" + " " * 40 + "30.00  \n\n\n\nNext") == "Total   30.00\n\nNext"
