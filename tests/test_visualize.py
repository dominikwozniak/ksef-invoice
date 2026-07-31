import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ksef_invoice.config import Profile
from ksef_invoice.invoice import build_invoice
from ksef_invoice.visualize import _fix_native_lib_lookup, to_html, to_pdf

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


def test_to_html_carries_print_css(invoice_xml):
    """Bez extry [pdf] HTML jest jedynym artefaktem do druku, więc musi mieć geometrię
    strony z SDK — inaczej Cmd/Ctrl+P dałoby inny układ niż PDF z WeasyPrinta."""
    html = to_html(invoice_xml).decode("utf-8")

    assert "@page" in html
    assert "A4 landscape" in html
    assert html.index("@page") < html.index("</head>")


def test_to_pdf(invoice_xml):
    pdf = to_pdf(invoice_xml)
    if pdf is None:
        pytest.skip("WeasyPrint/pango niedostępne w tym środowisku")
    assert pdf.startswith(b"%PDF")


@pytest.mark.skipif(sys.platform != "darwin", reason="poprawka dotyczy wyłącznie macOS")
def test_dyld_fixup_adds_homebrew_prefix(monkeypatch):
    """Regresja buga PDF-a: WeasyPrint szuka pango przez ctypes.util.find_library, a to
    na macOS czyta DEFAULT_LIBRARY_FALLBACK. Python z Homebrew ma tam swój prefiks,
    czysty CPython (ten od uv) nie — i PDF milcząco przestawał działać."""
    from ctypes.macholib import dyld

    if not os.path.isdir("/opt/homebrew/lib"):
        pytest.skip("brak /opt/homebrew/lib na tej maszynie")
    monkeypatch.setattr(dyld, "DEFAULT_LIBRARY_FALLBACK", ["/usr/local/lib", "/lib", "/usr/lib"])

    _fix_native_lib_lookup()

    assert "/opt/homebrew/lib" in dyld.DEFAULT_LIBRARY_FALLBACK


@pytest.mark.skipif(sys.platform != "darwin", reason="poprawka dotyczy wyłącznie macOS")
def test_dyld_fixup_has_an_escape_hatch(monkeypatch):
    from ctypes.macholib import dyld

    original = ["/usr/local/lib", "/lib", "/usr/lib"]
    monkeypatch.setattr(dyld, "DEFAULT_LIBRARY_FALLBACK", list(original))
    monkeypatch.setenv("KSEF_INVOICE_NO_DYLD_FIXUP", "1")

    _fix_native_lib_lookup()

    assert dyld.DEFAULT_LIBRARY_FALLBACK == original
