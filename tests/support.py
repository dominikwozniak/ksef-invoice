"""Stałe i fabryki katalogów współdzielone przez testy.

Osobny moduł, a nie conftest, żeby testy importowały to normalnym importem
zamiast przez fixture'y — fabryki nie potrzebują cyklu życia pytesta.
"""

from __future__ import annotations

import shutil
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from ksef_invoice.config import Profile
from ksef_invoice.invoice import build_invoice
from ksef_invoice.onboard import append_profile, create_config, create_env, profile_block

REPO_ROOT = Path(__file__).resolve().parents[1]

# Syntetyczny NIP z poprawną sumą kontrolną — dane testowe, nie należy do nikogo z projektu.
# Musi się różnić od 1111111111 z template.example.xml (test rozjazdu NIP-u sprzedawcy)
# i nie może być powtórzoną cyfrą (test braku ostrzeżenia o NIP-ie-atrapie).
VALID_NIP = "5252000019"

# NIP zgodny z Podmiot1 w template.example.xml — profil na nim przechodzi check_seller_nip.
EXAMPLE_NIP = "1111111111"

TODAY = date(2026, 7, 31)


def make_root(tmp_path: Path) -> Path:
    """Katalog roboczy z szablonem-atrapą, na który mogą wskazywać profile w testach."""
    (tmp_path / "examples").mkdir(exist_ok=True)
    shutil.copy(
        REPO_ROOT / "examples" / "template.example.xml", tmp_path / "examples" / "template.example.xml"
    )
    return tmp_path


def write_concrete_invoice(tmp_path: Path) -> Path:
    """Zapisuje konkretną fakturę FA(3) (bez placeholderów) i zwraca ścieżkę — imitację
    XML-a pobranego z Aplikacji Podatnika, czyli prawidłowe wejście dla `templatize`.

    Uwaga: tests/fixtures/two_lines.xml jest już *szablonem* z {{placeholderami}}, więc
    nie przechodzi walidacji XSD i nie nadaje się na wejście templatize.
    """
    profile = Profile(
        name="wzor",
        template_path=REPO_ROOT / "examples" / "template.example.xml",
        vat_rate="23",
        issue_day="today",
        due_days=14,
        due_day_next_month=None,
    )
    invoice = build_invoice(
        "2026-07",
        [Decimal("15000")],
        profile,
        number="FS/9/2026",
        generated_at=datetime(2026, 7, 31, 10, 0, tzinfo=UTC),
        today=date(2026, 7, 31),
    )
    target = tmp_path / "faktura-z-ksef.xml"
    target.write_bytes(invoice.xml)
    return target


def healthy_root(tmp_path: Path) -> Path:
    """Katalog, na którym `doctor` przechodzi bez FAIL — jeden działający profil."""
    root = make_root(tmp_path)
    create_config(root, EXAMPLE_NIP)
    create_env(root)
    append_profile(
        root, "demo", profile_block("demo", "examples/template.example.xml", "23", due_day_next_month=15)
    )
    return root
