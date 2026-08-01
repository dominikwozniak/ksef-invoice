"""Onboarding: init (config.toml/.env), dopisanie profilu, doctor.

Wszystko na tmp_path z jawnym `root` — nigdy na prawdziwym repo, bo w jego .env
siedzi produkcyjny token.
"""

import shutil
from datetime import date
from pathlib import Path

import pytest

from ksef_invoice.config import load_config
from ksef_invoice.doctor import FAIL, OK, SKIP, WARN, line_count, run_checks
from ksef_invoice.onboard import (
    append_profile,
    config_nip,
    create_config,
    create_env,
    existing_profiles,
    nip_checksum_ok,
    profile_block,
    suspicious_nip_warning,
    validate_nip,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Syntetyczny NIP z poprawną sumą kontrolną — dane testowe, nie należy do nikogo z projektu.
# Musi się różnić od 1111111111 z template.example.xml (test rozjazdu NIP-u sprzedawcy)
# i nie może być powtórzoną cyfrą (test braku ostrzeżenia o NIP-ie-atrapie).
VALID_NIP = "5252000019"
TODAY = date(2026, 7, 31)


def make_root(tmp_path: Path) -> Path:
    """Minimalny „klon" repo: examples/ potrzebne przez create_env i jako szablon."""
    (tmp_path / "examples").mkdir()
    shutil.copy(PROJECT_ROOT / "examples" / ".env.example", tmp_path / "examples" / ".env.example")
    shutil.copy(
        PROJECT_ROOT / "examples" / "template.example.xml", tmp_path / "examples" / "template.example.xml"
    )
    return tmp_path


# --- walidacja NIP -----------------------------------------------------------------


@pytest.mark.parametrize("raw", [VALID_NIP, f"PL{VALID_NIP}", "525-200-00-19", f" {VALID_NIP} "])
def test_validate_nip_accepts_separators_and_prefix(raw):
    assert validate_nip(raw) == VALID_NIP


def test_validate_nip_rejects_bad_checksum():
    with pytest.raises(ValueError, match="kontroln"):
        validate_nip("1234567890")


def test_validate_nip_rejects_wrong_length():
    with pytest.raises(ValueError, match="10 cyfr"):
        validate_nip("738217179")


def test_suspicious_nip_warns_on_repeated_digit():
    # 1111111111 ma poprawną sumę kontrolną (45 % 11 == 1), więc walidacja go przepuszcza —
    # dlatego ostrzeżenie jest osobnym mechanizmem.
    assert nip_checksum_ok("1111111111")
    assert validate_nip("1111111111") == "1111111111"
    assert "440" in suspicious_nip_warning("1111111111")
    assert suspicious_nip_warning(VALID_NIP) is None


# --- init --------------------------------------------------------------------------


def test_create_config_and_env(tmp_path):
    root = make_root(tmp_path)
    config_path = create_config(root, f"PL{VALID_NIP}")
    env_path = create_env(root)

    assert config_nip(config_path) == VALID_NIP
    assert "KSEF_ENV=test" in env_path.read_text()
    # Numeracja przetrwała .format() — nawiasy nie zostały zjedzone.
    assert 'number_format = "FS/{seq}/{year}"' in config_path.read_text()


def test_create_config_refuses_overwrite(tmp_path):
    root = make_root(tmp_path)
    create_config(root, VALID_NIP)
    (root / "config.toml").write_text("moje = 'dane'\n")

    with pytest.raises(FileExistsError, match="nie nadpisuję"):
        create_config(root, VALID_NIP)
    assert (root / "config.toml").read_text() == "moje = 'dane'\n"

    create_config(root, VALID_NIP, force=True)
    assert config_nip(root / "config.toml") == VALID_NIP


def test_create_env_refuses_overwrite(tmp_path):
    """Najważniejszy test bezpieczeństwa: .env może zawierać produkcyjny token."""
    root = make_root(tmp_path)
    (root / ".env").write_text("KSEF_TOKEN=sekret\n")

    with pytest.raises(FileExistsError, match="token"):
        create_env(root)
    assert (root / ".env").read_text() == "KSEF_TOKEN=sekret\n"


def test_create_config_rejects_bad_nip_before_writing(tmp_path):
    root = make_root(tmp_path)
    with pytest.raises(ValueError, match="kontroln"):
        create_config(root, "1234567890")
    assert not (root / "config.toml").exists()


# --- dopisywanie profilu -----------------------------------------------------------


def test_profile_block_requires_exactly_one_due_rule():
    with pytest.raises(ValueError, match="dokładnie jedną"):
        profile_block("x", "t.xml", "23")
    with pytest.raises(ValueError, match="dokładnie jedną"):
        profile_block("x", "t.xml", "23", due_days=14, due_day_next_month=15)


def test_append_profile_produces_loadable_config(tmp_path):
    root = make_root(tmp_path)
    create_config(root, VALID_NIP)
    block = profile_block("klient", "examples/template.example.xml", "23", due_day_next_month=15)
    append_profile(root, "klient", block)

    profile = load_config(root).profiles["klient"]
    assert profile.vat_rate == "23"
    assert profile.due_day_next_month == 15
    assert profile.due_days is None
    assert profile.issue_day == "today"  # domyślna z szablonu config.toml


def test_append_two_profiles(tmp_path):
    root = make_root(tmp_path)
    create_config(root, VALID_NIP)
    append_profile(root, "a", profile_block("a", "examples/template.example.xml", "23", due_days=14))
    append_profile(root, "b", profile_block("b", "examples/template.example.xml", "np", due_days=30))

    config = load_config(root)
    assert existing_profiles(root / "config.toml") == {"a", "b"}
    assert config.profiles["b"].vat_rate == "np"


def test_append_profile_refuses_duplicate_name(tmp_path):
    root = make_root(tmp_path)
    create_config(root, VALID_NIP)
    block = profile_block("klient", "examples/template.example.xml", "23", due_days=14)
    append_profile(root, "klient", block)

    with pytest.raises(ValueError, match="już jest"):
        append_profile(root, "klient", block)
    append_profile(root, "klient", block, force=True)  # z --force przechodzi

    # --force ma podmienić blok, nie dopisać drugiego: duplikat tabeli to plik,
    # którego tomllib nie zparsuje, więc padłaby każda kolejna komenda.
    assert existing_profiles(root / "config.toml") == {"klient"}


def test_force_replaces_profile_in_place(tmp_path):
    root = make_root(tmp_path)
    create_config(root, VALID_NIP)
    append_profile(root, "a", profile_block("a", "examples/template.example.xml", "23", due_days=14))
    append_profile(root, "b", profile_block("b", "examples/template.example.xml", "23", due_days=14))

    # adnotacja użytkownika nad sąsiednim profilem — podmiana profilu `a` nie może jej ruszyć
    config_path = root / "config.toml"
    annotation = "# UWAGA: umowa z b wygasa 2027-01"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("[profiles.b]", f"{annotation}\n[profiles.b]"),
        encoding="utf-8",
    )

    append_profile(
        root,
        "a",
        profile_block("a", "examples/template.example.xml", "np", due_day_next_month=15),
        force=True,
    )

    config = load_config(root)
    assert set(config.profiles) == {"a", "b"}
    assert config.profiles["a"].vat_rate == "np"
    assert config.profiles["a"].due_day_next_month == 15
    assert config.profiles["a"].due_days is None
    assert config.profiles["b"].due_days == 14  # sąsiedni profil nietknięty

    text = config_path.read_text(encoding="utf-8")
    assert "# NIP sprzedawcy" in text  # komentarze nagłówka pliku przeżywają
    assert annotation in text  # adnotacja sąsiada też — należy do jego bloku
    # profil `b` zachowuje swój komentarz i pustą linię rozdzielającą
    assert f"\n\n# Profil dopisany przez `templatize --write-config`.\n{annotation}\n[profiles.b]" in text


def test_append_profile_requires_config(tmp_path):
    root = make_root(tmp_path)
    with pytest.raises(FileNotFoundError, match="init"):
        append_profile(root, "x", profile_block("x", "t.xml", "23", due_days=14))


# --- doctor ------------------------------------------------------------------------


def _statuses(checks) -> dict[str, str]:
    return {check.name: check.status for check in checks}


def healthy_root(tmp_path: Path) -> Path:
    root = make_root(tmp_path)
    create_config(root, "1111111111")  # NIP zgodny z template.example.xml
    create_env(root)
    append_profile(
        root, "demo", profile_block("demo", "examples/template.example.xml", "23", due_day_next_month=15)
    )
    return root


def test_doctor_passes_on_healthy_setup(tmp_path):
    checks = run_checks(healthy_root(tmp_path), today=TODAY)
    statuses = _statuses(checks)

    assert not [check for check in checks if check.status == FAIL]
    assert statuses["config.toml"] == OK
    assert statuses["profil demo"] == OK
    # NIP-atrapa z przykładu zasługuje na ostrzeżenie, ale nie blokuje.
    assert statuses["NIP sprzedawcy"] == WARN
    detail = next(check.detail for check in checks if check.name == "profil demo")
    assert "1× --net" in detail


def test_doctor_never_warns_about_missing_pdf(tmp_path):
    """PDF to opcja, nie usterka — wiersz nie może świecić jak realny problem setupu.

    Asercja nie zakłada, czy pango jest w tym środowisku: z nim wychodzi OK, bez niego SKIP.
    """
    checks = run_checks(healthy_root(tmp_path), today=TODAY)

    assert _statuses(checks)["PDF (opcjonalny)"] in (OK, SKIP)


def test_doctor_accepts_issue_day_last_mid_month(tmp_path):
    """issue_day = "last" nie może dawać FAIL przez cały miesiąc poza jego ostatnim dniem.

    Próbny render za bieżący miesiąc wypadałby z datą wystawienia w przyszłości, którą
    build_invoice słusznie odrzuca — doctor sonduje wtedy poprzedni miesiąc.
    """
    root = healthy_root(tmp_path)
    config = (root / "config.toml").read_text().replace('issue_day = "today"', 'issue_day = "last"')
    (root / "config.toml").write_text(config)

    mid_month = date(2026, 7, 15)
    checks = run_checks(root, today=mid_month)
    assert _statuses(checks)["profil demo"] == OK
    assert "2026-06" in next(check.detail for check in checks if check.name == "profil demo")

    # w ostatnim dniu miesiąca sonduje już bieżący
    checks = run_checks(root, today=date(2026, 7, 31))
    assert "2026-07" in next(check.detail for check in checks if check.name == "profil demo")


@pytest.mark.parametrize("bad", ['"foo"', "0"])
def test_doctor_reports_invalid_issue_day_instead_of_crashing(tmp_path, bad):
    """Zepsute issue_day ma być wynikiem diagnostyki, nie jej końcem.

    Wybór miesiąca próbnego czyta issue_day, więc musi biec pod tym samym try
    co render — inaczej `doctor` wywala się tracebackiem na pliku, który ma zbadać.
    """
    root = healthy_root(tmp_path)
    config = (root / "config.toml").read_text().replace('issue_day = "today"', f"issue_day = {bad}")
    (root / "config.toml").write_text(config)

    checks = run_checks(root, today=TODAY)
    assert _statuses(checks)["profil demo"] == FAIL


def test_doctor_reports_missing_config(tmp_path):
    checks = run_checks(make_root(tmp_path), today=TODAY)
    assert [check.status for check in checks] == [FAIL]
    assert "config.toml" in checks[0].detail


def test_doctor_detects_seller_nip_mismatch(tmp_path):
    root = healthy_root(tmp_path)
    config = (root / "config.toml").read_text().replace('nip = "1111111111"', f'nip = "{VALID_NIP}"')
    (root / "config.toml").write_text(config)

    checks = run_checks(root, today=TODAY)
    assert _statuses(checks)["profil demo"] == FAIL
    assert "NIP sprzedawcy w szablonie" in next(c.detail for c in checks if c.name == "profil demo")


def test_doctor_detects_template_without_line_placeholders(tmp_path):
    root = healthy_root(tmp_path)
    template = root / "examples" / "template.example.xml"
    template.write_bytes(template.read_bytes().replace(b"{{line1_net}}", b"100.00"))

    checks = run_checks(root, today=TODAY)
    assert _statuses(checks)["profil demo"] == FAIL


def test_doctor_flags_missing_token_for_prod(tmp_path, monkeypatch):
    monkeypatch.setenv("KSEF_ENV", "prod")
    monkeypatch.delenv("KSEF_TOKEN", raising=False)
    checks = run_checks(healthy_root(tmp_path), today=TODAY)
    assert _statuses(checks)["uwierzytelnienie"] == FAIL


def test_doctor_reports_unseeded_prod_counter(tmp_path):
    checks = run_checks(healthy_root(tmp_path), today=TODAY)
    detail = next(check.detail for check in checks if check.name == "licznik prod")
    assert "nie zasiany" in detail


def test_line_count_counts_distinct_placeholders(tmp_path):
    template = tmp_path / "t.xml"
    template.write_text("{{line1_net}} {{line1_net}} {{line2_net}}")
    assert line_count(template) == 2
