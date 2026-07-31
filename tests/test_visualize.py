import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ksef_invoice.config import Profile
from ksef_invoice.invoice import build_invoice
from ksef_invoice.visualize import PDF_HINT, _add_homebrew_to_dyld_path, to_html, to_pdf

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


def test_pdf_hint_mentions_this_platform():
    """Podpowiedź musi pasować do systemu — kiedyś na Linuksie radziła `brew install`."""
    expected = {"darwin": "brew", "linux": "apt", "win32": "GTK3"}[
        "linux" if sys.platform.startswith("linux") else sys.platform
    ]
    assert expected in PDF_HINT


def test_add_homebrew_to_dyld_path_is_additive(monkeypatch):
    """Katalog Homebrew doklejamy na koniec, nie kasując tego, co ustawił użytkownik."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/moje/lib")
    monkeypatch.setattr("ksef_invoice.visualize._HOMEBREW_LIB_DIRS", ("/opt/homebrew/lib",))

    _add_homebrew_to_dyld_path()
    parts = os.environ["DYLD_LIBRARY_PATH"].split(os.pathsep)

    assert parts[0] == "/moje/lib"
    assert parts[1:] == (["/opt/homebrew/lib"] if Path("/opt/homebrew/lib").is_dir() else [])
    _add_homebrew_to_dyld_path()  # idempotentne — nie dokłada drugi raz
    assert os.environ["DYLD_LIBRARY_PATH"] == os.pathsep.join(parts)


def test_add_homebrew_to_dyld_path_skips_other_platforms(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DYLD_LIBRARY_PATH", raising=False)

    _add_homebrew_to_dyld_path()

    assert "DYLD_LIBRARY_PATH" not in os.environ
