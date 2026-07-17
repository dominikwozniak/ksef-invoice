"""Renderowanie faktury FA(3) z szablonu XML + walidacja XSD."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from importlib.resources import files
from pathlib import Path

from lxml import etree

from .config import Profile

TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class Invoice:
    month: str
    number: str
    issue_date: date
    sale_date: date
    payment_due: date
    line_nets: tuple[Decimal, ...]
    net: Decimal
    vat: Decimal
    gross: Decimal
    xml: bytes


def _parse_month(month: str) -> tuple[int, int]:
    try:
        year_s, month_s = month.split("-")
        year, month_no = int(year_s), int(month_s)
        if not 1 <= month_no <= 12:
            raise ValueError
    except ValueError:
        raise ValueError(f"Miesiąc {month!r} — oczekiwany format RRRR-MM, np. 2026-07") from None
    return year, month_no


def compute_amounts(net: Decimal, vat_rate: str) -> tuple[Decimal, Decimal]:
    """VAT i brutto z netto; zaokrąglenie ROUND_HALF_UP do groszy.

    vat_rate "np" (usługa nie podlega VAT w kraju, np. odwrotne obciążenie UE): VAT 0, brutto = netto.
    """
    net = net.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    if vat_rate == "np":
        return Decimal("0.00"), net
    vat = (net * Decimal(vat_rate) / 100).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    return vat, net + vat


def format_number(number_format: str, seq: int, year: int, month_no: int) -> str:
    return number_format.format(seq=seq, year=year, month=month_no, month02=f"{month_no:02d}")


def build_invoice(
    month: str,
    nets: list[Decimal],
    profile: Profile,
    *,
    number: str,
    generated_at: datetime | None = None,
    today: date | None = None,
) -> Invoice:
    year, month_no = _parse_month(month)
    last_day = calendar.monthrange(year, month_no)[1]
    today = today or date.today()

    # KSeF odrzuca faktury z P_1 w przyszłości (błąd semantyki 450).
    if profile.issue_day == "today":
        issue_date = today
    elif profile.issue_day == "last":
        issue_date = date(year, month_no, last_day)
    else:
        issue_date = date(year, month_no, min(int(profile.issue_day), last_day))
    if issue_date > today:
        raise ValueError(
            f"Data wystawienia {issue_date} jest w przyszłości — KSeF odrzuci taką fakturę. "
            f'Uruchom skrypt w dniu wystawienia albo ustaw issue_day = "today" w config.toml.'
        )
    sale_date = date(year, month_no, last_day)
    if profile.due_day_next_month is not None:
        next_year, next_month = (year, month_no + 1) if month_no < 12 else (year + 1, 1)
        payment_due = date(next_year, next_month, profile.due_day_next_month)
    else:
        payment_due = issue_date + timedelta(days=profile.due_days)

    line_nets = tuple(n.quantize(TWO_PLACES, rounding=ROUND_HALF_UP) for n in nets)
    net = sum(line_nets, Decimal("0.00"))
    vat, gross = compute_amounts(net, profile.vat_rate)

    generated_at = generated_at or datetime.now(UTC)
    values = {
        "generated_at": generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "issue_date": issue_date.isoformat(),
        "sale_date": sale_date.isoformat(),
        "payment_due": payment_due.isoformat(),
        "invoice_number": number,
        "net": str(net),
        "vat": str(vat),
        "gross": str(gross),
    }
    for index, line_net in enumerate(line_nets, start=1):
        values[f"line{index}_net"] = str(line_net)

    text = profile.template_path.read_text(encoding="utf-8")
    for index in range(1, len(line_nets) + 1):
        if "{{" + f"line{index}_net" + "}}" not in text:
            raise ValueError(
                f"Podano {len(line_nets)} kwot(y) --net, a szablon {profile.template_path.name} "
                f"nie ma placeholdera {{{{line{index}_net}}}} — sprawdź liczbę pozycji."
            )
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    if "{{" in text:
        leftover = text[text.index("{{") : text.index("}}") + 2]
        raise ValueError(
            f"Niepodmieniony placeholder w szablonie: {leftover} — "
            "za mało kwot --net albo literówka w szablonie."
        )

    return Invoice(
        month=month,
        number=number,
        issue_date=issue_date,
        sale_date=sale_date,
        payment_due=payment_due,
        line_nets=line_nets,
        net=net,
        vat=vat,
        gross=gross,
        xml=text.encode("utf-8"),
    )


def _fa3_schema() -> etree.XMLSchema:
    xsd_path = Path(str(files("ksef2"))) / "infra/schema/fa3/definitions/schemat.xsd"
    return etree.XMLSchema(etree.parse(str(xsd_path)))


def validate_fa3(xml: bytes) -> None:
    """Waliduje fakturę względem oficjalnego XSD FA(3); rzuca ValueError z listą błędów."""
    document = etree.fromstring(xml)
    schema = _fa3_schema()
    if not schema.validate(document):
        errors = "\n".join(f"  linia {e.line}: {e.message}" for e in schema.error_log)
        raise ValueError(f"Faktura nie przechodzi walidacji XSD FA(3):\n{errors}")


def check_seller_nip(xml: bytes, expected_nip: str) -> None:
    """NIP sprzedawcy (Podmiot1) musi być zgodny z kontekstem uwierzytelnienia,
    inaczej KSeF odrzuci fakturę na etapie weryfikacji semantycznej."""
    document = etree.fromstring(xml)
    ns = {"fa": document.nsmap[None]}
    nodes = document.xpath("/fa:Faktura/fa:Podmiot1/fa:DaneIdentyfikacyjne/fa:NIP", namespaces=ns)
    seller_nip = nodes[0].text if nodes else None
    if seller_nip != expected_nip:
        raise ValueError(
            f"NIP sprzedawcy w szablonie ({seller_nip}) różni się od NIP w config.toml "
            f"({expected_nip}) — KSeF odrzuciłby taką fakturę."
        )
