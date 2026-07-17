from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ksef_invoice.config import Profile
from ksef_invoice.invoice import build_invoice
from ksef_invoice.visualize import to_html, to_pdf

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def invoice_xml() -> bytes:
    profile = Profile(
        name="testowy",
        template_path=PROJECT_ROOT / "examples" / "template.example.xml",
        vat_rate="23",
        issue_day="last",
        due_days=14,
        due_day_next_month=None,
    )
    return build_invoice(
        "2026-07", [Decimal("15000")], profile, number="FS/9/2026", today=date(2026, 7, 31)
    ).xml


def test_to_html_contains_invoice_number(invoice_xml):
    html = to_html(invoice_xml).decode("utf-8")
    assert "FS/9/2026" in html
    assert "<html" in html.lower()


def test_to_pdf(invoice_xml):
    pdf = to_pdf(invoice_xml)
    if pdf is None:
        pytest.skip("WeasyPrint/pango niedostępne w tym środowisku")
    assert pdf.startswith(b"%PDF")
