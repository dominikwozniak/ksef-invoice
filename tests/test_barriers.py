"""Testy barier z conftest.py.

Bariera, która cicho przestała działać, jest groźniejsza niż jej brak — te testy
sprawdzają, że nadal działają. Jeśli któryś padnie, reszta suity przestała być
bezpieczna wobec produkcji, niezależnie od tego, że świeci na zielono.
"""

from __future__ import annotations

import os

import pytest

import ksef_invoice.cli as cli_module
import ksef_invoice.send as send_module


def test_ksef_env_is_stripped_inside_tests():
    """Token produkcyjny z shella dewelopera nie ma prawa być widoczny w teście.

    KSEF_INVOICE_HOME jest wyjątkiem — ustawia go celowo fixture isolated_home.
    """
    leaked = [key for key in os.environ if key.startswith("KSEF_") and key != "KSEF_INVOICE_HOME"]
    assert not leaked, f"KSEF_* przeciekło do testu: {leaked}"


def test_home_never_points_at_the_real_one(isolated_home, tmp_path):
    """Komenda bez --home musi trafiać w tmp, nie w produkcyjne ~/.ksef-invoice."""
    from pathlib import Path

    assert os.environ["KSEF_INVOICE_HOME"] == str(isolated_home)
    assert tmp_path in isolated_home.parents
    assert isolated_home != Path.home() / ".ksef-invoice"


@pytest.mark.parametrize("module", [cli_module, send_module])
def test_send_invoice_is_blocked(module):
    with pytest.raises(AssertionError, match="Test próbował wysłać fakturę"):
        module.send_invoice(b"<x/>", None)


def test_load_config_does_not_leak_env_to_next_test(tmp_path):
    """`_load_dotenv` robi os.environ.setdefault, więc bez bariery KSEF_ENV zostawałoby
    w środowisku procesu i cichcem sterowało kolejnymi testami."""
    from support import healthy_root

    from ksef_invoice.config import load_config

    config = load_config(healthy_root(tmp_path))

    assert config.environment == "test"  # z .env katalogu tmp, nie z shella
    assert os.environ.get("KSEF_ENV") == "test"  # setdefault faktycznie zabrudził środowisko
    # ...a sprzątnie to fixture clean_ksef_env — czego dowodzi test_ksef_env_is_stripped_inside_tests
    # przy uruchomieniu całej suity w jednym procesie.
