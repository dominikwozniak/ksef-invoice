"""Onboarding: utworzenie config.toml/.env i dopisanie profilu bez ręcznej edycji plików.

Profile dopisujemy jako tekst, nie przez bibliotekę TOML — `tomllib` jest read-only,
a blok profilu to cztery linie, więc dopisanie zachowuje komentarze użytkownika bez
dodatkowej zależności.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

# Wagi sumy kontrolnej NIP (9 pierwszych cyfr; dziesiąta jest cyfrą kontrolną).
NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)

CONFIG_TEMPLATE = """\
# Wygenerowane przez `ksef-invoice init`. Plik jest w .gitignore — trzymaj go lokalnie.

# NIP sprzedawcy — kontekst uwierzytelnienia w KSeF (wspólny dla wszystkich profili).
# Musi zgadzać się z NIP-em w Podmiot1 każdego szablonu, inaczej KSeF odrzuci fakturę.
nip = "{nip}"

# Wspólna numeracja: roczna sekwencja dla wszystkich profili.
# Tokeny: {{seq}} (licznik), {{year}} (2026), {{month}} (7), {{month02}} (07).
# Licznik trzyma out/ledger.json; pierwszą produkcyjną wysyłkę w roku zasiej flagą --seq.
number_format = "FS/{{seq}}/{{year}}"

# Dzień wystawienia (P_1): "today" | "last" (ostatni dzień miesiąca) | numer dnia.
# "today" jest bezpieczne — KSeF odrzuca faktury z datą wystawienia w przyszłości.
issue_day = "today"

# Profile dopisze templatize, jeden na powtarzalną fakturę:
#   uv run ksef-invoice templatize <faktura.xml> --name <profil> --write-config --due-days 14
"""

PROFILE_TEMPLATE = """\

# Profil dopisany przez `templatize --write-config`.
[profiles.{name}]
template = "{template}"
vat_rate = "{vat_rate}"
{due_rule}
"""


def normalize_nip(raw: str) -> str:
    """NIP bez separatorów i prefiksu kraju (dozwolone są zapisy typu 123-456-78-90, PL1234567890)."""
    cleaned = raw.strip().upper().removeprefix("PL")
    return "".join(character for character in cleaned if not character.isspace() and character != "-")


def nip_checksum_ok(nip: str) -> bool:
    """Suma kontrolna NIP; reszta 10 oznacza NIP nieprawidłowy (taki nie jest nadawany)."""
    if len(nip) != 10 or not nip.isdigit():
        return False
    total = sum(int(digit) * weight for digit, weight in zip(nip[:9], NIP_WEIGHTS, strict=True))
    return total % 11 == int(nip[9])


def validate_nip(raw: str) -> str:
    """Znormalizowany NIP albo ValueError z czytelnym powodem."""
    nip = normalize_nip(raw)
    if len(nip) != 10 or not nip.isdigit():
        raise ValueError(f"NIP {raw!r} — oczekiwane 10 cyfr (dozwolone separatory i prefiks PL).")
    if not nip_checksum_ok(nip):
        raise ValueError(f"NIP {nip} ma niepoprawną sumę kontrolną — sprawdź, czy nie ma literówki.")
    return nip


def suspicious_nip_warning(nip: str) -> str | None:
    """Ostrzeżenie dla NIP-ów-atrap. Uwaga: część z nich (np. 1111111111) ma poprawną
    sumę kontrolną, więc sama walidacja ich nie wyłapie — a na środowisku testowym KSeF
    bywają „zużyte" przez innych integratorów i faktura wraca z kodem 440 (duplikat)."""
    if len(set(nip)) == 1:
        return (
            f"NIP {nip} to powtórzona cyfra — na środowisku testowym KSeF takie NIP-y są "
            "współdzielone przez integratorów i Twoja faktura może wrócić z kodem 440 (duplikat). "
            "Lepiej użyć losowego NIP-u z poprawną sumą kontrolną."
        )
    return None


def existing_profiles(config_path: Path) -> set[str]:
    """Nazwy profili już zapisanych w config.toml (pusty zbiór, gdy pliku nie ma)."""
    if not config_path.exists():
        return set()
    return set(tomllib.loads(config_path.read_text(encoding="utf-8")).get("profiles", {}))


def config_nip(config_path: Path) -> str | None:
    """NIP z config.toml, czytany bez load_config — ten wymaga już istniejących profili."""
    if not config_path.exists():
        return None
    value = tomllib.loads(config_path.read_text(encoding="utf-8")).get("nip")
    return str(value) if value is not None else None


def create_config(root: Path, nip: str, *, force: bool = False) -> Path:
    """Zapisuje config.toml bez profili. Nie nadpisuje istniejącego pliku bez force."""
    target = root / "config.toml"
    if target.exists() and not force:
        raise FileExistsError(
            f"{target} już istnieje — nie nadpisuję (zawiera Twoje dane). "
            "Użyj --force, jeśli chcesz zacząć od zera."
        )
    target.write_text(CONFIG_TEMPLATE.format(nip=validate_nip(nip)), encoding="utf-8")
    return target


def create_env(root: Path, *, force: bool = False) -> Path:
    """Zapisuje .env na podstawie examples/.env.example. Nie nadpisuje bez force —
    w istniejącym pliku może siedzieć produkcyjny token."""
    target = root / ".env"
    if target.exists() and not force:
        raise FileExistsError(
            f"{target} już istnieje — nie nadpisuję (może zawierać token KSeF). "
            "Użyj --force, jeśli wiesz co robisz."
        )
    example = root / "examples" / ".env.example"
    if not example.exists():
        raise FileNotFoundError(f"Brak wzorca {example} — nie mam z czego utworzyć .env.")
    target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def profile_block(
    name: str,
    template: str,
    vat_rate: str,
    *,
    due_days: int | None = None,
    due_day_next_month: int | None = None,
) -> str:
    """Blok [profiles.<name>] gotowy do dopisania; dokładnie jedna reguła terminu płatności."""
    if (due_days is None) == (due_day_next_month is None):
        raise ValueError("Podaj dokładnie jedną regułę terminu: due_days albo due_day_next_month.")
    if due_days is not None:
        due_rule = f"due_days = {due_days}                # termin = data wystawienia + N dni"
    else:
        due_rule = (
            f"due_day_next_month = {due_day_next_month}      "
            "# termin = D. dzień miesiąca po miesiącu rozliczeniowym"
        )
    return PROFILE_TEMPLATE.format(name=name, template=template, vat_rate=vat_rate, due_rule=due_rule)


def append_profile(root: Path, name: str, block: str, *, force: bool = False) -> Path:
    """Dopisuje blok profilu do config.toml. Wymaga istniejącego configu i wolnej nazwy profilu."""
    target = root / "config.toml"
    if not target.exists():
        raise FileNotFoundError(f"Brak {target} — uruchom najpierw `ksef-invoice init --nip <NIP>`.")
    if name in existing_profiles(target) and not force:
        raise ValueError(
            f"Profil {name!r} już jest w {target.name} — nie dopisuję drugiego. "
            "Wybierz inną nazwę (--name) albo użyj --force."
        )
    current = target.read_text(encoding="utf-8")
    separator = "" if current.endswith("\n") else "\n"
    target.write_text(current + separator + block, encoding="utf-8")
    return target
