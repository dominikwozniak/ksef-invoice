"""CLI: render / send / status."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import Config, Profile, load_config
from .invoice import Invoice, build_invoice, check_seller_nip, format_number, validate_fa3
from .ledger import Ledger
from .send import send_invoice
from .templatize import templatize as run_templatize
from .visualize import to_html, to_pdf

app = typer.Typer(help="Wystawianie powtarzalnych faktur sprzedażowych w KSeF.", no_args_is_help=True)
console = Console()


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
        console.print(
            "[yellow]Uwaga: termin płatności wypada przed datą wystawienia "
            "(faktura wystawiana po terminie wynikającym z reguły profilu).[/]"
        )


def _render(config: Config, profile: Profile, month: str, nets: list[Decimal], number: str) -> Invoice:
    invoice = build_invoice(month, nets, profile, number=number)
    validate_fa3(invoice.xml)
    check_seller_nip(invoice.xml, config.nip)
    return invoice


def _write_visualizations(target: Path, xml: bytes) -> None:
    """Zapisuje invoice.html (zawsze) i invoice.pdf (jeśli WeasyPrint dostępny)."""
    (target / "invoice.html").write_bytes(to_html(xml))
    pdf = to_pdf(xml)
    if pdf:
        (target / "invoice.pdf").write_bytes(pdf)
    else:
        console.print(
            "[yellow]PDF pominięty — brak bibliotek WeasyPrint (macOS: brew install pango). HTML zapisany.[/]"
        )


NET_HELP = (
    "Kwota netto pozycji; powtórz dla kolejnych pozycji w kolejności z faktury, np. --net 1000 --net 500"
)


@app.command()
def render(
    month: str = typer.Option(..., "--month", help="Miesiąc faktury, np. 2026-07"),
    net: list[str] = typer.Option(..., "--net", help=NET_HELP),
    profile: str = typer.Option(None, "--profile", help="Nazwa profilu z config.toml"),
    seq: int = typer.Option(None, "--seq", help="Wymuś numer w sekwencji (domyślnie: kolejny z ledgera)"),
) -> None:
    """Wygeneruj i zwaliduj XML faktury bez wysyłania (numer: przewidywany, bez rezerwacji)."""
    config = load_config()
    selected = _resolve_profile(config, profile)
    ledger = Ledger(config.out_dir / "ledger.json")
    _, _, number = _allocate_number(config, ledger, month, seq)

    invoice = _render(config, selected, month, _parse_nets(net), number)
    _print_summary(config, selected, invoice)

    target = _invoice_dir(config, selected, invoice)
    target.mkdir(parents=True, exist_ok=True)
    xml_path = target / "invoice.xml"
    xml_path.write_bytes(invoice.xml)
    _write_visualizations(target, invoice.xml)
    console.print(f"\n✅ XML zwalidowany (XSD FA(3)) i zapisany: [bold]{xml_path}[/]")
    console.print(f"Podgląd: {target / 'invoice.pdf'}")
    console.print("Numer jest przewidywany — rezerwacja następuje dopiero przy send.")


@app.command()
def send(
    month: str = typer.Option(..., "--month", help="Miesiąc faktury, np. 2026-07"),
    net: list[str] = typer.Option(..., "--net", help=NET_HELP),
    profile: str = typer.Option(None, "--profile", help="Nazwa profilu z config.toml"),
    seq: int = typer.Option(None, "--seq", help="Wymuś numer w sekwencji (domyślnie: kolejny z ledgera)"),
    prod: bool = typer.Option(False, "--prod", help="Wyślij na PRODUKCJĘ (skutki prawne!)."),
    yes: bool = typer.Option(False, "--yes", help="Pomiń interaktywne potwierdzenie."),
    force: bool = typer.Option(False, "--force", help="Wyślij mimo istniejącego wpisu w ledgerze."),
) -> None:
    """Wygeneruj, zwaliduj i wyślij fakturę do KSeF; zapisz numer KSeF i UPO."""
    config = load_config()
    if prod:
        config = Config(**{**config.__dict__, "environment": "prod"})
    selected = _resolve_profile(config, profile)

    ledger = Ledger(config.out_dir / "ledger.json")
    existing = ledger.get(config.environment, selected.name, month)
    if existing and not force:
        console.print(
            f"[red]Faktura {selected.name} za {month} ({config.environment}) już wystawiona: "
            f"{existing.get('number')} → {existing.get('ksef_number')}.[/]\n"
            "Użyj --force, jeśli świadomie chcesz wysłać kolejną."
        )
        raise typer.Exit(code=1)

    used_seq, year, number = _allocate_number(config, ledger, month, seq)

    clash = ledger.number_exists(config.environment, number)
    if clash and not force:
        console.print(
            f"[red]Numer {number} jest już użyty w ledgerze ({config.environment}): "
            f"profil {clash[0]}, miesiąc {clash[1]}.[/]\n"
            "Nie podawaj --seq drugiej fakturze tego samego miesiąca (licznik dolicza się sam). "
            "--force wysyła mimo to."
        )
        raise typer.Exit(code=1)
    if config.environment == "prod" and seq is None and not ledger.year_started("prod", year) and not force:
        console.print(
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
        console.print(f"\n[red]Wysyłka nie powiodła się:[/] {error}")
        console.print(
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
        console.print("[yellow]UPO jeszcze niedostępne — sprawdź później w Aplikacji Podatnika.[/]")
    console.print(f"Artefakty: {target}")


@app.command()
def pdf(
    month: str = typer.Option(..., "--month", help="Miesiąc faktury, np. 2026-07"),
    profile: str = typer.Option(None, "--profile", help="Nazwa profilu z config.toml"),
    prod: bool = typer.Option(False, "--prod", help="Faktura produkcyjna."),
) -> None:
    """Wygeneruj HTML+PDF dla już zapisanej faktury z out/ (np. wysłanej wcześniej)."""
    config = load_config()
    selected = _resolve_profile(config, profile)
    environment = "prod" if prod else config.environment
    matches = sorted((config.out_dir / environment / selected.name).glob(f"{month}_*/invoice.xml"))
    if not matches:
        console.print(f"Brak zapisanej faktury {selected.name} za {month} ({environment}) w out/.")
        raise typer.Exit(code=1)
    for xml_path in matches:
        _write_visualizations(xml_path.parent, xml_path.read_bytes())
        console.print(f"✅ {xml_path.parent / 'invoice.pdf'}")


@app.command()
def status(
    month: str = typer.Option(..., "--month", help="Miesiąc faktury, np. 2026-07"),
    profile: str = typer.Option(None, "--profile", help="Nazwa profilu z config.toml"),
    prod: bool = typer.Option(False, "--prod", help="Sprawdź wpis produkcyjny."),
) -> None:
    """Pokaż zapisany status faktury za dany miesiąc (z lokalnego ledgera)."""
    config = load_config()
    selected = _resolve_profile(config, profile)
    environment = "prod" if prod else config.environment
    entry = Ledger(config.out_dir / "ledger.json").get(environment, selected.name, month)
    if not entry:
        console.print(f"Brak wpisu {selected.name} za {month} ({environment}).")
        raise typer.Exit(code=1)
    console.print_json(json.dumps(entry, ensure_ascii=False))


@app.command()
def templatize(
    input_xml: Path = typer.Argument(..., help="XML faktury FA(3) pobrany z KSeF (Aplikacja Podatnika)"),
    name: str = typer.Option(None, "--name", help="Nazwa profilu; bez --out zapisze do templates/<name>.xml"),
    out: Path = typer.Option(None, "--out", help="Ścieżka wyjściowego szablonu (domyślnie stdout)"),
) -> None:
    """Zrób szablon z placeholderami z pobranej faktury (onboarding nowego profilu)."""
    try:
        result = run_templatize(input_xml.read_bytes())
    except Exception as error:
        console.print(f"[red]Nie udało się przetworzyć {input_xml}:[/] {error}")
        raise typer.Exit(code=1) from None

    target = out or (Path("templates") / f"{name}.xml" if name else None)
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(result.xml)
        console.print(
            f"✅ Szablon zapisany: [bold]{target}[/] ({result.line_count} poz., vat_rate={result.vat_rate!r})"
        )
    else:
        console.print(result.xml.decode("utf-8"))

    for warning in result.warnings:
        console.print(f"[yellow]⚠ {warning}[/]")

    profile_name = name or "moj-profil"
    template_ref = str(target) if target is not None else f"templates/{profile_name}.xml"
    console.print("\nDopisz profil do [bold]config.toml[/] (uzupełnij regułę terminu płatności):")
    console.print(
        f"[dim]\\[profiles.{profile_name}]\n"
        f'template = "{template_ref}"\n'
        f'vat_rate = "{result.vat_rate}"\n'
        "# dokładnie jedno:\n"
        "# due_days = 14            # termin = data wystawienia + N dni\n"
        "# due_day_next_month = 15  # termin = D. dzień miesiąca po miesiącu rozliczeniowym[/]"
    )
