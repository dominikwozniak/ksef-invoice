"""CLI: render / send / status."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from importlib.metadata import version as package_version
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import Config, Profile, load_config
from .doctor import FAIL, OK, WARN, run_checks
from .invoice import Invoice, build_invoice, check_seller_nip, format_number, validate_fa3
from .ledger import Ledger
from .onboard import (
    append_profile,
    config_nip,
    create_config,
    create_env,
    ensure_home,
    profile_block,
    suspicious_nip_warning,
)
from .send import send_invoice
from .templatize import templatize as run_templatize
from .visualize import to_html, to_pdf

app = typer.Typer(help="Wystawianie powtarzalnych faktur sprzedażowych w KSeF.", no_args_is_help=True)

# Payload (tabele, ścieżki, potwierdzenia) na stdout; błędy i ostrzeżenia na stderr —
# inaczej `ksef-invoice status ... | jq` psuje się, gdy w środku wypadnie ostrzeżenie.
console = Console()
# soft_wrap, bo komunikaty błędów zawierają ścieżki: twarde zawijanie rich-a wstawiało
# w środek ścieżki znak nowej linii, co psuło kopiowanie, grep i dopasowanie po treści
# komunikatu (na tym opiera się tabela troubleshootingu w skillu ksef-onboard).
err_console = Console(stderr=True, soft_wrap=True)


# Jeden katalog per użytkownik, jak ~/.aws czy ~/.ssh — a nie szukanie w górę od cwd.
# Numer faktury to roczna sekwencja z out/ledger.json i nie może zależeć od tego, w którym
# katalogu stoi shell: znaleziony gdzie indziej pusty ledger wystartowałby numerację od 1.
DEFAULT_HOME = Path.home() / ".ksef-invoice"

HOME_HELP = "Katalog z config.toml, .env, templates/ i out/ (domyślnie ~/.ksef-invoice)"


@dataclass(frozen=True)
class AppContext:
    """Stan współdzielony przez komendy. Trzymany w ctx.obj, nie w module — stan modułu
    przeżywa między wywołaniami CliRunner w jednym procesie pytesta i przecieka między
    testami."""

    home: Path


def _version_callback(value: bool) -> None:
    if value:
        console.print(package_version("ksef-invoice"))
        raise typer.Exit()


@app.callback()
def _app(
    ctx: typer.Context,
    home: Path = typer.Option(DEFAULT_HOME, "--home", envvar="KSEF_INVOICE_HOME", help=HOME_HELP),
    show_version: bool = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Pokaż wersję i zakończ.",
    ),
) -> None:
    # Rozwiązywane tutaj, nigdy przy imporcie. envvar= daje udokumentowaną precedencję
    # click-a (flaga > KSEF_INVOICE_HOME > default) i samo-dokumentuje zmienną w --help.
    ctx.obj = AppContext(home=home.expanduser().resolve())


def _home(ctx: typer.Context) -> Path:
    """Katalog roboczy z ctx.obj. Osobna funkcja, żeby komendy nie znały struktury obiektu."""
    return ctx.obj.home


def _parse_nets(nets: list[str]) -> list[Decimal]:
    values = []
    for net in nets:
        try:
            value = Decimal(net.replace(",", "."))
        except InvalidOperation:
            raise typer.BadParameter(f"Kwota {net!r} nie jest liczbą.") from None
        if value <= 0:
            raise typer.BadParameter("Kwota netto musi być dodatnia.")
        values.append(value)
    return values


def _resolve_profile(config: Config, name: str | None) -> Profile:
    if name is None:
        if len(config.profiles) == 1:
            return next(iter(config.profiles.values()))
        raise typer.BadParameter(f"Wybierz profil (--profile): {', '.join(sorted(config.profiles))}")
    if name not in config.profiles:
        raise typer.BadParameter(f"Nieznany profil {name!r}. Dostępne: {', '.join(sorted(config.profiles))}")
    return config.profiles[name]


def _allocate_number(config: Config, ledger: Ledger, month: str, seq: int | None) -> tuple[int, int, str]:
    """Zwraca (seq, year, numer) — seq z ledgera albo z flagi --seq."""
    year, month_no = int(month[:4]), int(month[5:7])
    seq = seq if seq is not None else ledger.next_seq(config.environment, year)
    return seq, year, format_number(config.number_format, seq, year, month_no)


def _invoice_dir(config: Config, profile: Profile, invoice: Invoice) -> Path:
    safe_number = invoice.number.replace("/", "-").replace(" ", "_")
    return config.out_dir / config.environment / profile.name / f"{invoice.month}_{safe_number}"


def _print_summary(config: Config, profile: Profile, invoice: Invoice) -> None:
    table = Table(title="Podsumowanie faktury", show_header=False)
    table.add_row(
        "Środowisko",
        f"[bold red]{config.environment.upper()}[/]" if config.environment == "prod" else config.environment,
    )
    table.add_row("Profil", profile.name)
    table.add_row("Numer", f"[bold]{invoice.number}[/]")
    table.add_row("Data wystawienia (P_1)", invoice.issue_date.isoformat())
    table.add_row("Data sprzedaży (P_6)", invoice.sale_date.isoformat())
    table.add_row("Termin płatności", invoice.payment_due.isoformat())
    if len(invoice.line_nets) > 1:
        for index, line_net in enumerate(invoice.line_nets, start=1):
            table.add_row(f"Pozycja {index} (netto)", f"{line_net} PLN")
    table.add_row("Netto", f"{invoice.net} PLN")
    if profile.vat_rate == "np":
        table.add_row("VAT", "— (np — nie podlega)")
    else:
        table.add_row(f"VAT ({profile.vat_rate}%)", f"{invoice.vat} PLN")
    table.add_row("Brutto", f"[bold]{invoice.gross} PLN[/]")
    table.add_row("Szablon", str(profile.template_path.name))
    console.print(table)
    if invoice.payment_due < invoice.issue_date:
        err_console.print(
            "[yellow]Uwaga: termin płatności wypada przed datą wystawienia "
            "(faktura wystawiana po terminie wynikającym z reguły profilu).[/]"
        )


def _render(config: Config, profile: Profile, month: str, nets: list[Decimal], number: str) -> Invoice:
    invoice = build_invoice(month, nets, profile, number=number)
    validate_fa3(invoice.xml)
    check_seller_nip(invoice.xml, config.nip)
    return invoice


def _write_visualizations(target: Path, xml: bytes) -> Path:
    """Zapisuje invoice.html (zawsze) i invoice.pdf (jeśli WeasyPrint dostępny).
    Zwraca ścieżkę do pliku, który naprawdę powstał — PDF-a albo HTML-a."""
    html_path = target / "invoice.html"
    html_path.write_bytes(to_html(xml))
    pdf = to_pdf(xml)
    if pdf:
        (target / "invoice.pdf").write_bytes(pdf)
        return target / "invoice.pdf"

    msg = "PDF pominięty — brak bibliotek WeasyPrint (macOS: brew install pango"
    if sys.platform == "darwin":
        msg += " + export DYLD_LIBRARY_PATH=/opt/homebrew/lib"
    msg += "). HTML zapisany."
    err_console.print(f"[yellow]{msg}[/]")
    return html_path


NET_HELP = (
    "Kwota netto pozycji; powtórz dla kolejnych pozycji w kolejności z faktury, np. --net 1000 --net 500"
)


@app.command()
def render(
    ctx: typer.Context,
    month: str = typer.Option(..., "--month", help="Miesiąc faktury, np. 2026-07"),
    net: list[str] = typer.Option(..., "--net", help=NET_HELP),
    profile: str = typer.Option(None, "--profile", help="Nazwa profilu z config.toml"),
    seq: int = typer.Option(None, "--seq", help="Wymuś numer w sekwencji (domyślnie: kolejny z ledgera)"),
) -> None:
    """Wygeneruj i zwaliduj XML faktury bez wysyłania (numer: przewidywany, bez rezerwacji)."""
    config = load_config(_home(ctx))
    selected = _resolve_profile(config, profile)
    ledger = Ledger(config.out_dir / "ledger.json")
    _, _, number = _allocate_number(config, ledger, month, seq)

    invoice = _render(config, selected, month, _parse_nets(net), number)
    _print_summary(config, selected, invoice)

    target = _invoice_dir(config, selected, invoice)
    target.mkdir(parents=True, exist_ok=True)
    xml_path = target / "invoice.xml"
    xml_path.write_bytes(invoice.xml)
    preview = _write_visualizations(target, invoice.xml)
    console.print(f"\n✅ XML zwalidowany (XSD FA(3)) i zapisany: [bold]{xml_path}[/]")
    console.print(f"Podgląd: {preview}")
    console.print("Numer jest przewidywany — rezerwacja następuje dopiero przy send.")


@app.command()
def send(
    ctx: typer.Context,
    month: str = typer.Option(..., "--month", help="Miesiąc faktury, np. 2026-07"),
    net: list[str] = typer.Option(..., "--net", help=NET_HELP),
    profile: str = typer.Option(None, "--profile", help="Nazwa profilu z config.toml"),
    seq: int = typer.Option(None, "--seq", help="Wymuś numer w sekwencji (domyślnie: kolejny z ledgera)"),
    prod: bool = typer.Option(False, "--prod", help="Wyślij na PRODUKCJĘ (skutki prawne!)."),
    yes: bool = typer.Option(False, "--yes", help="Pomiń interaktywne potwierdzenie."),
    force: bool = typer.Option(False, "--force", help="Wyślij mimo istniejącego wpisu w ledgerze."),
) -> None:
    """Wygeneruj, zwaliduj i wyślij fakturę do KSeF; zapisz numer KSeF i UPO."""
    config = load_config(_home(ctx))
    if prod:
        config = Config(**{**config.__dict__, "environment": "prod"})
    selected = _resolve_profile(config, profile)

    ledger = Ledger(config.out_dir / "ledger.json")
    existing = ledger.get(config.environment, selected.name, month)
    if existing and not force:
        err_console.print(
            f"[red]Faktura {selected.name} za {month} ({config.environment}) już wystawiona: "
            f"{existing.get('number')} → {existing.get('ksef_number')}.[/]\n"
            "Użyj --force, jeśli świadomie chcesz wysłać kolejną."
        )
        raise typer.Exit(code=1)

    used_seq, year, number = _allocate_number(config, ledger, month, seq)

    clash = ledger.number_exists(config.environment, number)
    if clash and not force:
        err_console.print(
            f"[red]Numer {number} jest już użyty w ledgerze ({config.environment}): "
            f"profil {clash[0]}, miesiąc {clash[1]}.[/]\n"
            "Nie podawaj --seq drugiej fakturze tego samego miesiąca (licznik dolicza się sam). "
            "--force wysyła mimo to."
        )
        raise typer.Exit(code=1)
    if config.environment == "prod" and seq is None and not ledger.year_started("prod", year) and not force:
        err_console.print(
            f"[red]To pierwsza produkcyjna wysyłka w {year} — numer wyszedłby {number}.[/]\n"
            "Zasiej licznik: --seq <następny numer po ostatniej ręcznej fakturze> "
            "(albo --force, jeśli naprawdę zaczynasz numerację od tego numeru)."
        )
        raise typer.Exit(code=1)

    invoice = _render(config, selected, month, _parse_nets(net), number)
    _print_summary(config, selected, invoice)

    if config.environment == "prod":
        console.print(
            "\n[bold red]UWAGA: wysyłka na PRODUKCJĘ — faktura będzie miała skutki "
            "prawne i nie da się jej usunąć (tylko korekta).[/]"
        )
    if not yes and not typer.confirm("Wysłać fakturę?"):
        console.print("Przerwano — nic nie wysłano.")
        raise typer.Exit(code=0)

    console.print(f"\nWysyłam do KSeF ({config.environment})...")
    try:
        result = send_invoice(invoice.xml, config)
    except Exception as error:
        err_console.print(f"\n[red]Wysyłka nie powiodła się:[/] {error}")
        err_console.print(
            "Faktura NIE została zarejestrowana w ledgerze — po usunięciu przyczyny uruchom komendę ponownie."
        )
        raise typer.Exit(code=1) from None

    target = _invoice_dir(config, selected, invoice)
    target.mkdir(parents=True, exist_ok=True)
    (target / "invoice.xml").write_bytes(invoice.xml)
    _write_visualizations(target, invoice.xml)
    if result.upo:
        (target / "upo.xml").write_bytes(result.upo)
    meta = {
        "month": month,
        "profile": selected.name,
        "number": invoice.number,
        "seq": used_seq,
        "line_nets": [str(n) for n in invoice.line_nets],
        "net": str(invoice.net),
        "vat": str(invoice.vat),
        "gross": str(invoice.gross),
        "ksef_number": result.ksef_number,
        "invoice_reference_number": result.invoice_reference_number,
        "session_reference_number": result.session_reference_number,
        "acquisition_date": result.acquisition_date,
        "upo": "upo.xml" if result.upo else None,
        "environment": config.environment,
        "sent_at": datetime.now(UTC).isoformat(),
    }
    (target / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    ledger.record(config.environment, selected.name, month, used_seq, year, meta)

    console.print(f"\n✅ Faktura przyjęta. Numer KSeF: [bold]{result.ksef_number}[/]")
    if result.upo:
        console.print(f"✅ UPO zapisane: [bold]{target / 'upo.xml'}[/]")
    else:
        err_console.print("[yellow]UPO jeszcze niedostępne — sprawdź później w Aplikacji Podatnika.[/]")
    console.print(f"Artefakty: {target}")


@app.command()
def pdf(
    ctx: typer.Context,
    month: str = typer.Option(..., "--month", help="Miesiąc faktury, np. 2026-07"),
    profile: str = typer.Option(None, "--profile", help="Nazwa profilu z config.toml"),
    prod: bool = typer.Option(False, "--prod", help="Faktura produkcyjna."),
) -> None:
    """Wygeneruj HTML+PDF dla już zapisanej faktury z out/ (np. wysłanej wcześniej)."""
    config = load_config(_home(ctx))
    selected = _resolve_profile(config, profile)
    environment = "prod" if prod else config.environment
    matches = sorted((config.out_dir / environment / selected.name).glob(f"{month}_*/invoice.xml"))
    if not matches:
        err_console.print(
            f"[red]Brak zapisanej faktury {selected.name} za {month} ({environment}) w out/.[/]"
        )
        raise typer.Exit(code=1)
    for xml_path in matches:
        console.print(f"✅ {_write_visualizations(xml_path.parent, xml_path.read_bytes())}")


@app.command()
def status(
    ctx: typer.Context,
    month: str = typer.Option(..., "--month", help="Miesiąc faktury, np. 2026-07"),
    profile: str = typer.Option(None, "--profile", help="Nazwa profilu z config.toml"),
    prod: bool = typer.Option(False, "--prod", help="Sprawdź wpis produkcyjny."),
) -> None:
    """Pokaż zapisany status faktury za dany miesiąc (z lokalnego ledgera)."""
    config = load_config(_home(ctx))
    selected = _resolve_profile(config, profile)
    environment = "prod" if prod else config.environment
    entry = Ledger(config.out_dir / "ledger.json").get(environment, selected.name, month)
    if not entry:
        err_console.print(f"[red]Brak wpisu {selected.name} za {month} ({environment}).[/]")
        raise typer.Exit(code=1)
    console.print_json(json.dumps(entry, ensure_ascii=False))


def _template_ref(target: Path, root: Path) -> str:
    """Ścieżka szablonu zapisywana w config.toml — względna do korzenia projektu,
    bo config.py składa ją jako `root / template`."""
    try:
        return str(target.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(target)


@app.command()
def templatize(
    ctx: typer.Context,
    input_xml: Path = typer.Argument(..., help="XML faktury FA(3) pobrany z KSeF (Aplikacja Podatnika)"),
    name: str = typer.Option(None, "--name", help="Nazwa profilu; bez --out zapisze do templates/<name>.xml"),
    out: Path = typer.Option(None, "--out", help="Ścieżka wyjściowego szablonu (domyślnie stdout)"),
    write_config: bool = typer.Option(
        False, "--write-config", help="Dopisz profil do config.toml zamiast drukować blok do skopiowania"
    ),
    due_days: int = typer.Option(
        None, "--due-days", help="Termin płatności = data wystawienia + N dni (wymagane z --write-config)"
    ),
    due_day_next_month: int = typer.Option(
        None,
        "--due-day-next-month",
        help="Termin płatności = D. dzień miesiąca po miesiącu rozliczeniowym (wymagane z --write-config)",
    ),
    force: bool = typer.Option(False, "--force", help="Nadpisz profil o tej nazwie w config.toml"),
) -> None:
    """Zrób szablon z placeholderami z pobranej faktury (onboarding nowego profilu)."""
    home = _home(ctx)
    if write_config:
        if not name:
            raise typer.BadParameter("--write-config wymaga --name (to nazwa sekcji [profiles.<name>]).")
        if (due_days is None) == (due_day_next_month is None):
            raise typer.BadParameter(
                "Podaj dokładnie jedną regułę terminu płatności: --due-days N albo --due-day-next-month D. "
                "Tego nie da się wywnioskować z faktury — to zapis z umowy."
            )

    try:
        result = run_templatize(input_xml.read_bytes())
    except Exception as error:
        err_console.print(f"[red]Nie udało się przetworzyć {input_xml}:[/] {error}")
        raise typer.Exit(code=1) from None

    # Względem home, nie cwd: config.py składa ścieżkę szablonu jako `home / template`,
    # więc szablon zapisany względem katalogu roboczego dawał profil, którego load_config
    # nie znajdzie — a komenda i tak raportowała sukces.
    target = out or (home / "templates" / f"{name}.xml" if name else None)
    if target is not None:
        ensure_home(home)  # 0700 — w templates/ leżą dane kontrahentów
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(result.xml)
        console.print(
            f"✅ Szablon zapisany: [bold]{target}[/] ({result.line_count} poz., vat_rate={result.vat_rate!r})"
        )
    else:
        console.print(result.xml.decode("utf-8"))

    for warning in result.warnings:
        err_console.print(f"[yellow]⚠ {warning}[/]")

    profile_name = name or "moj-profil"
    template_ref = _template_ref(target, home) if target is not None else f"templates/{profile_name}.xml"

    if not write_config:
        console.print("\nDopisz profil do [bold]config.toml[/] (uzupełnij regułę terminu płatności):")
        console.print(
            f"[dim]\\[profiles.{profile_name}]\n"
            f'template = "{template_ref}"\n'
            f'vat_rate = "{result.vat_rate}"\n'
            "# dokładnie jedno:\n"
            "# due_days = 14            # termin = data wystawienia + N dni\n"
            "# due_day_next_month = 15  # termin = D. dzień miesiąca po miesiącu rozliczeniowym[/]"
        )
        console.print("\n[dim]Albo powtórz komendę z --write-config, żeby skrypt dopisał to za Ciebie.[/]")
        return

    block = profile_block(
        name,
        template_ref,
        result.vat_rate,
        due_days=due_days,
        due_day_next_month=due_day_next_month,
    )
    try:
        config_path = append_profile(home, name, block, force=force)
    except (FileNotFoundError, ValueError) as error:
        err_console.print(f"[red]{error}[/]")
        raise typer.Exit(code=1) from None

    console.print(f"✅ Profil [bold]{name}[/] dopisany do {config_path}")

    declared = config_nip(config_path)
    if result.seller_nip and declared and result.seller_nip != declared:
        err_console.print(
            f"[yellow]⚠ NIP sprzedawcy w fakturze ({result.seller_nip}) różni się od nip w config.toml "
            f"({declared}) — KSeF odrzuci taką fakturę. Popraw jedno z nich.[/]"
        )
    console.print("\nSprawdź setup: [bold]uv run ksef-invoice doctor[/]")


@app.command()
def init(
    ctx: typer.Context,
    nip: str = typer.Option(..., "--nip", help="NIP sprzedawcy (10 cyfr; dozwolone separatory i prefiks PL)"),
    force: bool = typer.Option(False, "--force", help="Nadpisz istniejące config.toml / .env"),
) -> None:
    """Utwórz config.toml i .env. Profile dopisuje potem `templatize --write-config`."""
    home = _home(ctx)
    try:
        config_path = create_config(home, nip, force=force)
        env_path = create_env(home, force=force)
    except (FileExistsError, FileNotFoundError, ValueError) as error:
        err_console.print(f"[red]{error}[/]")
        raise typer.Exit(code=1) from None

    console.print(f"✅ {config_path}")
    console.print(f"✅ {env_path} (środowisko test, token pusty — na TEST niepotrzebny)")

    warning = suspicious_nip_warning(config_nip(config_path) or "")
    if warning:
        err_console.print(f"[yellow]⚠ {warning}[/]")

    console.print(
        "\nDalej: pobierz z KSeF XML swojej wcześniejszej faktury (Aplikacja Podatnika → faktura → "
        "pobierz XML) i zrób z niej profil:\n"
        "[bold]uv run ksef-invoice templatize faktura.xml --name klient --write-config --due-days 14[/]"
    )


@app.command()
def doctor(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="Wypisz wynik jako JSON (dla skryptów)."),
) -> None:
    """Sprawdź spójność setupu (config, profile, szablony, token, licznik) — nic nie wysyła."""
    home = _home(ctx)
    checks = run_checks(home)
    failed = [check for check in checks if check.status == FAIL]

    if as_json:
        # Świadomie bez rich: kontrakt maszynowy nie może zależeć od szerokości terminala.
        payload = {
            "home": str(home),
            "checks": [asdict(check) for check in checks],
            "failed": len(failed),
        }
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        if failed:
            raise typer.Exit(code=1)
        return

    # Katalog poza tabelą i z soft_wrap: kolumna rich-a obcina długie ścieżki wielokropkiem,
    # a przy trzech źródłach rozwiązania (flaga, KSEF_INVOICE_HOME, default) każde pytanie
    # o pomoc zaczyna się od „gdzie ono w ogóle szuka?".
    console.print(f"Katalog: [bold]{home}[/]", soft_wrap=True)
    symbols = {OK: "[green]✅[/]", WARN: "[yellow]⚠[/]", FAIL: "[red]❌[/]"}
    table = Table(title="Diagnostyka setupu", show_header=False)
    for check in checks:
        table.add_row(symbols[check.status], check.name, check.detail)
    console.print(table)

    if failed:
        err_console.print(f"\n[red]{len(failed)} problem(y) do naprawy przed wysyłką.[/]")
        raise typer.Exit(code=1)
    console.print(
        "\n✅ Setup wygląda dobrze. Podgląd faktury: [bold]ksef-invoice render --profile <profil> "
        "--month <RRRR-MM> --net <kwota>[/]"
    )


def main() -> None:
    """Wejście console_scriptu.

    Łapie dwa typy, które `load_config` dokumentuje jako swoje — bez tego każdy problem
    z configiem kończy się surowym tracebackiem, a to jest dokładnie ten stan, w którym
    startuje świeża instalacja (`render`/`send`/`pdf`/`status` wołają load_config bez try).
    typer.Exit i błędy click są z innych hierarchii, więc tego nie przechwytujemy.
    """
    try:
        app()
    except (FileNotFoundError, ValueError) as error:
        err_console.print(f"[red]{error}[/]")
        raise SystemExit(1) from None
