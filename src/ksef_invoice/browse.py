"""Przeglądanie katalogu roboczego: co jest w ledgerze i co leży w out/.

Czysty odczyt — bez `rich` i bez `typer`, tak jak `doctor.py` oddziela checki od
formatowania. Nic nie zapisuje i nie dotyka KSeF: źródłem jest wyłącznie
`out/ledger.json` i zawartość `out/`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .config import Config
from .ledger import Ledger


@dataclass(frozen=True)
class InvoiceRow:
    """Jedna wystawiona faktura. Pola opcjonalne, bo wpisy z wcześniejszych wersji
    `meta` nie mają wszystkich kluczy (w prawdziwym ledgerze brakuje `line_nets`)."""

    month: str
    profile: str
    number: str | None
    seq: int | None
    net: str | None
    vat: str | None
    gross: str | None
    ksef_number: str | None
    acquisition_date: str | None
    sent_at: str | None
    # None = na dysku nie ma katalogu z artefaktami. Świadomie nie składamy ścieżki
    # z numeru: nigdy nie pokazujemy ścieżki, której nie da się otworzyć. Ten stan
    # oznacza zwykle ledger skopiowany bez out/, czyli połowicznie wykonaną migrację.
    directory: Path | None


def invoice_dirs(config: Config, environment: str, profile: str, month: str) -> list[Path]:
    """Katalogi z artefaktami faktury. Wiele wyników to realny stan po `send --force`."""
    base = config.out_dir / environment / profile
    return sorted(match for match in base.glob(f"{month}_*") if match.is_dir())


def invoice_rows(
    config: Config,
    environment: str,
    *,
    profile: str | None = None,
    year: int | None = None,
) -> list[InvoiceRow]:
    """Wystawione faktury z ledgera, chronologicznie.

    Iterujemy ledger, nie `config.profiles` — ledger jest historią, więc faktura
    wystawiona na profilu później usuniętym z config.toml musi zostać widoczna.
    """
    ledger = Ledger(config.out_dir / "ledger.json")
    rows = []
    for entry_profile, month, entry in ledger.entries(environment):
        if profile is not None and entry_profile != profile:
            continue
        if year is not None and not month.startswith(f"{year}-"):
            continue
        directories = invoice_dirs(config, environment, entry_profile, month)
        rows.append(
            InvoiceRow(
                month=month,
                profile=entry_profile,
                number=entry.get("number"),
                seq=entry.get("seq"),
                net=entry.get("net"),
                vat=entry.get("vat"),
                gross=entry.get("gross"),
                ksef_number=entry.get("ksef_number"),
                acquisition_date=entry.get("acquisition_date"),
                sent_at=entry.get("sent_at"),
                directory=directories[0] if directories else None,
            )
        )
    return rows


def ledger_profiles(config: Config, environment: str) -> set[str]:
    """Nazwy profili występujące w ledgerze — do walidacji --profile obok config.toml."""
    return {profile for profile, _, _ in Ledger(config.out_dir / "ledger.json").entries(environment)}


def gross_total(rows: list[InvoiceRow]) -> Decimal:
    """Suma brutto. Kwoty w ledgerze są stringami, więc liczymy na Decimal — na
    pieniądzach nie ma tu float. Wpisy bez `gross` są pomijane."""
    return sum((Decimal(row.gross) for row in rows if row.gross is not None), Decimal(0))
