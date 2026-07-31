"""Sprzężenie skilla ksef-onboard z komunikatami CLI.

Tabela troubleshootingu w SKILL.md dopasowuje się po **treści** komunikatów błędów, więc
przeredagowanie któregokolwiek z nich cicho psuje skilla: komendy dalej działają, testy
dalej są zielone, a agent przestaje rozpoznawać sytuację i doradza bez sensu.

Ten test nie broni konkretnego brzmienia — broni istnienia fragmentu, na który skill liczy.
Zmieniasz komunikat: zaktualizuj skilla w tym samym commicie i popraw fragment tutaj.
"""

from __future__ import annotations

import pytest
from support import REPO_ROOT

SKILL = REPO_ROOT / ".claude" / "skills" / "ksef-onboard" / "SKILL.md"
SRC = REPO_ROOT / "src" / "ksef_invoice"

# Fragment komunikatu → moduł, który go produkuje.
COUPLED_MESSAGES = [
    ("Brak {config_path}", "config.py"),
    ("uruchom najpierw `ksef-invoice init", "onboard.py"),
    ("już jest w ", "onboard.py"),
    ("ma niepoprawną sumę kontrolną", "onboard.py"),
    ("Nie udało się przetworzyć", "cli.py"),
    ("brak placeholderów", "doctor.py"),
    ("różni się od nip w config.toml", "cli.py"),
    ('"migracja"', "doctor.py"),
    # Ostrzeżenia templatize, które skill ma czytać „na głos" (krok 4).
    ("ilość P_8B", "templatize.py"),
    ("Wykryto dodatkowe stawki VAT", "templatize.py"),
    ("Nie udało się odczytać stawki VAT", "templatize.py"),
    ("Brak pola", "templatize.py"),
]


@pytest.mark.parametrize(("fragment", "module"), COUPLED_MESSAGES)
def test_message_the_skill_matches_on_still_exists(fragment, module):
    assert fragment in (SRC / module).read_text(encoding="utf-8"), (
        f"{module} nie zawiera już {fragment!r} — SKILL.md dopasowuje się po tym tekście, "
        "więc zaktualizuj skilla w tym samym commicie."
    )


def test_skill_does_not_tell_users_to_run_from_a_checkout():
    """Po przejściu na `uv tool install` `uv run ksef-invoice` nie zadziała u kogoś,
    kto nie ma klonu repo."""
    assert "uv run ksef-invoice" not in SKILL.read_text(encoding="utf-8")


def test_skill_keeps_the_send_boundary():
    """Granica nr 1: skill nigdy nie wysyła faktur. Faktury w KSeF są nieusuwalne."""
    text = SKILL.read_text(encoding="utf-8")

    assert "Nie uruchamiaj `send`" in text
    assert "KSEF_TOKEN" in text
