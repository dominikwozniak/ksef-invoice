"""Rejestr wystawionych faktur: ochrona przed duplikatem + wspólny licznik roczny numeracji.

Struktura pliku (licznik i wpisy per środowisko — testy nie zużywają numerów produkcyjnych):

    {
      "test": {
        "sequences": { "2026": 2 },
        "profiles": { "klient-a": { "2026-07": { ...meta } } }
      }
    }
"""

from __future__ import annotations

import json
from pathlib import Path


class Ledger:
    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {}

    def get(self, environment: str, profile: str, month: str) -> dict | None:
        return self._load().get(environment, {}).get("profiles", {}).get(profile, {}).get(month)

    def entries(self, environment: str) -> list[tuple[str, str, dict]]:
        """(profil, miesiąc, wpis) dla wszystkich faktur w środowisku, chronologicznie.

        Miesiąc bierzemy z klucza, nie z wpisu — klucz jest tu autorytatywny, a starsze
        wpisy pochodzą z wcześniejszej wersji `meta` i nie mają wszystkich pól.
        """
        profiles = self._load().get(environment, {}).get("profiles", {})
        rows = [
            (profile, month, entry) for profile, months in profiles.items() for month, entry in months.items()
        ]
        return sorted(rows, key=lambda row: (row[1], row[0]))

    def next_seq(self, environment: str, year: int) -> int:
        """Kolejny wolny numer w rocznej sekwencji (bez rezerwacji)."""
        sequences = self._load().get(environment, {}).get("sequences", {})
        return int(sequences.get(str(year), 0)) + 1

    def year_started(self, environment: str, year: int) -> bool:
        """Czy w danym roku/środowisku zapisano już jakikolwiek numer (rozróżnia pierwszą wysyłkę)."""
        sequences = self._load().get(environment, {}).get("sequences", {})
        return str(year) in sequences

    def number_exists(self, environment: str, number: str) -> tuple[str, str] | None:
        """(profil, miesiąc) faktury o danym numerze w tym środowisku, albo None — ochrona
        przed dwukrotnym użyciem tego samego numeru (np. --seq podany obu fakturom naraz)."""
        profiles = self._load().get(environment, {}).get("profiles", {})
        for profile, months in profiles.items():
            for month, entry in months.items():
                if entry.get("number") == number:
                    return profile, month
        return None

    def record(self, environment: str, profile: str, month: str, seq: int, year: int, entry: dict) -> None:
        data = self._load()
        env_data = data.setdefault(environment, {})
        env_data.setdefault("profiles", {}).setdefault(profile, {})[month] = entry
        sequences = env_data.setdefault("sequences", {})
        sequences[str(year)] = max(int(sequences.get(str(year), 0)), seq)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
