"""Trzy bariery bezpieczeństwa dla całej suity.

Wszystkie są autouse, bo chodzi w nich o to, żeby test **nie mógł** dotknąć produkcji:

* `clean_ksef_env` — token z shella dewelopera nie wchodzi do `Config.ksef_token`,
  a `KSEF_*` nie przecieka między testami (`_load_dotenv` używa `os.environ.setdefault`,
  więc każdy `load_config()` zostawia po sobie `KSEF_ENV` w środowisku procesu).
* `_no_send` — nawet środowisko TEST tworzy prawdziwe faktury w KSeF, a testowe NIP-y
  bywają „zużyte" przez innych integratorów (kod 440). Żaden test nie ma prawa wysyłać.
* `_guard_real_state` — ostatnia linia obrony: prawdziwy `config.toml`, `.env` i
  `out/ledger.json` muszą być po sesji nietknięte. Stan mieszka w katalogu projektu,
  a `load_config()` bez argumentu czyta go wprost — test, który zapomni o stubie,
  trafia w produkcyjny ledger. Ledger jest źródłem prawdy dla numeracji faktur, więc
  jego przypadkowa modyfikacja to problem prawny, nie testowy.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Pliki, których żaden test nie ma prawa ruszyć.
_GUARDED = (
    REPO_ROOT / "config.toml",
    REPO_ROOT / ".env",
    REPO_ROOT / "out" / "ledger.json",
)


@pytest.fixture(autouse=True)
def clean_ksef_env():
    """Zdejmuje wszystkie KSEF_* na czas testu i przywraca dokładny stan po nim."""
    saved = {key: value for key, value in os.environ.items() if key.startswith("KSEF_")}
    for key in saved:
        del os.environ[key]
    yield
    for key in [key for key in os.environ if key.startswith("KSEF_")]:
        del os.environ[key]
    os.environ.update(saved)


@pytest.fixture(autouse=True)
def _no_send(monkeypatch):
    """Blokuje wysyłkę do KSeF. Test, który jej potrzebuje, nadpisuje to własnym stubem."""

    def _refuse(*args, **kwargs):
        raise AssertionError("Test próbował wysłać fakturę do KSeF — to nigdy nie jest zamierzone.")

    # Patchujemy zaimportowaną nazwę w cli (`from .send import send_invoice` wiąże ją
    # przy imporcie) *i* źródło, żeby żaden przyszły importer nie obszedł bariery.
    monkeypatch.setattr("ksef_invoice.send.send_invoice", _refuse)
    monkeypatch.setattr("ksef_invoice.cli.send_invoice", _refuse)


def _fingerprint() -> dict[Path, tuple[bool, int, int]]:
    marks = {}
    for path in _GUARDED:
        try:
            stat = path.stat()
            marks[path] = (True, stat.st_mtime_ns, stat.st_size)
        except OSError:
            marks[path] = (False, 0, 0)
    return marks


@pytest.fixture(scope="session", autouse=True)
def _guard_real_state():
    before = _fingerprint()
    yield
    after = _fingerprint()
    touched = [str(path) for path in _GUARDED if before[path] != after[path]]
    assert not touched, "Suita zmodyfikowała prawdziwy stan: " + ", ".join(touched)
