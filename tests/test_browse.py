"""Logika przeglądania: spłaszczanie ledgera, filtry, katalogi z artefaktami.

Testowane wprost, bez CliRunner — przez tabelę widać tylko sformatowany tekst,
a tu chodzi o to, co ma się w niej w ogóle znaleźć.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from ksef_invoice.browse import (
    artifact_dir_name,
    gross_total,
    invoice_dirs,
    invoice_rows,
    ledger_profiles,
)
from ksef_invoice.config import Config, Profile
from ksef_invoice.ledger import Ledger

FULL_ENTRY_KEYS = ("number", "seq", "net", "vat", "gross", "ksef_number", "acquisition_date", "sent_at")


def _config(tmp_path: Path, *profile_names: str, environment: str = "test") -> Config:
    return Config(
        nip="5252000019",
        number_format="FS/{seq}/{year}",
        profiles={
            name: Profile(
                name=name,
                template_path=tmp_path / f"{name}.xml",
                vat_rate="23",
                issue_day="today",
                due_days=14,
                due_day_next_month=None,
            )
            for name in profile_names
        },
        environment=environment,
        ksef_token=None,
        out_dir=tmp_path / "out",
    )


def _record(config: Config, environment: str, profile: str, month_key: str, seq: int, **overrides) -> str:
    """Wpis w ledgerze jak po udanym `send`; zwraca numer faktury.

    `month_key` to klucz w ledgerze; `month=` w overrides nadpisuje pole *wewnątrz* wpisu —
    rozjazd tych dwóch jest tu przedmiotem testu, więc muszą być osobno adresowalne.
    """
    number = overrides.pop("number", f"FS/{seq}/2026")
    entry = {
        "month": month_key,
        "profile": profile,
        "number": number,
        "seq": seq,
        "net": "1000.00",
        "vat": "230.00",
        "gross": "1230.00",
        "ksef_number": f"KSEF-{seq}",
        "acquisition_date": "2026-07-31 10:00:00+00:00",
        "sent_at": "2026-07-31T10:00:01+00:00",
    }
    entry.update(overrides)
    Ledger(config.out_dir / "ledger.json").record(environment, profile, month_key, seq, 2026, entry)
    return number


def _artifacts(config: Config, environment: str, profile: str, month: str, number: str) -> Path:
    target = config.out_dir / environment / profile / f"{month}_{number.replace('/', '-')}"
    target.mkdir(parents=True)
    return target


# --- kolejność i filtry ------------------------------------------------------------


def test_rows_are_ordered_by_month_then_profile(tmp_path):
    config = _config(tmp_path, "b", "a")
    _record(config, "test", "b", "2026-07", 3)
    _record(config, "test", "a", "2026-05", 1)
    _record(config, "test", "b", "2026-05", 2)

    rows = invoice_rows(config, "test")

    assert [(row.month, row.profile) for row in rows] == [
        ("2026-05", "a"),
        ("2026-05", "b"),
        ("2026-07", "b"),
    ]


def test_environments_do_not_leak_into_each_other(tmp_path):
    """Ta sama klasa błędu co licznik per środowisko: faktura produkcyjna nie może
    pokazać się w listingu testowym ani odwrotnie."""
    config = _config(tmp_path, "klient")
    _record(config, "test", "klient", "2026-07", 5)
    _record(config, "prod", "klient", "2026-07", 8)

    assert [row.number for row in invoice_rows(config, "test")] == ["FS/5/2026"]
    assert [row.number for row in invoice_rows(config, "prod")] == ["FS/8/2026"]


def test_year_filter_uses_the_ledger_month_key(tmp_path):
    """Klucz miesiąca jest autorytatywny — wpisy z wcześniejszych wersji `meta` mogą
    mieć w środku cokolwiek, a numeracja wisi na kluczu."""
    config = _config(tmp_path, "klient")
    _record(config, "test", "klient", "2026-03", 1, month="2025-12")

    assert [row.month for row in invoice_rows(config, "test", year=2026)] == ["2026-03"]
    assert invoice_rows(config, "test", year=2025) == []


def test_profile_filter_narrows_to_one(tmp_path):
    config = _config(tmp_path, "a", "b")
    _record(config, "test", "a", "2026-05", 1)
    _record(config, "test", "b", "2026-06", 2)

    assert [row.profile for row in invoice_rows(config, "test", profile="b")] == ["b"]


def test_profile_removed_from_config_is_still_listed(tmp_path):
    """Ledger jest historią, nie widokiem config.toml — faktura wystawiona na profilu
    później usuniętym z konfiguracji nie może zniknąć z listingu."""
    config = _config(tmp_path, "obecny")
    _record(config, "test", "juz-nieobecny", "2026-04", 1)

    assert [row.profile for row in invoice_rows(config, "test")] == ["juz-nieobecny"]
    assert ledger_profiles(config, "test") == {"juz-nieobecny"}


def test_empty_ledger_gives_empty_list(tmp_path):
    assert invoice_rows(_config(tmp_path, "klient"), "test") == []


# --- tolerancja na starsze wpisy ---------------------------------------------------


def test_entry_without_optional_keys_still_lists(tmp_path):
    """Prawdziwy ledger ma wpisy bez `line_nets` (starsza wersja `meta`), więc każde
    pole poza kluczami musi być opcjonalne — brak nie może wywalić listingu."""
    config = _config(tmp_path, "klient")
    Ledger(config.out_dir / "ledger.json").record(
        "test", "klient", "2026-02", 1, 2026, {"number": "FS/1/2026"}
    )

    (row,) = invoice_rows(config, "test")

    assert row.number == "FS/1/2026"
    assert (row.net, row.vat, row.gross, row.ksef_number, row.seq) == (None,) * 5


def test_full_entry_maps_every_field(tmp_path):
    """Kontrola pozytywna dla testu powyżej: gdy wpis ma wszystko, wiersz też ma."""
    config = _config(tmp_path, "klient")
    _record(config, "test", "klient", "2026-02", 1)

    (row,) = invoice_rows(config, "test")

    assert all(getattr(row, key) is not None for key in FULL_ENTRY_KEYS)


# --- katalogi z artefaktami --------------------------------------------------------


def test_directory_is_none_when_artifacts_are_missing(tmp_path):
    """Ledger skopiowany bez out/ to połowicznie wykonana migracja. Świadomie nie
    składamy ścieżki z numeru — nigdy nie pokazujemy ścieżki, której nie da się otworzyć."""
    config = _config(tmp_path, "klient")
    _record(config, "test", "klient", "2026-07", 1)

    (row,) = invoice_rows(config, "test")

    assert row.directory is None


def test_directory_points_at_existing_artifacts(tmp_path):
    config = _config(tmp_path, "klient")
    number = _record(config, "test", "klient", "2026-07", 1)
    expected = _artifacts(config, "test", "klient", "2026-07", number)

    (row,) = invoice_rows(config, "test")

    assert row.directory == expected


def test_directory_belongs_to_the_entry_after_force(tmp_path):
    """Po `send --force` w out/ leżą dwa katalogi, a w ledgerze zostaje tylko nowszy wpis
    (record nadpisuje klucz miesiąca). Wiersz musi wskazywać katalog SWOJEJ faktury —
    inaczej `list --json` paruje metadane jednej faktury ze ścieżką drugiej."""
    config = _config(tmp_path, "klient")
    _artifacts(config, "test", "klient", "2026-07", "FS/8/2026")
    _record(config, "test", "klient", "2026-07", 8)
    forced = _artifacts(config, "test", "klient", "2026-07", "FS/9/2026")
    _record(config, "test", "klient", "2026-07", 9)

    (row,) = invoice_rows(config, "test")

    assert row.number == "FS/9/2026"
    assert row.directory == forced


def test_directory_is_not_picked_by_sort_order(tmp_path):
    """Kontrola dla testu powyżej: przy FS/9 i FS/10 najstarszy katalog jest leksykograficznie
    drugi, więc wybór „pierwszy z globa" trafiał tu poprawnie przez przypadek. Bez tego testu
    poprawka dałaby się cofnąć w połowie przypadków bez czerwonego testu."""
    config = _config(tmp_path, "klient")
    ninth = _artifacts(config, "test", "klient", "2026-07", "FS/9/2026")
    _artifacts(config, "test", "klient", "2026-07", "FS/10/2026")
    _record(config, "test", "klient", "2026-07", 9)

    (row,) = invoice_rows(config, "test")

    assert row.directory == ninth


def test_directory_is_none_when_only_another_invoices_dir_survives(tmp_path):
    """Katalog innej faktury tego miesiąca nie jest zamiennikiem: ścieżka wskazująca cudzą
    fakturę jest gorsza niż jej brak, bo w skrypcie wygląda na poprawną."""
    config = _config(tmp_path, "klient")
    _artifacts(config, "test", "klient", "2026-07", "FS/8/2026")
    _record(config, "test", "klient", "2026-07", 9)

    (row,) = invoice_rows(config, "test")

    assert row.directory is None


def test_directory_is_none_for_an_entry_without_a_number(tmp_path):
    """Bez numeru nie ma z czego złożyć nazwy katalogu — i tak wtedy kolumna `numer`
    pokazuje `—`, więc `pliki` też."""
    config = _config(tmp_path, "klient")
    Ledger(config.out_dir / "ledger.json").record("test", "klient", "2026-07", 1, 2026, {"seq": 1})
    _artifacts(config, "test", "klient", "2026-07", "FS/1/2026")

    (row,) = invoice_rows(config, "test")

    assert (row.number, row.directory) == (None, None)


def test_artifact_dir_name_keeps_the_number_readable(tmp_path):
    """Ukośnik nie może wejść do nazwy katalogu (zrobiłby zagnieżdżenie), spacja psuje
    podstawienie w shellu. Ta funkcja jest jedyną regułą — sprawdzoną po obu stronach
    w test_cli.test_invoice_dir_uses_the_shared_artifact_dir_name."""
    assert artifact_dir_name("2026-07", "FS/8/2026") == "2026-07_FS-8-2026"
    assert artifact_dir_name("2026-07", "FS 8 2026") == "2026-07_FS_8_2026"


def test_invoice_dirs_returns_every_directory_for_a_month(tmp_path):
    """Dwa katalogi na jeden miesiąc to realny stan po `send --force`."""
    config = _config(tmp_path, "klient")
    first = _artifacts(config, "test", "klient", "2026-07", "FS/1/2026")
    second = _artifacts(config, "test", "klient", "2026-07", "FS/9/2026")

    assert invoice_dirs(config, "test", "klient", "2026-07") == sorted([first, second])


def test_invoice_dirs_ignores_stray_files(tmp_path):
    config = _config(tmp_path, "klient")
    target = _artifacts(config, "test", "klient", "2026-07", "FS/1/2026")
    (target.parent / "2026-07_notatki.txt").write_text("nie katalog\n")

    assert invoice_dirs(config, "test", "klient", "2026-07") == [target]


def test_invoice_dirs_on_missing_profile_dir_is_empty(tmp_path):
    assert invoice_dirs(_config(tmp_path, "klient"), "test", "klient", "2026-07") == []


# --- suma brutto ------------------------------------------------------------------


def test_gross_total_sums_on_decimal(tmp_path):
    config = _config(tmp_path, "klient")
    _record(config, "test", "klient", "2026-05", 1, gross="0.10")
    _record(config, "test", "klient", "2026-06", 2, gross="0.20")

    total = gross_total(invoice_rows(config, "test"))

    # 0.1 + 0.2 na floatach dałoby 0.30000000000000004 — kwoty liczymy na Decimal.
    assert total == Decimal("0.30")
    assert isinstance(total, Decimal)


def test_gross_total_skips_entries_without_gross(tmp_path):
    config = _config(tmp_path, "klient")
    _record(config, "test", "klient", "2026-05", 1, gross="1230.00")
    Ledger(config.out_dir / "ledger.json").record(
        "test", "klient", "2026-06", 2, 2026, {"number": "FS/2/2026"}
    )

    assert gross_total(invoice_rows(config, "test")) == Decimal("1230.00")


def test_gross_total_of_nothing_is_zero(tmp_path):
    assert gross_total(invoice_rows(_config(tmp_path, "klient"), "test")) == Decimal(0)
