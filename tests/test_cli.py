"""Testy warstwy CLI — na razie tylko to, co dotyka parsowania wejścia użytkownika."""

from pathlib import Path

import pytest
import typer

from ksef_invoice.cli import _allocate_number, _parse_nets
from ksef_invoice.config import Config
from ksef_invoice.ledger import Ledger


def make_config() -> Config:
    return Config(
        nip="1111111111",
        number_format="FS/{seq}/{year}",
        profiles={},
        environment="test",
        ksef_token=None,
        out_dir=Path("out"),
    )


@pytest.mark.parametrize("month", ["07-2026", "2026/07", "lipiec", "2026-13"])
def test_bad_month_is_a_parameter_error_not_a_traceback(tmp_path, month):
    """_allocate_number biegnie przed build_invoice, więc to on musi złapać zły --month."""
    with pytest.raises(typer.BadParameter, match="RRRR-MM"):
        _allocate_number(make_config(), Ledger(tmp_path / "ledger.json"), month, 1)


def test_good_month_allocates_number(tmp_path):
    seq, year, number = _allocate_number(make_config(), Ledger(tmp_path / "ledger.json"), "2026-07", 40)
    assert (seq, year, number) == (40, 2026, "FS/40/2026")


@pytest.mark.parametrize("net", ["nie-liczba", "0", "-5"])
def test_bad_net_is_a_parameter_error(net):
    with pytest.raises(typer.BadParameter):
        _parse_nets([net])


def test_net_accepts_comma_decimal():
    assert [str(value) for value in _parse_nets(["1000,50", "500"])] == ["1000.50", "500"]
