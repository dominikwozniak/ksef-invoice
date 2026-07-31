"""Warstwa CLI: helpery i powierzchnia komend.

Helpery testujemy wprost, bo to one decydują o numerze faktury i o tym, gdzie
ląduje szablon — a przez CliRunner widać tylko sformatowany tekst.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from importlib.metadata import version as package_version
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import ksef_invoice.cli as cli
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


def test_help_keeps_app_description_after_adding_callback():
    """@app.callback() bez docstringa nie może przesłonić help= z Typer()."""
    result = CliRunner().invoke(app, ["--help"])

    assert "Wystawianie powtarzalnych faktur" in result.output


def test_version_matches_package_metadata():
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == package_version("ksef-invoice")


# --- kontrakt maszynowy doctor --json ---------------------------------------------


def test_doctor_json_is_machine_readable():
    """Hermetycznie: sprawdzamy kształt i spójność, nie treść zależną od środowiska."""
    result = CliRunner().invoke(app, ["doctor", "--json"])

    payload = json.loads(result.stdout)
    assert set(payload) == {"home", "checks", "failed"}
    assert payload["failed"] == sum(1 for check in payload["checks"] if check["status"] == "fail")
    assert result.exit_code == (1 if payload["failed"] else 0)
    for check in payload["checks"]:
        assert set(check) == {"name", "status", "detail"}
        assert check["status"] in {"ok", "warn", "fail"}


def test_doctor_json_writes_nothing_to_stderr():
    """`doctor --json | jq` nie może się psuć od ostrzeżenia wypadającego w środku."""
    result = CliRunner().invoke(app, ["doctor", "--json"])

    assert result.stderr == ""


# --- main(): handler, który zamienia oczekiwane błędy w jedną linię ----------------


def test_main_reports_expected_errors_as_one_line(monkeypatch, capsys):
    message = "Brak /nie/ma/config.toml. Utwórz go komendą `ksef-invoice init --nip <NIP>`."

    def _raise():
        raise FileNotFoundError(message)

    monkeypatch.setattr(cli, "app", _raise)

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    captured = capsys.readouterr()
    assert exit_info.value.code == 1
    assert captured.out == ""
    assert "Traceback" not in captured.err
    # Ścieżka musi zostać w jednej linii — od tego zależy grep i skill ksef-onboard.
    assert "/nie/ma/config.toml" in captured.err.splitlines()[0]


def test_main_does_not_swallow_unexpected_errors(monkeypatch):
    """Handler ma być wąski: prawdziwy bug musi nadal wyjść z tracebackiem."""

    def _bug():
        raise RuntimeError("prawdziwy bug")

    monkeypatch.setattr(cli, "app", _bug)

    with pytest.raises(RuntimeError, match="prawdziwy bug"):
        cli.main()


# --- rozwiązywanie katalogu roboczego ----------------------------------------------


def _run(args: list[str], home: Path | None = None, **kwargs):
    """CliRunner z jawnym --home, żeby żaden test nie trafił w prawdziwy katalog."""
    prefix = ["--home", str(home)] if home is not None else []
    return CliRunner().invoke(app, prefix + args, **kwargs)


def test_doctor_reports_resolved_home_on_empty_dir(tmp_path):
    """Doświadczenie świeżej instalacji: mówimy, gdzie szukamy, i wychodzimy z 1."""
    result = _run(["doctor", "--json"], home=tmp_path)

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["home"] == str(tmp_path)
    assert payload["checks"][0]["name"] == "config.toml"


def test_doctor_prints_home_outside_the_table(tmp_path):
    """Kolumna rich-a obcina długie ścieżki wielokropkiem, więc katalog idzie osobną
    linią — inaczej użytkownik nie może odczytać ani skopiować ścieżki."""
    result = _run(["doctor"], home=tmp_path)

    first_line = result.stdout.splitlines()[0]
    assert first_line.startswith("Katalog:")
    assert str(tmp_path) in first_line


def test_home_flag_beats_env_var(tmp_path, monkeypatch):
    """Precedencja click-a: flaga > KSEF_INVOICE_HOME. To dźwignia rollbacku po migracji."""
    from_env = tmp_path / "z-env"
    from_flag = tmp_path / "z-flagi"
    from_env.mkdir()
    from_flag.mkdir()
    monkeypatch.setenv("KSEF_INVOICE_HOME", str(from_env))

    payload = json.loads(_run(["doctor", "--json"], home=from_flag).stdout)

    assert payload["home"] == str(from_flag)


def test_default_home_is_one_per_user_directory():
    """Świadomie NIE szukanie config.toml w górę od cwd: numer faktury to roczna sekwencja
    z out/ledger.json i nie może zależeć od katalogu, w którym stoi shell."""
    assert cli.DEFAULT_HOME == Path.home() / ".ksef-invoice"


def test_help_documents_default_home_and_env_var():
    result = CliRunner().invoke(app, ["--help"])

    assert "KSEF_INVOICE_HOME" in result.output
    assert ".ksef-invoice" in result.output


def test_doctor_hints_migration_when_state_sits_in_cwd(tmp_path, monkeypatch):
    """Po przestawieniu defaultu użytkownik ze stanem w klonie repo musi dostać przepis,
    a nie samo „brak config.toml"."""
    legacy = tmp_path / "stary-klon"
    legacy.mkdir()
    (legacy / "config.toml").write_text('nip = "1111111111"\n')
    monkeypatch.chdir(legacy)

    payload = json.loads(_run(["doctor", "--json"], home=tmp_path / "nowy").stdout)

    hint = next(check for check in payload["checks"] if check["name"] == "migracja")
    assert "cp -a" in hint["detail"]
    assert str(legacy) in hint["detail"]
    assert "cp, nie mv" in hint["detail"]


def test_doctor_does_not_hint_migration_on_healthy_home(tmp_path):
    home = _ready_home(tmp_path)

    payload = json.loads(_run(["doctor", "--json"], home=home).stdout)

    assert "migracja" not in [check["name"] for check in payload["checks"]]


def test_env_var_is_used_when_flag_absent(tmp_path, monkeypatch):
    home = tmp_path / "z-env"
    home.mkdir()
    monkeypatch.setenv("KSEF_INVOICE_HOME", str(home))

    payload = json.loads(CliRunner().invoke(app, ["doctor", "--json"]).stdout)

    assert payload["home"] == str(home)


# --- init --------------------------------------------------------------------------


def test_init_creates_home_that_does_not_exist_yet(tmp_path):
    """Regresja: create_config/create_env robiły write_text bez mkdir rodzica, więc
    pierwszy init na czystej maszynie umierał na FileNotFoundError."""
    home = tmp_path / "jeszcze-nie-ma"

    result = _run(["init", "--nip", "5252000019"], home=home)

    assert result.exit_code == 0, result.output
    assert (home / "config.toml").exists()
    assert (home / ".env").exists()


def test_init_makes_home_private_and_env_unreadable_for_others(tmp_path):
    """W .env siedzi produkcyjny token KSeF — konwencja ~/.ssh, nie domyślne 0644."""
    home = tmp_path / "nowy"

    _run(["init", "--nip", "5252000019"], home=home)

    assert home.stat().st_mode & 0o777 == 0o700
    assert (home / ".env").stat().st_mode & 0o777 == 0o600


def test_init_refuses_to_clobber_existing_env(tmp_path):
    home = tmp_path / "istnieje"
    _run(["init", "--nip", "5252000019"], home=home)
    (home / ".env").write_text("KSEF_TOKEN=produkcyjny-sekret\n")

    result = _run(["init", "--nip", "5252000019"], home=home)

    assert result.exit_code == 1
    assert (home / ".env").read_text() == "KSEF_TOKEN=produkcyjny-sekret\n"


def test_init_rejects_bad_nip_without_creating_home(tmp_path):
    home = tmp_path / "nie-powinien-powstac"

    result = _run(["init", "--nip", "1234567890"], home=home)

    assert result.exit_code == 1
    assert not home.exists()


# --- templatize --write-config -----------------------------------------------------


def test_templatize_writes_template_into_home_not_cwd(tmp_path, monkeypatch):
    """Regresja najważniejsza dla tego kroku: szablon zapisywany był względem cwd, a
    config.py składa go jako `home / template`. Komenda raportowała sukces i zostawiała
    profil, którego load_config nie znajdzie. Asercja na load_config, nie na tekst."""
    from support import EXAMPLE_NIP, write_concrete_invoice

    from ksef_invoice.config import load_config

    home = tmp_path / "home"
    elsewhere = tmp_path / "gdzie-indziej"
    elsewhere.mkdir()
    faktura = write_concrete_invoice(tmp_path)
    monkeypatch.chdir(elsewhere)  # cwd celowo różne od home

    _run(["init", "--nip", EXAMPLE_NIP], home=home)
    result = _run(
        ["templatize", str(faktura), "--name", "klient", "--write-config", "--due-days", "14"],
        home=home,
    )

    assert result.exit_code == 0, result.output
    assert (home / "templates" / "klient.xml").exists()
    assert not (elsewhere / "templates").exists()

    # Dowód właściwy: profil da się wczytać, czyli ścieżka w config.toml jest rozwiązywalna.
    profile = load_config(home).profiles["klient"]
    assert profile.template_path == home / "templates" / "klient.xml"
    assert profile.due_days == 14


def test_templatize_then_doctor_passes(tmp_path, monkeypatch):
    """Pełny onboarding przez CLI: init → templatize → doctor bez FAIL."""
    from support import EXAMPLE_NIP, write_concrete_invoice

    home = tmp_path / "home"
    faktura = write_concrete_invoice(tmp_path)
    monkeypatch.chdir(tmp_path)

    _run(["init", "--nip", EXAMPLE_NIP], home=home)
    _run(
        ["templatize", str(faktura), "--name", "klient", "--write-config", "--due-days", "14"],
        home=home,
    )
    payload = json.loads(_run(["doctor", "--json"], home=home).stdout)

    failed = [check for check in payload["checks"] if check["status"] == "fail"]
    assert not failed, failed
    assert payload["home"] == str(home)


# --- guardy send: chronią numerację faktur, dotąd bez żadnego testu -----------------


def _assert_refused_by_guard(result) -> None:
    """Kod 1 musi pochodzić z guarda, a nie z próby wysyłki.

    `send` łapie z send_invoice każdy wyjątek i też kończy kodem 1, więc ani kod wyjścia,
    ani typ result.exception nie rozróżniają tych dwóch ścieżek. Dowodem jest brak
    komunikatu o nieudanej wysyłce — kontrolę pozytywną robi
    test_force_bypasses_guard_and_reaches_the_network_barrier.
    """
    assert result.exit_code == 1, result.output
    assert "Wysyłka nie powiodła się" not in result.stderr, result.stderr


def _ready_home(tmp_path: Path) -> Path:
    """Home po pełnym onboardingu przez CLI: config.toml z profilem `klient` (1 pozycja)
    i szablonem w templates/."""
    from support import EXAMPLE_NIP, write_concrete_invoice

    home = tmp_path / "home"
    faktura = write_concrete_invoice(tmp_path)
    _run(["init", "--nip", EXAMPLE_NIP], home=home)
    _run(
        ["templatize", str(faktura), "--name", "klient", "--write-config", "--due-days", "14"],
        home=home,
    )
    return home


def test_send_refuses_duplicate_month_before_touching_network(tmp_path):
    home = _ready_home(tmp_path)
    Ledger(home / "out" / "ledger.json").record(
        "test", "klient", "2026-07", 1, 2026, {"number": "FS/1/2026", "ksef_number": "KSEF-1"}
    )

    result = _run(["send", "--month", "2026-07", "--net", "1000", "--yes"], home=home)

    _assert_refused_by_guard(result)
    assert "już wystawiona" in result.stderr


def test_send_prod_refuses_unseeded_year(tmp_path):
    """Pierwsza produkcyjna wysyłka w roku bez --seq wystawiłaby FS/1/<rok> obok
    faktur wystawionych wcześniej ręcznie."""
    home = _ready_home(tmp_path)

    result = _run(["send", "--month", "2026-07", "--net", "1000", "--prod", "--yes"], home=home)

    _assert_refused_by_guard(result)
    assert "--seq" in result.stderr


def test_force_bypasses_guard_and_reaches_the_network_barrier(tmp_path):
    """Kontrola negatywna dla testów guardów: z --force sterowanie dochodzi aż do
    send_invoice, czyli bariera _no_send jest osiągalna z tej ścieżki. Bez tego testu
    guardy mogłyby „przechodzić" tylko dlatego, że wysyłka nigdy nie jest próbowana."""
    home = _ready_home(tmp_path)
    ledger_path = home / "out" / "ledger.json"
    Ledger(ledger_path).record(
        "test", "klient", "2026-07", 1, 2026, {"number": "FS/1/2026", "ksef_number": "KSEF-1"}
    )
    before = ledger_path.read_text()

    result = _run(["send", "--month", "2026-07", "--net", "1000", "--force", "--yes"], home=home)

    assert result.exit_code == 1
    assert "Wysyłka nie powiodła się" in result.stderr
    assert "próbował wysłać fakturę" in result.stderr
    # Kluczowe niezależnie od bariery: nieudana wysyłka nie rusza ledgera.
    assert ledger_path.read_text() == before


def test_send_records_nothing_when_confirmation_declined(tmp_path):
    home = _ready_home(tmp_path)

    result = _run(["send", "--month", "2026-07", "--net", "1000"], home=home, input="n\n")

    assert result.exit_code == 0
    assert result.exception is None
    assert not (home / "out" / "ledger.json").exists()


def test_send_number_clash_is_refused(tmp_path):
    """--seq podany dwóm fakturom tego samego miesiąca nie może wyprodukować duplikatu."""
    home = _ready_home(tmp_path)
    Ledger(home / "out" / "ledger.json").record(
        "test", "inny", "2026-06", 7, 2026, {"number": "FS/7/2026", "ksef_number": "KSEF-7"}
    )

    result = _run(["send", "--month", "2026-07", "--net", "1000", "--seq", "7", "--yes"], home=home)

    _assert_refused_by_guard(result)
    assert "już użyty" in result.stderr


def test_render_points_at_the_file_that_actually_exists(tmp_path):
    """Bez extry [pdf] nie powstaje invoice.pdf, więc „Podgląd:" nie może wskazywać
    na nieistniejący plik — a od kiedy PDF jest opcjonalny, to jest domyślny przypadek."""
    home = _ready_home(tmp_path)

    result = _run(["render", "--profile", "klient", "--month", "2026-07", "--net", "1000"], home=home)

    assert result.exit_code == 0, result.output
    preview = next(
        line.split("Podgląd:", 1)[1].strip() for line in result.stdout.splitlines() if "Podgląd:" in line
    )
    assert Path(preview).exists(), f"Podgląd wskazuje na nieistniejący plik: {preview}"


# --- end-to-end przez main() -------------------------------------------------------


def test_missing_config_gives_one_line_without_traceback(tmp_path):
    """Przez `python -m`, czyli przez prawdziwy main() — świeża instalacja bez configu
    to stan, w którym startuje każdy nowy użytkownik, i nie może sypać tracebackiem."""
    import os
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "ksef_invoice", "--home", str(tmp_path), "status", "--month", "2026-07"],
        capture_output=True,
        text=True,
        env=os.environ,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "Traceback" not in result.stderr
    assert len(result.stderr.strip().splitlines()) == 1, result.stderr
    assert str(tmp_path) in result.stderr
