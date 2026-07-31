"""Warstwa CLI: helpery i powierzchnia komend.

Helpery testujemy wprost, bo to one decydują o numerze faktury i o tym, gdzie
ląduje szablon — a przez CliRunner widać tylko sformatowany tekst.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from ksef_invoice.cli import (
    _allocate_number,
    _invoice_dir,
    _parse_nets,
    _resolve_profile,
    _template_ref,
    app,
)
from ksef_invoice.config import Config, Profile
from ksef_invoice.invoice import Invoice
from ksef_invoice.ledger import Ledger

COMMANDS = ("render", "send", "pdf", "status", "templatize", "init", "doctor")


def _profile(name: str) -> Profile:
    return Profile(
        name=name,
        template_path=Path("t.xml"),
        vat_rate="23",
        issue_day="today",
        due_days=14,
        due_day_next_month=None,
    )


def _config(*profile_names: str, out_dir: Path = Path("out"), environment: str = "test") -> Config:
    return Config(
        nip="5252000019",
        number_format="FS/{seq}/{year}",
        profiles={name: _profile(name) for name in profile_names},
        environment=environment,
        ksef_token=None,
        out_dir=out_dir,
    )


# --- _parse_nets -------------------------------------------------------------------


def test_parse_nets_accepts_comma_decimal():
    """Polska klawiatura numeryczna daje przecinek — musi być równoważny kropce."""
    assert _parse_nets(["1000,50", "500"]) == [Decimal("1000.50"), Decimal("500")]


def test_parse_nets_rejects_non_number():
    with pytest.raises(typer.BadParameter, match="nie jest liczbą"):
        _parse_nets(["1000zł"])


@pytest.mark.parametrize("value", ["0", "-1", "0,00"])
def test_parse_nets_rejects_non_positive(value):
    with pytest.raises(typer.BadParameter, match="dodatnia"):
        _parse_nets([value])


# --- _resolve_profile --------------------------------------------------------------


def test_resolve_profile_autoselects_single():
    assert _resolve_profile(_config("jedyny"), None).name == "jedyny"


def test_resolve_profile_demands_choice_when_ambiguous():
    with pytest.raises(typer.BadParameter, match="Wybierz profil") as error:
        _resolve_profile(_config("b", "a"), None)
    # Nazwy muszą być posortowane, żeby podpowiedź nie zmieniała kolejności między uruchomieniami.
    assert "a, b" in str(error.value)


def test_resolve_profile_rejects_unknown_name():
    with pytest.raises(typer.BadParameter, match="Nieznany profil"):
        _resolve_profile(_config("a"), "literowka")


# --- _allocate_number --------------------------------------------------------------


def test_allocate_number_takes_next_from_ledger(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.record("test", "a", "2026-06", 4, 2026, {"number": "FS/4/2026"})

    assert _allocate_number(_config("a"), ledger, "2026-07", None) == (5, 2026, "FS/5/2026")


def test_allocate_number_starts_at_one_on_empty_ledger(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    assert _allocate_number(_config("a"), ledger, "2026-07", None) == (1, 2026, "FS/1/2026")


def test_allocate_number_honours_explicit_seq(tmp_path):
    """--seq zasiewa licznik po ręcznie wystawionych fakturach — ledger nie może go nadpisać."""
    ledger = Ledger(tmp_path / "ledger.json")
    assert _allocate_number(_config("a"), ledger, "2026-07", 9) == (9, 2026, "FS/9/2026")


def test_allocate_number_counters_are_per_environment(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.record("test", "a", "2026-06", 5, 2026, {"number": "FS/5/2026"})

    prod = _config("a", environment="prod")
    assert _allocate_number(prod, ledger, "2026-07", None)[0] == 1


# --- _template_ref -----------------------------------------------------------------


def test_template_ref_is_relative_inside_root(tmp_path):
    """config.py składa ścieżkę jako `root / template`, więc wpis musi być względny."""
    target = tmp_path / "templates" / "klient.xml"
    assert _template_ref(target, tmp_path) == "templates/klient.xml"


def test_template_ref_falls_back_to_absolute_outside_root(tmp_path):
    outside = tmp_path / "gdzie-indziej" / "klient.xml"
    root = tmp_path / "root"
    root.mkdir()
    assert _template_ref(outside, root) == str(outside)


# --- _invoice_dir ------------------------------------------------------------------


def test_invoice_dir_sanitizes_number_into_one_segment(tmp_path):
    """Numer faktury zawiera / — bez podmiany zrobiłby zagnieżdżone katalogi."""
    invoice = Invoice(
        month="2026-07",
        number="FS/8/2026",
        issue_date=date(2026, 7, 31),
        sale_date=date(2026, 7, 31),
        payment_due=date(2026, 8, 15),
        line_nets=(Decimal("1000"),),
        net=Decimal("1000"),
        vat=Decimal("230"),
        gross=Decimal("1230"),
        xml=b"<x/>",
    )
    config = _config("klient", out_dir=tmp_path)

    target = _invoice_dir(config, config.profiles["klient"], invoice)

    assert target == tmp_path / "test" / "klient" / "2026-07_FS-8-2026"
    assert target.relative_to(tmp_path).parts == ("test", "klient", "2026-07_FS-8-2026")


# --- powierzchnia komend -----------------------------------------------------------


def test_help_lists_every_command():
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in COMMANDS:
        assert command in result.output


@pytest.mark.parametrize("command", COMMANDS)
def test_command_help_works(command):
    """Każda komenda musi dać się opisać bez wczytywania configu."""
    result = CliRunner().invoke(app, [command, "--help"])

    assert result.exit_code == 0, result.output
    assert result.exception is None


def test_no_args_shows_help_not_traceback():
    result = CliRunner().invoke(app, [])

    assert "Usage" in result.output
    assert result.exit_code != 0  # no_args_is_help=True zwraca kod użycia
