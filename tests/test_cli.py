"""Warstwa CLI: helpery i powierzchnia komend.

Helpery testujemy wprost, bo to one decydują o numerze faktury i o tym, gdzie
ląduje katalog faktury — a przez CliRunner widać tylko sformatowany tekst.
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import ksef_invoice.cli as cli
from ksef_invoice.browse import artifact_dir_name
from ksef_invoice.cli import _allocate_number, _invoice_dir, _parse_nets, app
from ksef_invoice.config import Config, Profile, load_config
from ksef_invoice.invoice import Invoice, build_invoice
from ksef_invoice.ledger import Ledger
from ksef_invoice.onboard import append_profile, create_config, create_env, profile_block

REPO_ROOT = Path(__file__).resolve().parents[1]

# NIP zgodny z Podmiot1 w obu szablonach — profil na nim przechodzi check_seller_nip,
# więc `render` w testach faktycznie składa fakturę zamiast odmawiać na rozjeździe NIP-u.
EXAMPLE_NIP = "1111111111"

ONE_LINE = REPO_ROOT / "examples" / "template.example.xml"
TWO_LINES = REPO_ROOT / "tests" / "fixtures" / "two_lines.xml"


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


# --- _invoice_dir ------------------------------------------------------------------


def test_invoice_dir_uses_the_shared_artifact_dir_name(tmp_path):
    """Numer faktury zawiera / — bez podmiany zrobiłby zagnieżdżone katalogi.

    Zapis (tu) i odczyt (`list` przez browse) muszą składać nazwę jedną regułą — rozjazd
    tych dwóch dawał w listingu ścieżkę innej faktury niż wpis, obok którego stała.
    """
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
    config = Config(
        nip=EXAMPLE_NIP,
        number_format="FS/{seq}/{year}",
        profiles={},
        environment="test",
        ksef_token=None,
        out_dir=tmp_path,
    )
    profile = Profile(
        name="klient",
        template_path=ONE_LINE,
        vat_rate="23",
        issue_day="today",
        due_days=14,
        due_day_next_month=None,
    )

    target = _invoice_dir(config, profile, invoice)

    assert target == tmp_path / "test" / "klient" / "2026-07_FS-8-2026"
    assert target.name == artifact_dir_name(invoice.month, invoice.number)


# --- przeglądanie: profiles / list / path ------------------------------------------


def _run(args: list[str], **kwargs):
    return CliRunner().invoke(app, args, **kwargs)


def _project(
    monkeypatch,
    tmp_path: Path,
    *names: str,
    environment: str = "test",
    source: Path = ONE_LINE,
) -> Config:
    """Podstawia CLI atrapę katalogu projektu: szablony w templates/, stan w out/.

    Komendy wołają `load_config()` bez argumentu — katalog projektu jest jeden i wynika
    z położenia kodu — więc to jedyny punkt, w którym CLI dowiaduje się, gdzie leży stan.
    PROJECT_ROOT podmieniamy razem z nim, bo `profiles` przez niego skraca ścieżkę
    szablonu w tabeli.
    """
    (tmp_path / "templates").mkdir(exist_ok=True)
    profiles = {}
    for name in names or ("klient",):
        template = tmp_path / "templates" / f"{name}.xml"
        shutil.copy(source, template)
        profiles[name] = Profile(
            name=name,
            template_path=template,
            vat_rate="23",
            issue_day="today",
            due_days=14,
            due_day_next_month=None,
        )
    config = Config(
        nip=EXAMPLE_NIP,
        number_format="FS/{seq}/{year}",
        profiles=profiles,
        environment=environment,
        ksef_token=None,
        out_dir=tmp_path / "out",
    )
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda: config)
    return config


def _record_invoice(
    config: Config, environment: str, month: str, seq: int, *, profile: str = "klient"
) -> str:
    """Wpis w ledgerze + katalog z artefaktami, jak po udanym `send`."""
    number = f"FS/{seq}/2026"
    Ledger(config.out_dir / "ledger.json").record(
        environment,
        profile,
        month,
        seq,
        2026,
        {
            "month": month,
            "profile": profile,
            "number": number,
            "seq": seq,
            "net": "1000.00",
            "vat": "230.00",
            "gross": "1230.00",
            "ksef_number": f"5252000019-{month.replace('-', '')}31-8275E6C00000-{seq:02d}",
        },
    )
    target = config.out_dir / environment / profile / artifact_dir_name(month, number)
    target.mkdir(parents=True, exist_ok=True)
    return number


def test_list_command_does_not_shadow_the_list_builtin():
    """Funkcja komendy nazywa się `list_invoices`, nie `list`.

    cli.py ma `from __future__ import annotations`, więc Typer rozwiązuje `net: list[str]`
    z render/send przez get_type_hints w globalsach modułu. Moduł-level `list` przesłania
    builtin i `render` wywala się na `TypeError: 'function' object is not subscriptable`
    (sprawdzone) — czyli nowa komenda urywa dwie istniejące.
    """
    assert "list" not in vars(cli), "funkcja `list` w globalsach modułu przesłania builtin"
    assert _run(["render", "--help"]).exit_code == 0


def test_profiles_shows_nets_vat_and_due_rule(tmp_path, monkeypatch):
    _project(monkeypatch, tmp_path)

    result = _run(["profiles"])

    assert result.exit_code == 0, result.output
    assert "klient" in result.stdout
    assert "23%" in result.stdout
    assert "+14 dni" in result.stdout
    assert "templates/klient.xml" in result.stdout


def test_profiles_json_has_a_stable_shape(tmp_path, monkeypatch):
    _project(monkeypatch, tmp_path)

    payload = json.loads(_run(["profiles", "--json"]).stdout)

    assert set(payload) == {"nip", "number_format", "environment", "profiles"}
    (profile,) = payload["profiles"]
    assert set(profile) == {
        "name",
        "nets",
        "vat_rate",
        "issue_day",
        "due_days",
        "due_day_next_month",
        "template",
    }
    assert (profile["name"], profile["nets"], profile["due_days"]) == ("klient", 1, 14)
    assert profile["template"] == "templates/klient.xml"


def test_profiles_agrees_with_render_on_the_number_of_nets(tmp_path, monkeypatch):
    """Dwie niezależne ścieżki: `profiles` czyta placeholdery {{lineN_net}}, `render`
    faktycznie składa fakturę i waliduje ją XSD. Rozjazd znaczyłby, że tabela kłamie
    o tym, ile kwot podać — czyli myli w jedynej rzeczy, po którą się do niej zagląda."""
    _project(monkeypatch, tmp_path, source=TWO_LINES)

    nets = json.loads(_run(["profiles", "--json"]).stdout)["profiles"][0]["nets"]
    amounts = [argument for _ in range(nets) for argument in ("--net", "1000")]
    result = _run(["render", "--month", "2026-07", *amounts])

    assert nets == 2
    assert result.exit_code == 0, result.output


def _root_with_token(tmp_path: Path, token: str) -> Path:
    """Prawdziwy katalog projektu z .env — token ma dojść do Config normalną drogą
    (load_config → _load_dotenv), a nie przez stub. Inaczej test nie dowodzi niczego
    o tym, co narzędzie faktycznie ma w ręku, gdy drukuje JSON."""
    (tmp_path / "examples").mkdir()
    for name in (".env.example", "template.example.xml"):
        shutil.copy(REPO_ROOT / "examples" / name, tmp_path / "examples" / name)
    create_config(tmp_path, EXAMPLE_NIP)
    create_env(tmp_path)
    append_profile(
        tmp_path, "klient", profile_block("klient", "examples/template.example.xml", "23", due_days=14)
    )
    (tmp_path / ".env").write_text(f"KSEF_ENV=prod\nKSEF_TOKEN={token}\n")
    return tmp_path


@pytest.mark.parametrize("command", ["profiles", "list"])
def test_browse_json_never_carries_the_token(tmp_path, monkeypatch, command):
    """`.env` leży obok config.toml, a load_config wciąga KSEF_TOKEN do Config —
    nowa powierzchnia maszynowa nie może go wynieść."""
    token = "TOKEN-KTORY-NIE-MA-PRAWA-WYJSC-1234567890"
    root = _root_with_token(tmp_path, token)
    monkeypatch.setattr(cli, "PROJECT_ROOT", root)
    monkeypatch.setattr(cli, "load_config", lambda: load_config(root))
    _record_invoice(load_config(root), "prod", "2026-07", 1)

    result = _run([command, "--json"])

    assert result.exit_code == 0, result.output
    assert token not in result.stdout
    # Kontrola pozytywna: token faktycznie doszedł do konfiguracji, więc asercja wyżej
    # nie przechodzi tylko dlatego, że .env nie został wczytany.
    assert load_config(root).ksef_token == token


def test_list_on_empty_ledger_exits_zero(tmp_path, monkeypatch):
    """Świadoma asymetria wobec `status`, który kończy 1: `status` pyta o konkretną
    fakturę i jej brak jest błędem, a `list` przegląda."""
    _project(monkeypatch, tmp_path)

    result = _run(["list"])

    assert result.exit_code == 0, result.output
    assert "Brak wystawionych faktur" in result.stdout


def test_list_json_on_empty_ledger_is_still_a_contract(tmp_path, monkeypatch):
    _project(monkeypatch, tmp_path)

    result = _run(["list", "--json"])

    payload = json.loads(result.stdout)
    assert payload["invoices"] == []
    assert (payload["count"], payload["gross_total"]) == (0, "0")
    assert result.exit_code == 0
    assert result.stderr == "", result.stderr


def test_list_shows_recorded_invoice_and_separates_prod(tmp_path, monkeypatch):
    config = _project(monkeypatch, tmp_path)
    _record_invoice(config, "test", "2026-06", 3)
    _record_invoice(config, "prod", "2026-07", 8)

    testowe = _run(["list"])
    produkcyjne = _run(["list", "--prod"])

    assert "FS/3/2026" in testowe.stdout
    assert "FS/8/2026" not in testowe.stdout
    assert "FS/8/2026" in produkcyjne.stdout
    assert "FS/3/2026" not in produkcyjne.stdout
    assert "PROD" in produkcyjne.stdout


def test_list_reports_the_gross_total(tmp_path, monkeypatch):
    config = _project(monkeypatch, tmp_path)
    _record_invoice(config, "test", "2026-06", 1)
    _record_invoice(config, "test", "2026-07", 2)

    assert "2460.00 PLN brutto" in _run(["list"]).stdout


def test_list_marks_invoices_whose_artifacts_are_gone(tmp_path, monkeypatch):
    """Ledger bez odpowiadających mu katalogów (skopiowany osobno, posprzątane out/)
    to stan, który musi być widoczny — nie udajemy, że pliki są."""
    config = _project(monkeypatch, tmp_path)
    number = _record_invoice(config, "test", "2026-07", 1)
    shutil.rmtree(config.out_dir / "test" / "klient" / artifact_dir_name("2026-07", number))

    payload = json.loads(_run(["list", "--json"]).stdout)

    assert payload["invoices"][0]["dir"] is None
    # Kolumna `pliki` musi stracić znacznik, a nie tylko „gdzieś" pokazać kreskę.
    assert "✓" not in _run(["list"]).stdout


def test_list_json_carries_what_the_table_omits(tmp_path, monkeypatch):
    """Tabela świadomie nie ma numeru KSeF (35 znaków zawijałoby się przy 80 kolumnach
    i i tak nie dałoby się skopiować) ani ścieżki — więc jedno i drugie musi być w JSON-ie
    w całości, inaczej ta decyzja gubi dane."""
    config = _project(monkeypatch, tmp_path)
    _record_invoice(config, "test", "2026-07", 1)

    payload = json.loads(_run(["list", "--json"]).stdout)

    assert set(payload) == {"environment", "count", "gross_total", "invoices"}
    (invoice,) = payload["invoices"]
    assert set(invoice) == {
        "month",
        "profile",
        "number",
        "seq",
        "net",
        "vat",
        "gross",
        "ksef_number",
        "acquisition_date",
        "sent_at",
        "dir",
    }
    assert invoice["ksef_number"] == "5252000019-20260731-8275E6C00000-01"
    assert invoice["ksef_number"] not in _run(["list"]).stdout
    assert Path(invoice["dir"]).is_dir()


def test_list_rejects_unknown_profile(tmp_path, monkeypatch):
    """Bez tej walidacji literówka wygląda jak „brak faktur" — najgorszy fałszywy
    negatyw w narzędziu, w którym numeracja ma skutki prawne."""
    config = _project(monkeypatch, tmp_path)
    _record_invoice(config, "test", "2026-07", 1)

    result = _run(["list", "--profile", "klint"])

    assert result.exit_code == 2, result.output
    assert "klient" in result.output


def test_list_accepts_profile_known_only_to_the_ledger(tmp_path, monkeypatch):
    """Profil usunięty z config.toml ma nadal historię, więc musi dać się o nią zapytać."""
    config = _project(monkeypatch, tmp_path)
    _record_invoice(config, "test", "2026-04", 1, profile="juz-nieobecny")

    result = _run(["list", "--profile", "juz-nieobecny"])

    assert result.exit_code == 0, result.output
    assert "FS/1/2026" in result.stdout


def test_list_year_filter(tmp_path, monkeypatch):
    config = _project(monkeypatch, tmp_path)
    _record_invoice(config, "test", "2026-07", 1)

    assert "FS/1/2026" in _run(["list", "--year", "2026"]).stdout
    assert "Brak wystawionych faktur" in _run(["list", "--year", "2025"]).stdout


def test_path_prints_one_clean_line_for_a_deep_directory(tmp_path, monkeypatch):
    """Rich zawija do szerokości terminala, więc console.print wstawiłby w środek długiej
    ścieżki znak nowej linii i zepsuł `open $(uv run ksef-invoice path ...)`. Głęboka
    ścieżka jest tu istotą testu, nie ozdobą."""
    deep = tmp_path / "bardzo" / "gleboko" / "zagniezdzony" / "katalog" / "z-projektem-uzytkownika"
    deep.mkdir(parents=True)
    config = _project(monkeypatch, deep)
    _record_invoice(config, "test", "2026-07", 1)

    result = _run(["path", "--month", "2026-07"])

    assert result.exit_code == 0, result.output
    (line,) = result.stdout.splitlines()
    assert "…" not in line
    assert Path(line).is_dir(), line
    assert len(line) > 80, f"ścieżka za krótka, żeby test cokolwiek dowodził: {len(line)}"


def test_path_autoselects_the_only_profile(tmp_path, monkeypatch):
    config = _project(monkeypatch, tmp_path)
    _record_invoice(config, "test", "2026-07", 1)

    assert _run(["path", "--month", "2026-07"]).stdout.strip().endswith("2026-07_FS-1-2026")


def test_path_reports_missing_invoice_on_stderr_only(tmp_path, monkeypatch):
    """`$(...)` nie może dostać śmieci na stdout, gdy nie ma czego otworzyć."""
    _project(monkeypatch, tmp_path)

    result = _run(["path", "--month", "2019-01"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Brak zapisanej faktury" in result.stderr


def test_path_lists_every_directory_after_force(tmp_path, monkeypatch):
    config = _project(monkeypatch, tmp_path)
    _record_invoice(config, "test", "2026-07", 1)
    (config.out_dir / "test" / "klient" / "2026-07_FS-9-2026").mkdir()

    lines = _run(["path", "--month", "2026-07"]).stdout.splitlines()

    assert len(lines) == 2
    assert all(Path(line).is_dir() for line in lines)


def _project_with_history(monkeypatch, tmp_path: Path) -> Config:
    """Projekt, w którym `stary` ma fakturę w rejestrze, ale nie ma już sekcji w config.toml.
    Realne po zakończeniu współpracy z klientem: konfigurację się porządkuje, historia zostaje."""
    config = _project(monkeypatch, tmp_path)
    _record_invoice(config, "test", "2026-07", 3, profile="stary")
    return config


@pytest.mark.parametrize("command", ["path", "status", "pdf"])
def test_read_only_commands_accept_a_profile_only_in_the_ledger(tmp_path, monkeypatch, command):
    """`list` pokazuje ten profil i w stopce odsyła do `status` oraz `path` — obie muszą
    zadziałać na tę samą nazwę. Odpowiedź „Nieznany profil" na profil, którego fakturę
    narzędzie właśnie wypisało, jest wprost nieprawdziwa."""
    config = _project_with_history(monkeypatch, tmp_path)
    invoice = build_invoice("2026-07", [Decimal("1000")], config.profiles["klient"], number="FS/3/2026")
    directory = config.out_dir / "test" / "stary" / "2026-07_FS-3-2026"
    (directory / "invoice.xml").write_bytes(invoice.xml)

    listing = _run(["list"])
    result = _run([command, "--profile", "stary", "--month", "2026-07"])

    assert "stary" in listing.stdout
    assert result.exit_code == 0, result.output


def test_render_still_refuses_a_profile_only_in_the_ledger(tmp_path, monkeypatch):
    """Kontrola negatywna: rozluźnienie dotyczy tylko odczytu. Profil z historii nie ma
    szablonu ani stawki VAT, więc na ścieżce wystawiania musi dalej odmawiać."""
    _project_with_history(monkeypatch, tmp_path)

    result = _run(["render", "--profile", "stary", "--month", "2026-08", "--net", "1000"])

    assert result.exit_code == 2
    assert "Nieznany profil" in result.output


def test_unknown_profile_is_still_a_parameter_error(tmp_path, monkeypatch):
    """Suma config+ledger nie może wpuścić literówki — „brak faktur" byłoby tu najgorszym
    fałszywym negatywem, bo wygląda na poprawną odpowiedź."""
    _project_with_history(monkeypatch, tmp_path)

    for command in (["list"], ["path", "--month", "2026-07"], ["status", "--month", "2026-07"]):
        result = _run([*command, "--profile", "starry"])
        assert result.exit_code == 2, (command, result.output)
        assert "stary" in result.output, command


def test_list_json_dir_belongs_to_the_invoice_in_the_same_row(tmp_path, monkeypatch):
    """Zarzut z review, end-to-end: po `--force` w out/ są dwa katalogi, a w rejestrze
    jeden wpis. `dir` musi należeć do faktury z tego samego wiersza — skrypt podpinający
    `$(jq -r .dir)/invoice.pdf` do maila załączyłby inaczej inną fakturę."""
    config = _project(monkeypatch, tmp_path)
    _record_invoice(config, "test", "2026-07", 8)
    _record_invoice(config, "test", "2026-07", 9)

    (invoice,) = json.loads(_run(["list", "--json"]).stdout)["invoices"]

    assert invoice["number"] == "FS/9/2026"
    assert Path(invoice["dir"]).name == "2026-07_FS-9-2026"
    assert Path(invoice["dir"]).is_dir()


def test_path_and_pdf_agree_on_directories(tmp_path, monkeypatch):
    """Obie komendy chodzą po tym samym globie — nie mogą się rozjechać co do tego,
    które katalogi istnieją."""
    _project(monkeypatch, tmp_path)
    _run(["render", "--month", "2026-07", "--net", "1000"])
    _run(["render", "--month", "2026-07", "--net", "2000", "--seq", "9"])

    from_path = {Path(line) for line in _run(["path", "--month", "2026-07"]).stdout.splitlines()}
    pdf_output = _run(["pdf", "--month", "2026-07"]).stdout

    assert len(from_path) == 2, from_path
    assert pdf_output.count("✅") == len(from_path)
