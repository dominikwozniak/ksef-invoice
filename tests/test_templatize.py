import re
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from lxml import etree

from ksef_invoice.config import Profile
from ksef_invoice.invoice import build_invoice, validate_fa3
from ksef_invoice.templatize import NS, templatize

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATED_AT = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)


def _q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def _profile(template_path: Path, vat_rate: str = "23") -> Profile:
    return Profile(
        name="x",
        template_path=template_path,
        vat_rate=vat_rate,
        issue_day="last",
        due_days=14,
        due_day_next_month=None,
    )


def _concrete_vat_invoice() -> bytes:
    """Konkretna (bez placeholderów) faktura VAT 23%, 1 pozycja — jak pobrana z KSeF."""
    profile = _profile(PROJECT_ROOT / "examples" / "template.example.xml")
    invoice = build_invoice(
        "2026-07",
        [Decimal("15000")],
        profile,
        number="FS/9/2026",
        generated_at=GENERATED_AT,
        today=date(2026, 7, 31),
    )
    return invoice.xml


def test_templatize_roundtrip_single_line(tmp_path):
    result = templatize(_concrete_vat_invoice())

    assert result.vat_rate == "23"
    assert result.line_count == 1
    assert not result.warnings

    root = etree.fromstring(result.xml)
    fa = root.find(_q("Fa"))
    assert root.find(_q("Naglowek")).find(_q("DataWytworzeniaFa")).text == "{{generated_at}}"
    assert fa.find(_q("P_1")).text == "{{issue_date}}"
    assert fa.find(_q("P_2")).text == "{{invoice_number}}"
    assert fa.find(_q("P_6")).text == "{{sale_date}}"
    assert fa.find(_q("P_13_1")).text == "{{net}}"
    assert fa.find(_q("P_14_1")).text == "{{vat}}"
    assert fa.find(_q("P_15")).text == "{{gross}}"
    row = fa.find(_q("FaWiersz"))
    assert row.find(_q("P_9A")).text == "{{line1_net}}"
    assert row.find(_q("P_11")).text == "{{line1_net}}"
    termin = fa.find(_q("Platnosc")).find(_q("TerminPlatnosci")).find(_q("Termin"))
    assert termin.text == "{{payment_due}}"

    # Żadna konkretna data ani kwota nie została w polach mapowanych.
    assert b"2026-07-31" not in result.xml
    assert b"15000" not in result.xml
    assert b"18450" not in result.xml

    # Round-trip: szablon znów renderuje się do poprawnej faktury FA(3).
    template = tmp_path / "roundtrip.xml"
    template.write_bytes(result.xml)
    rerendered = build_invoice(
        "2026-07",
        [Decimal("15000")],
        _profile(template),
        number="FS/9/2026",
        generated_at=GENERATED_AT,
        today=date(2026, 7, 31),
    )
    validate_fa3(rerendered.xml)  # nie może rzucić


def test_templatize_roundtrip_two_lines():
    profile = _profile(PROJECT_ROOT / "tests" / "fixtures" / "two_lines.xml")
    invoice = build_invoice(
        "2026-07",
        [Decimal("1000"), Decimal("500")],
        profile,
        number="FS/9/2026",
        generated_at=GENERATED_AT,
        today=date(2026, 7, 31),
    )
    result = templatize(invoice.xml)

    assert result.line_count == 2
    rows = etree.fromstring(result.xml).find(_q("Fa")).findall(_q("FaWiersz"))
    assert rows[0].find(_q("P_9A")).text == "{{line1_net}}"
    assert rows[0].find(_q("P_11")).text == "{{line1_net}}"
    assert rows[1].find(_q("P_9A")).text == "{{line2_net}}"
    assert rows[1].find(_q("P_11")).text == "{{line2_net}}"


def test_templatize_infers_np_rate():
    text = _concrete_vat_invoice().decode()
    text = text.replace("<P_13_1>", "<P_13_9>").replace("</P_13_1>", "</P_13_9>")
    text = re.sub(r"\s*<P_14_1>.*?</P_14_1>", "", text)
    text = text.replace("<P_12>23</P_12>", "<P_12>np II</P_12>")

    result = templatize(text.encode())

    assert result.vat_rate == "np"
    fa = etree.fromstring(result.xml).find(_q("Fa"))
    assert fa.find(_q("P_13_9")).text == "{{net}}"
    assert fa.find(_q("P_14_1")) is None


def test_templatize_warns_on_quantity_not_one():
    text = _concrete_vat_invoice().decode().replace("<P_8B>1</P_8B>", "<P_8B>2</P_8B>")
    result = templatize(text.encode())
    assert any("P_8B" in warning for warning in result.warnings)


def test_templatize_extracts_seller_nip():
    result = templatize(_concrete_vat_invoice())
    assert result.seller_nip == "1111111111"


def test_templatize_warns_on_extra_vat_rates():
    """Sumy pozostałych stawek zostają w szablonie jako sztywne kwoty — to musi być powiedziane."""
    text = (
        _concrete_vat_invoice()
        .decode()
        .replace("</P_14_1>", "</P_14_1><P_13_2>1000.00</P_13_2><P_14_2>80.00</P_14_2>", 1)
    )
    result = templatize(text.encode())
    assert any("dodatkowe stawki VAT" in warning and "P_13_2" in warning for warning in result.warnings)


def test_templatize_warns_on_unusual_vat_rate():
    text = _concrete_vat_invoice().decode().replace("<P_12>23</P_12>", "<P_12>oo</P_12>")
    result = templatize(text.encode())
    assert result.vat_rate == "oo"
    assert any("Nietypowa stawka" in warning for warning in result.warnings)


def test_templatize_warns_when_vat_rate_unreadable():
    """Bez P_12 stawka spada na domyślne 23 — nie może to przejść po cichu."""
    text = re.sub(r"\s*<P_12>.*?</P_12>", "", _concrete_vat_invoice().decode())
    result = templatize(text.encode())
    assert result.vat_rate == "23"
    assert any("stawki VAT" in warning for warning in result.warnings)


def test_templatize_warns_on_missing_payment_term():
    text = re.sub(r"\s*<Platnosc>.*?</Platnosc>", "", _concrete_vat_invoice().decode(), flags=re.DOTALL)
    result = templatize(text.encode())
    assert any("payment_due" in warning for warning in result.warnings)


def test_templatize_rejects_non_fa3_document():
    with pytest.raises(ValueError):
        templatize(b'<?xml version="1.0"?><Cokolwiek><A>1</A></Cokolwiek>')
