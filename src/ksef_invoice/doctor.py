"""Weryfikacja setupu bez wysyłki: czy config, szablony i profile są spójne.

Każdy check zwraca `Check` — nazwę, status i opis. Nic nie zapisuje na dysk i nie
dotyka KSeF; token raportujemy wyłącznie jako obecny/nieobecny, nigdy jego wartość.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from .config import Config, Profile, load_config
from .invoice import build_invoice, check_seller_nip, issue_date_for, validate_fa3
from .ledger import Ledger
from .onboard import nip_checksum_ok, suspicious_nip_warning
from .visualize import PDF_HINT, PDF_NO_EXTRA, PDF_NO_PANGO, pdf_status, to_pdf

LINE_PLACEHOLDER = re.compile(r"\{\{line(\d+)_net\}\}")

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def line_count(template_path: Path) -> int:
    """Ile kwot --net wymaga szablon — liczba różnych {{lineN_net}}."""
    text = template_path.read_text(encoding="utf-8")
    return len({int(match) for match in LINE_PLACEHOLDER.findall(text)})


def _probe_month(profile: Profile, today: date) -> str:
    """Miesiąc próbnego renderu: bieżący, a gdy data wystawienia z profilu jeszcze w nim
    nie nadeszła (issue_day = "last" albo dzień późniejszy niż dzisiejszy) — poprzedni.

    Bez tego poprawnie skonfigurowany profil z issue_day = "last" świeciłby na czerwono
    przez cały miesiąc poza jego ostatnim dniem, bo build_invoice słusznie odrzuca P_1
    z przyszłości.
    """
    if issue_date_for(profile, today.year, today.month, today) <= today:
        return f"{today.year:04d}-{today.month:02d}"
    previous = date(today.year, today.month, 1) - timedelta(days=1)
    return f"{previous.year:04d}-{previous.month:02d}"


def _check_profile(config: Config, profile: Profile, today: date) -> list[Check]:
    """Próbny render profilu: XSD + zgodność NIP-u, na kwotach 1.00 za możliwy miesiąc."""
    label = f"profil {profile.name}"
    count = line_count(profile.template_path)
    if count == 0:
        return [
            Check(
                label,
                FAIL,
                f"{profile.template_path.name}: brak placeholderów {{{{line1_net}}}} — "
                "szablon nie ma zmiennych pozycji (użyj `templatize`).",
            )
        ]

    try:
        # Wybór miesiąca też czyta issue_day, więc musi być pod tym samym try —
        # zepsute issue_day ("foo", 0) ma dać FAIL, a nie wywalić całą diagnostykę.
        month = _probe_month(profile, today)
        invoice = build_invoice(
            month,
            [Decimal("1.00")] * count,
            profile,
            number="FS/1/2026",
            today=today,
        )
        validate_fa3(invoice.xml)
        check_seller_nip(invoice.xml, config.nip)
    except Exception as error:  # noqa: BLE001 — każdy błąd renderu to wynik do pokazania
        return [Check(label, FAIL, str(error).replace("\n", " ")[:300])]

    due = "po terminie" if invoice.payment_due < invoice.issue_date else invoice.payment_due.isoformat()
    vat = "np (bez VAT)" if profile.vat_rate == "np" else f"{profile.vat_rate}%"
    return [
        Check(
            label,
            OK,
            f"{count}× --net, VAT {vat}, termin {due} — render za {month} przechodzi XSD FA(3)",
        )
    ]


def _legacy_layout_hint(root: Path) -> Check | None:
    """Stary układ (stan trzymany w klonie repo) wykryty w katalogu roboczym shella.

    Sama podpowiedź, świadomie — przenoszenia kod nie robi. Połowicznie wykonana
    migracja out/ledger.json to dokładnie ta awaria, która duplikuje numer faktury.
    """
    legacy = Path.cwd()
    if legacy == root or not (legacy / "config.toml").exists():
        return None
    return Check(
        "migracja",
        WARN,
        f"config.toml leży w {legacy}, a szukam go w {root}. Przenieś stan: "
        f"cp -a config.toml .env templates out {root}/ (cp, nie mv — potem sprawdź, "
        "czy licznik jest ten sam, i dopiero wtedy usuń kopie).",
    )


def run_checks(root: Path, today: date | None = None) -> list[Check]:
    """Wszystkie checki po kolei; pierwszy blokujący (brak configu) przerywa dalsze."""
    today = today or date.today()
    checks: list[Check] = []

    try:
        config = load_config(root)
    except Exception as error:  # noqa: BLE001 — komunikaty load_config są celowo instruktażowe
        checks.append(Check("config.toml", FAIL, str(error).replace("\n", " ")[:300]))
        hint = _legacy_layout_hint(root)
        if hint:
            checks.append(hint)
        return checks

    checks.append(Check("config.toml", OK, f"wczytany, {len(config.profiles)} profil(e)"))

    if not nip_checksum_ok(config.nip):
        checks.append(Check("NIP sprzedawcy", FAIL, f"{config.nip} — niepoprawna suma kontrolna"))
    else:
        suspicious = suspicious_nip_warning(config.nip)
        checks.append(
            Check(
                "NIP sprzedawcy",
                WARN if suspicious else OK,
                suspicious or f"{config.nip} — suma kontrolna OK",
            )
        )

    for profile in sorted(config.profiles.values(), key=lambda item: item.name):
        checks.extend(_check_profile(config, profile, today))

    checks.append(Check("środowisko", OK, f"KSEF_ENV={config.environment}"))
    if config.environment == "test":
        checks.append(Check("uwierzytelnienie", OK, "TEST — certyfikat testowy z SDK, token niepotrzebny"))
    elif config.ksef_token:
        checks.append(
            Check("uwierzytelnienie", OK, f"KSEF_TOKEN ustawiony ({len(config.ksef_token)} znaków)")
        )
    else:
        checks.append(
            Check(
                "uwierzytelnienie",
                FAIL,
                f"środowisko {config.environment} wymaga KSEF_TOKEN w .env — wysyłka przerwie się przed KSeF",
            )
        )

    ledger = Ledger(config.out_dir / "ledger.json")
    for environment in ("test", "prod"):
        started = ledger.year_started(environment, today.year)
        seq = ledger.next_seq(environment, today.year)
        detail = f"następny numer w {today.year}: {seq}" + (
            "" if started else " (licznik nie zasiany — użyj --seq)"
        )
        checks.append(Check(f"licznik {environment}", OK, detail))

    checks.append(_check_pdf(config, today))
    return checks


def _check_pdf(config: Config, today: date) -> Check:
    """Trzy różne stany wymagają trzech różnych instrukcji naprawy — dotąd wszystkie
    kończyły się jednym „brak WeasyPrint". Brak PDF-a jest oczekiwany, nie jest defektem."""
    status = pdf_status()
    if status == PDF_NO_EXTRA:
        return Check(
            "PDF",
            WARN,
            "wyłączony — instalacja bez extry [pdf]; HTML powstaje i drukuje się do PDF-a "
            "z przeglądarki. Chcesz lokalnego PDF-a: uv tool install --force 'ksef-invoice[pdf]'",
        )
    if status == PDF_NO_PANGO:
        # PDF_HINT jest zależny od platformy — wcześniej ta podpowiedź żyła w trzech
        # miejscach i rozjechała się (na Linuksie radziła `brew install`).
        return Check("PDF", WARN, f"extra [pdf] jest, brakuje biblioteki natywnej. {PDF_HINT}")

    probe = _probe_xml(config, today)
    if probe is None:
        return Check("PDF", WARN, "nie sprawdzono — żaden profil nie renderuje się poprawnie")
    if to_pdf(probe) is not None:
        return Check("PDF", OK, "WeasyPrint działa — powstaje invoice.pdf")
    return Check("PDF", WARN, f"WeasyPrint jest, ale render PDF-a się nie udał. {PDF_HINT}")


def _probe_xml(config: Config, today: date) -> bytes | None:
    """Faktura z pierwszego działającego profilu — wejście dla sprawdzenia renderera PDF."""
    for profile in config.profiles.values():
        try:
            count = line_count(profile.template_path)
            if not count:
                continue
            return build_invoice(
                _probe_month(profile, today),
                [Decimal("1.00")] * count,
                profile,
                number="FS/1/2026",
                today=today,
            ).xml
        except Exception:  # noqa: BLE001 — profil zepsuty zgłosi już _check_profile
            continue
    return None
