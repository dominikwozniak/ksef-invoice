"""Zamiana pobranej z KSeF faktury FA(3) w szablon z placeholderami.

Mapowanie odbywa się po ścieżkach elementów FA(3) (nie po wartościach — dzięki temu
te same liczby w różnych polach nie mylą się ze sobą). Wynik to szablon zgodny z tym,
czego oczekuje `build_invoice` (placeholdery `{{...}}`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lxml import etree

from .invoice import validate_fa3

NS = "http://crd.gov.pl/wzor/2025/06/25/13775/"

# Dodatkowe sumy stawek VAT — model obsługuje jedną stawkę, obecność innych sygnalizujemy.
_EXTRA_RATE_TAGS = ("P_13_2", "P_13_3", "P_13_4", "P_13_5", "P_13_6", "P_13_7", "P_13_8")


@dataclass
class TemplatizeResult:
    xml: bytes
    vat_rate: str
    line_count: int
    warnings: list[str] = field(default_factory=list)


def _q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def templatize(xml: bytes) -> TemplatizeResult:
    """Zwraca szablon z placeholderami + wywnioskowaną stawkę VAT i ostrzeżenia.

    Waliduje wejście oficjalnym XSD FA(3) — to ma być prawdziwa faktura pobrana z KSeF.
    """
    validate_fa3(xml)
    root = etree.fromstring(xml)
    warnings: list[str] = []

    def set_ph(parent: etree._Element | None, tag: str, placeholder: str) -> etree._Element | None:
        el = parent.find(_q(tag)) if parent is not None else None
        if el is not None:
            el.text = "{{" + placeholder + "}}"
        return el

    naglowek = root.find(_q("Naglowek"))
    set_ph(naglowek, "DataWytworzeniaFa", "generated_at")

    fa = root.find(_q("Fa"))
    if fa is None:
        raise ValueError("Brak elementu <Fa> — to nie wygląda na fakturę FA(3).")

    for tag, placeholder in (("P_1", "issue_date"), ("P_2", "invoice_number"), ("P_6", "sale_date")):
        if set_ph(fa, tag, placeholder) is None:
            warnings.append(f"Brak pola {tag} — uzupełnij {{{{{placeholder}}}}} w szablonie ręcznie.")

    # Suma netto: P_13_1 (stawka krajowa) albo P_13_9 (np./poza terytorium kraju).
    if fa.find(_q("P_13_1")) is not None:
        set_ph(fa, "P_13_1", "net")
    elif fa.find(_q("P_13_9")) is not None:
        set_ph(fa, "P_13_9", "net")
    else:
        warnings.append("Brak P_13_1/P_13_9 (suma netto) — uzupełnij {{net}} ręcznie.")

    if fa.find(_q("P_14_1")) is not None:
        set_ph(fa, "P_14_1", "vat")

    if set_ph(fa, "P_15", "gross") is None:
        warnings.append("Brak P_15 (brutto) — uzupełnij {{gross}} ręcznie.")

    extra_rates = [tag for tag in _EXTRA_RATE_TAGS if fa.find(_q(tag)) is not None]
    if extra_rates:
        warnings.append(
            f"Wykryto dodatkowe stawki VAT ({', '.join(extra_rates)}); model obsługuje jedną "
            "stawkę na fakturę — dopracuj szablon ręcznie."
        )

    rows = fa.findall(_q("FaWiersz"))
    for index, row in enumerate(rows, start=1):
        set_ph(row, "P_9A", f"line{index}_net")
        set_ph(row, "P_11", f"line{index}_net")
        qty = row.find(_q("P_8B"))
        qty_text = (qty.text or "").strip() if qty is not None else ""
        if qty_text and qty_text not in ("1", "1.00", "1.0000"):
            warnings.append(
                f"Pozycja {index}: ilość P_8B={qty_text!r} ≠ 1 — {{{{line{index}_net}}}} podstawiono "
                "i pod cenę jednostkową (P_9A), i pod wartość (P_11); zweryfikuj szablon."
            )

    payment = None
    platnosc = fa.find(_q("Platnosc"))
    if platnosc is not None:
        termin_platnosci = platnosc.find(_q("TerminPlatnosci"))
        payment = set_ph(termin_platnosci, "Termin", "payment_due")
    if payment is None:
        warnings.append("Brak Platnosc/TerminPlatnosci/Termin — dodaj {{payment_due}} ręcznie.")

    vat_rate = "23"
    if rows:
        p12 = rows[0].find(_q("P_12"))
        raw = (p12.text or "").strip() if p12 is not None else ""
        if raw.lower().startswith("np"):
            vat_rate = "np"
        elif raw.isdigit():
            vat_rate = raw
        elif raw:
            vat_rate = raw
            warnings.append(f"Nietypowa stawka P_12={raw!r} — ustaw vat_rate w config.toml ręcznie.")

    out = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
    return TemplatizeResult(xml=out, vat_rate=vat_rate, line_count=len(rows), warnings=warnings)
