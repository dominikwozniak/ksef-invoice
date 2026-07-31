# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/), wersjonowanie
[SemVer](https://semver.org/lang/pl/). MINOR = zmiana powierzchni CLI (nowa komenda, nowa
flaga), PATCH = poprawki.

## [1.0.0] — 2026-07-31

Pierwsza wersja instalowalna jako narzędzie: `uv tool install ksef-invoice`. Wcześniej CLI
działało wyłącznie z wnętrza klonu repozytorium przez `uv run`.

Wersja 1.0.0, a nie 0.2.0, bo przez ten kod przeszły już produkcyjne faktury — na 0.x
`uv tool upgrade` mógłby komuś zmienić zachowanie w środku roku podatkowego.

### Migracja z układu w repozytorium

**Stan przenosi się ręcznie.** `config.toml`, `.env`, `templates/` i `out/` leżały dotąd
w katalogu repozytorium, a teraz domyślnie w `~/.ksef-invoice`. `doctor` wykryje stary układ
i wypisze przepis. Kolejność ma znaczenie, bo `out/ledger.json` jest źródłem prawdy dla
numeracji faktur:

```bash
ksef-invoice --home ~/sciezka/do/klonu doctor   # zapisz licznik, np. „licznik prod: 9"
mkdir -m 700 -p ~/.ksef-invoice
cp -a config.toml .env templates out ~/.ksef-invoice/    # cp, NIE mv
chmod 600 ~/.ksef-invoice/.env
ksef-invoice doctor                             # ten sam licznik? dopiero wtedy usuń kopie
```

Utracony ledger jest głośny (pierwsza produkcyjna wysyłka w roku odmówi i poprosi o `--seq`),
ale ledger **nieaktualny** jest cichy i kończy się duplikatem numeru faktury.

### Dodane

- `uv tool install ksef-invoice` jako udokumentowana instalacja; nazwa komendy `ksef-invoice`
  wszędzie zamiast `uv run ksef-invoice`.
- Globalna flaga `--home` i zmienna `KSEF_INVOICE_HOME`. Precedencja: flaga > zmienna >
  `~/.ksef-invoice`. Katalog jest jeden na użytkownika i **nie** jest szukany w górę od
  katalogu roboczego — numer faktury nie może zależeć od tego, gdzie stoi shell.
- `--version`, `python -m ksef_invoice`, `doctor --json` (`{home, checks, failed}`).
- `doctor` wypisuje rozwiązany katalog roboczy i rozróżnia trzy stany PDF-a.
- Extra `[pdf]` — instalacja `ksef-invoice[pdf]` dla lokalnego PDF-a.

### Zmienione

- **Domyślna instalacja nie ma żadnych zależności systemowych.** WeasyPrint (11 pakietów,
  ~41 MB) przeniesiony do opcjonalnej extry `[pdf]`, bo wymaga natywnego `pango`, którego
  nie da się zainstalować pipem. `invoice.html` powstaje zawsze i ma teraz CSS druku z SDK,
  więc Cmd/Ctrl+P daje ten sam układ A4.
- Błędy i ostrzeżenia idą na stderr, payload na stdout — `doctor --json | jq` nie psuje się
  od ostrzeżenia wypadającego w środku.
- `lxml` i `rich` zadeklarowane jawnie; dotąd wchodziły tylko tranzytywnie.
- `.env` dostaje prawa `600`, katalog roboczy `700`.
- Katalog `examples/` jest wyłącznie dokumentacją — narzędzie nie czyta go w trakcie działania.

### Naprawione

- **PDF nie generował się pod interpreterem innym niż ten z Homebrew.** WeasyPrint szuka
  `pango` przez `ctypes.util.find_library`, a to na macOS czyta
  `ctypes.macholib.dyld.DEFAULT_LIBRARY_FALLBACK` — listę, którą Python z Homebrew ma
  załataną o własny prefiks, a czysty CPython (m.in. ten pobierany przez `uv`) nie. Narzędzie
  dokłada tę ścieżkę samo, więc `export DYLD_LIBRARY_PATH=/opt/homebrew/lib` nie jest już
  potrzebny (i nigdy nie działał z `/usr/bin/python3` — SIP strippuje tę zmienną). Wyłącznik:
  `KSEF_INVOICE_NO_DYLD_FIXUP=1`.
- **`templatize --write-config` uruchomione poza korzeniem repo raportowało sukces i zostawiało
  niedziałający profil** — szablon zapisywał się względem katalogu roboczego, a `config.toml`
  składa ścieżkę względem katalogu roboczego narzędzia.
- **`init` nie działał po instalacji z paczki** — `create_env` czytał `examples/.env.example`
  w trakcie działania, a `examples/` nie trafia do wheela.
- **`init` na czystej maszynie kończył się surowym `FileNotFoundError`** — zapis pliku nie
  tworzył katalogu nadrzędnego.
- **Problem z konfiguracją kończył się tracebackiem** w `render`/`send`/`pdf`/`status`; teraz
  jedna linia na stderr i kod wyjścia 1.
- `render` i `pdf` wskazywały `invoice.pdf` nawet wtedy, gdy PDF nie powstał.
- `doctor` gubił `[pdf]` z instrukcji instalacji, bo `rich` traktował to jako znacznik stylu.

### Wewnętrznie

- Pierwsze testy warstwy CLI (`typer.testing.CliRunner`), w tym guardów `send` chroniących
  numerację faktur — dotąd `cli.py` nie miał żadnego pokrycia.
- Trzy bariery w testach: token z shella nie wchodzi do konfiguracji, żaden test nie może
  wysłać faktury do KSeF, prawdziwy `config.toml`/`.env`/`ledger.json` musi być po sesji
  nietknięty.
- CI (GitHub Actions): macOS i Linux × instalacja z extrą `[pdf]` i bez niej, smoke instalacji
  z wheela od zera oraz osobny job na czystym CPythonie, bo tylko tam widać regresję poprawki
  `pango`. Publikacja przez PyPI Trusted Publishing (OIDC).

## Wcześniej

Historia przed 1.0.0 nie była prowadzona — projekt działał jako skrypt uruchamiany z klonu
repozytorium. Zobacz `git log`.
