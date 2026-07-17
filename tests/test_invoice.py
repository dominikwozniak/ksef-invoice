from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from ksef_invoice.config import Profile
from ksef_invoice.invoice import build_invoice, compute_amounts, format_number, validate_fa3

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_profile(**overrides) -> Profile:
    defaults = dict(
        name="testowy",
        template_path=PROJECT_ROOT / "examples" / "template.example.xml",
        vat_rate="23",
        issue_day="last",
        due_days=14,
        due_day_next_month=None,
    )
    return Profile(**{**defaults, **overrides})


def build(
    month="2026-07",
    nets=(Decimal("15000"),),
    number="FS/1/2026",
    today=date(2026, 7, 31),
    **profile_overrides,
):
    return build_invoice(month, list(nets), make_profile(**profile_overrides), number=number, today=today)


def test_vat_rounding_half_up():
    vat, gross = compute_amounts(Decimal("1234.56"), "23")
    assert vat == Decimal("283.95")  # 283.9488 -> 283.95
    assert gross == Decimal("1518.51")


def test_np_rate_no_vat():
    vat, gross = compute_amounts(Decimal("800"), "np")
    assert vat == Decimal("0.00")
    assert gross == Decimal("800.00")


def test_two_lines_sums():
    invoice = build(
        nets=(Decimal("1000"), Decimal("500")),
        template_path=PROJECT_ROOT / "tests" / "fixtures" / "two_lines.xml",
    )
    assert invoice.line_nets == (Decimal("1000.00"), Decimal("500.00"))
    assert invoice.net == Decimal("1500.00")
    assert invoice.vat == Decimal("345.00")
    assert invoice.gross == Decimal("1845.00")
    xml = invoice.xml.decode()
    assert "<P_9A>1000.00</P_9A>" in xml
    assert "<P_9A>500.00</P_9A>" in xml
    assert "<P_13_1>1500.00</P_13_1>" in xml


def test_too_many_nets_rejected():
    with pytest.raises(ValueError, match="line2_net"):
        build(nets=(Decimal("100"), Decimal("200")))


def test_too_few_nets_rejected():
    with pytest.raises(ValueError, match="line2_net"):
        build(nets=(Decimal("100"),), template_path=PROJECT_ROOT / "tests" / "fixtures" / "two_lines.xml")


def test_format_number():
    assert format_number("FS/{seq}/{year}", 5, 2026, 7) == "FS/5/2026"
    assert format_number("FV {month02}/{year}", 1, 2026, 7) == "FV 07/2026"


def test_dates_and_number():
    invoice = build()
    assert invoice.number == "FS/1/2026"
    assert invoice.issue_date == date(2026, 7, 31)
    assert invoice.sale_date == date(2026, 7, 31)
    assert invoice.payment_due == date(2026, 8, 14)


def test_due_day_next_month():
    # Reguła due_day_next_month: termin = 15. dzień miesiąca po miesiącu rozliczeniowym, niezależnie od P_1.
    invoice = build(
        month="2026-06", issue_day="today", today=date(2026, 6, 25), due_days=None, due_day_next_month=15
    )
    assert invoice.issue_date == date(2026, 6, 25)
    assert invoice.payment_due == date(2026, 7, 15)


def test_due_day_next_month_december_rollover():
    invoice = build(
        month="2026-12", issue_day="last", today=date(2026, 12, 31), due_days=None, due_day_next_month=15
    )
    assert invoice.payment_due == date(2027, 1, 15)


def test_issue_day_fixed_and_february_clamp():
    invoice = build(month="2027-02", issue_day=30, today=date(2027, 3, 1))
    assert invoice.issue_date == date(2027, 2, 28)


def test_issue_day_today():
    invoice = build(issue_day="today", today=date(2026, 7, 16))
    assert invoice.issue_date == date(2026, 7, 16)
    assert invoice.sale_date == date(2026, 7, 31)
    assert invoice.payment_due == date(2026, 7, 30)


def test_future_issue_date_rejected():
    with pytest.raises(ValueError, match="w przyszłości"):
        build(issue_day="last", today=date(2026, 7, 16))


def test_invalid_month_rejected():
    with pytest.raises(ValueError, match="RRRR-MM"):
        build(month="07-2026")


def test_rendered_xml_contains_values_and_no_placeholders():
    invoice = build_invoice(
        "2026-07",
        [Decimal("15000")],
        make_profile(),
        number="FS/3/2026",
        generated_at=datetime(2026, 7, 31, 10, 0, tzinfo=UTC),
        today=date(2026, 7, 31),
    )
    xml = invoice.xml.decode()
    assert "{{" not in xml
    assert "<P_2>FS/3/2026</P_2>" in xml
    assert "<P_1>2026-07-31</P_1>" in xml
    assert "<P_13_1>15000.00</P_13_1>" in xml
    assert "<P_14_1>3450.00</P_14_1>" in xml
    assert "<P_15>18450.00</P_15>" in xml
    assert "<Termin>2026-08-14</Termin>" in xml


def test_rendered_xml_is_xsd_valid():
    validate_fa3(build().xml)  # nie może rzucić


def test_invalid_xml_fails_validation():
    broken = build().xml.replace(b"<KodWaluty>PLN</KodWaluty>", b"")
    with pytest.raises(ValueError, match="XSD"):
        validate_fa3(broken)
