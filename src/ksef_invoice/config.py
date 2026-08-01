"""Konfiguracja: config.toml (profile faktur) + .env (środowisko i token)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

ENVIRONMENTS = ("test", "demo", "prod")


@dataclass(frozen=True)
class Profile:
    name: str
    template_path: Path
    vat_rate: str  # procent ("23") albo "np" — bez VAT (np. odwrotne obciążenie UE)
    issue_day: str | int
    # Dokładnie jedna reguła terminu płatności:
    due_days: int | None  # termin = data wystawienia + N dni
    due_day_next_month: int | None  # termin = D. dzień miesiąca po miesiącu rozliczeniowym (P_6)


@dataclass(frozen=True)
class Config:
    nip: str
    number_format: str
    profiles: dict[str, Profile]
    environment: str
    ksef_token: str | None
    out_dir: Path


def _load_dotenv(path: Path) -> None:
    """Minimalny parser .env — tylko KEY=VALUE, bez nadpisywania istniejących zmiennych."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _resolve_due_rule(name: str, profile_data: dict, data: dict) -> tuple[int | None, int | None]:
    """Dokładnie jedna reguła terminu płatności; klucz w profilu wygrywa z domyślnym."""
    source = profile_data if ("due_days" in profile_data or "due_day_next_month" in profile_data) else data
    due_days = source.get("due_days")
    due_day_next_month = source.get("due_day_next_month")
    if due_days is not None and due_day_next_month is not None:
        raise ValueError(
            f"config.toml: profil {name!r} ma jednocześnie due_days i due_day_next_month — wybierz jedno."
        )
    if due_days is None and due_day_next_month is None:
        due_days = 14
    return (
        int(due_days) if due_days is not None else None,
        int(due_day_next_month) if due_day_next_month is not None else None,
    )


def load_config(root: Path = PROJECT_ROOT) -> Config:
    _load_dotenv(root / ".env")

    config_path = root / "config.toml"
    if not config_path.exists():
        raise FileNotFoundError(
            f"Brak {config_path}. Utwórz go komendą `ksef-invoice init --nip <NIP>` "
            "(albo skopiuj examples/config.example.toml i uzupełnij ręcznie)."
        )
    data = tomllib.loads(config_path.read_text())

    profiles_data = data.get("profiles")
    if not profiles_data:
        raise ValueError("config.toml: brak sekcji [profiles.<nazwa>] — zdefiniuj co najmniej jeden profil.")

    profiles: dict[str, Profile] = {}
    for name, profile_data in profiles_data.items():
        if "template" not in profile_data:
            raise ValueError(f"config.toml: profil {name!r} nie ma pola template.")
        template_path = root / profile_data["template"]
        if not template_path.exists():
            raise FileNotFoundError(f"Profil {name!r}: brak szablonu {template_path}.")
        due_days, due_day_next_month = _resolve_due_rule(name, profile_data, data)
        profiles[name] = Profile(
            name=name,
            template_path=template_path,
            vat_rate=str(profile_data.get("vat_rate", data.get("vat_rate", "23"))),
            issue_day=profile_data.get("issue_day", data.get("issue_day", "today")),
            due_days=due_days,
            due_day_next_month=due_day_next_month,
        )

    environment = os.environ.get("KSEF_ENV", "test").lower()
    if environment not in ENVIRONMENTS:
        raise ValueError(f"KSEF_ENV={environment!r} — dozwolone: {', '.join(ENVIRONMENTS)}")

    return Config(
        nip=str(data["nip"]),
        number_format=data.get("number_format", "FS/{seq}/{year}"),
        profiles=profiles,
        environment=environment,
        ksef_token=os.environ.get("KSEF_TOKEN") or None,
        out_dir=root / "out",
    )
