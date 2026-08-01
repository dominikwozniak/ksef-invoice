<div align="center">

# ksef-invoice

**Powtarzalne faktury sprzedażowe w KSeF — jeden profil, jedna komenda, FA(3).**

[![Test](https://github.com/dominikwozniak/ksef-invoice/actions/workflows/test.yaml/badge.svg)](https://github.com/dominikwozniak/ksef-invoice/actions/workflows/test.yaml)
[![Lint](https://github.com/dominikwozniak/ksef-invoice/actions/workflows/lint.yaml/badge.svg)](https://github.com/dominikwozniak/ksef-invoice/actions/workflows/lint.yaml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

[Szybki start](#szybki-start) · [Komendy](#komendy) · [Onboarding](#onboarding-jednorazowo) ·
[Bezpieczeństwo](#bezpieczeństwo) · [Problemy](#rozwiązywanie-problemów)

</div>

Wystawianie powtarzalnych faktur sprzedażowych w KSeF (oficjalne API 2.0, schema FA(3)).
Każda powtarzalna faktura to **profil** z własnym szablonem XML; dane prawie się nie
zmieniają — skrypt podmienia tylko numer, daty i kwoty. Numeracja jest wspólna dla
wszystkich profili: roczna sekwencja `FS/<licznik>/<rok>`.

<details>
<summary>Spis treści</summary>

- [Szybki start](#szybki-start)
- [Wymagania](#wymagania)
- [Instalacja](#instalacja)
- [Onboarding (jednorazowo)](#onboarding-jednorazowo)
- [Komendy](#komendy)
  - [Wystawianie](#wystawianie)
  - [Przeglądanie](#przeglądanie)
  - [Podgląd faktury (PDF/HTML)](#podgląd-faktury-pdfhtml)
  - [Środowisko testowe w przeglądarce](#środowisko-testowe-w-przeglądarce)
- [Konfiguracja](#konfiguracja)
- [Bezpieczeństwo](#bezpieczeństwo)
- [Rozwiązywanie problemów](#rozwiązywanie-problemów)
- [Rozwój projektu](#rozwój-projektu)
- [Jak to działa](#jak-to-działa)
- [Licencja](#licencja)

</details>

## Szybki start

Potrzebujesz dwóch rzeczy: [uv](https://docs.astral.sh/uv/) i **XML-a swojej wcześniejszej
faktury pobranego z KSeF**. Wszystko domyślnie idzie na środowisko **testowe** — produkcja
wymaga jawnej flagi `--prod`.

```bash
git clone git@github.com:dominikwozniak/ksef-invoice.git
cd ksef-invoice

# 1. config.toml + .env (NIP sprzedawcy, czyli Twojej firmy)
uv run ksef-invoice init --nip 5252000019

# 2. szablon z prawdziwej faktury + wpisanie profilu do config.toml
uv run ksef-invoice templatize ~/Downloads/faktura.xml \
    --name klient-a --write-config --due-day-next-month 15

# 3. weryfikacja setupu — nic nie wysyła
uv run ksef-invoice doctor

# 4. pierwsza faktura, na TEST (bez skutków prawnych)
uv run ksef-invoice send --profile klient-a --month 2026-07 --net 1000
```

Wolisz prowadzenie za rękę? Wpisz `/ksef-onboard` w Claude Code — patrz
[Onboarding](#onboarding-jednorazowo).

## Wymagania

- [uv](https://docs.astral.sh/uv/) — `brew install uv` albo
  `curl -LsSf https://astral.sh/uv/install.sh | sh`. Pythona 3.12 uv dociągnie sam,
  jeśli nie masz go w systemie.
- Konto w KSeF (na produkcji: token KSeF — patrz [Token KSeF](#token-ksef-produkcja)).

## Instalacja

```bash
git clone git@github.com:dominikwozniak/ksef-invoice.git
cd ksef-invoice
uv run ksef-invoice doctor   # pierwsze uruchomienie dociąga zależności (~40 paczek)
```

Na tym etapie `doctor` powie, że brakuje `config.toml` — to normalne, tworzy go onboarding
poniżej. Wszystkie komendy uruchamiaj **z katalogu repozytorium**: `config.toml`, `.env`,
`templates/` i `out/` skrypt trzyma w korzeniu projektu.

## Onboarding (jednorazowo)

Potrzebujesz jednej rzeczy: **XML-a swojej wcześniejszej faktury pobranego z KSeF**
(Aplikacja Podatnika → faktura → pobierz XML). Nie PDF-a, nie skanu.

### Z Claude Code — najprościej

Wpisz w Claude Code:

```
/ksef-onboard
```

Agent poprowadzi Cię przez konfigurację: zapyta o XML faktury i o regułę terminu płatności,
zbuduje szablon, wpisze profil i zweryfikuje setup. Wyjaśnia też ostrzeżenia, które
`templatize` wypisuje po drodze — a te warto przeczytać. **Skill nie wysyła faktur** i nie
dotyka tokenu KSeF; pierwszą wysyłkę robisz sam.

Zadziała też opis słowny, bez slasha — „skonfiguruj mi ten projekt", „dodaj nowego kontrahenta",
„mam XML faktury, co dalej".

### Ręcznie — te same trzy komendy

```bash
# 1. config.toml + .env (NIP sprzedawcy, czyli Twojej firmy — suma kontrolna jest sprawdzana)
uv run ksef-invoice init --nip 5252000019

# 2. szablon z prawdziwej faktury + wpisanie profilu do config.toml
#    dokładnie jedna reguła terminu: --due-days N ALBO --due-day-next-month D
uv run ksef-invoice templatize faktura.xml --name klient-a --write-config --due-day-next-month 15

# 3. weryfikacja setupu — nic nie wysyła
uv run ksef-invoice doctor
```

Po tym `doctor` mówi między innymi **ile kwot `--net` bierze każdy profil**, jaka jest stawka VAT
i termin płatności oraz jak stoi licznik numeracji. Kolejnego kontrahenta dodajesz samym krokiem 2.

Kroki wykonuj po kolei: `init` tworzy config **bez profili**, więc `doctor` uruchomiony między
krokiem 1 a 2 zgłosi „brak sekcji `[profiles.<nazwa>]`". To oczekiwane — profil dopisuje krok 2.

`init` **nie nadpisze** istniejącego `config.toml` ani `.env` (w tym drugim może siedzieć token) —
do tego trzeba jawnego `--force`. `config.toml`, `.env`, `templates/` i `out/` są w `.gitignore`
— zawierają dane prywatne. **Plik wejściowy `faktura.xml` też nie należy do repozytorium** —
patrz [Co zostaje lokalnie](#co-zostaje-lokalnie).

### Co robi `templatize`

Mapuje pola FA(3) na placeholdery (`{{issue_date}}`, `{{invoice_number}}`, `{{sale_date}}`,
`{{net}}`, `{{vat}}`, `{{gross}}`, `{{line1_net}}`, `{{line2_net}}`, …, `{{payment_due}}`,
`{{generated_at}}`) — po **ścieżkach elementów**, nie po wartościach, więc te same liczby
w różnych polach nie mylą się ze sobą. Wnioskuje stawkę VAT i liczbę pozycji oraz wyciąga NIP
sprzedawcy; z `--write-config` porównuje go dodatkowo z `nip` w `config.toml` i ostrzega przy
rozjeździe (KSeF odrzuciłby taką fakturę).

**Czytaj ostrzeżenia.** Dwa przypadki dają szablon po cichu niedokładny i wymagają ręcznej korekty
`templates/<profil>.xml`:

- **ilość ≠ 1** — kwota `--net` wchodzi i pod cenę jednostkową (P_9A), i pod wartość pozycji (P_11),
  co jest poprawne tylko przy ilości 1
- **wiele stawek VAT** — model obsługuje jedną stawkę; sumy pozostałych zostają jako sztywne kwoty

Bez `--write-config` komenda drukuje blok `[profiles.<nazwa>]` do samodzielnego skopiowania,
zamiast dopisywać go do `config.toml` — przydaje się, gdy chcesz najpierw zobaczyć wynik.
Szablon i tak powstaje: z `--name` ląduje w `templates/<nazwa>.xml`, a `--out <ścieżka>`
kieruje go gdzie indziej (bez obu — na stdout). `--force` **podmienia** istniejący profil
o tej nazwie. Wzór placeholderów jest też w `examples/template.example.xml`.

## Komendy

| Komenda | Co robi | Sieć / token |
|---|---|---|
| `render` | Generuje XML i wizualizację, waliduje XSD FA(3) — niczego nie wysyła | — |
| `send` | To co `render` plus wysyłka: numer KSeF i UPO | **KSeF** (na produkcji: token) |
| `pdf` | Odtwarza HTML/PDF dla faktury już leżącej w `out/` | — |
| `status` | Pokazuje zapisany status jednej faktury (profil + miesiąc) | — |
| `list` | Historia wystawionych faktur z lokalnego rejestru | — |
| `profiles` | Co jest w `config.toml`: liczba kwot `--net`, VAT, termin, szablon | — |
| `path` | Wypisuje ścieżkę do katalogu z artefaktami | — |
| `init` | Tworzy `config.toml` i `.env` | — |
| `templatize` | Robi szablon z faktury FA(3) i dopisuje profil do configu | — |
| `doctor` | Diagnostyka setupu: config, profile, szablony, token, licznik | — |

Sieci dotyka **wyłącznie `send`** — reszta czyta to, co masz na dysku. Pełną listę flag daje
`uv run ksef-invoice <komenda> --help`.

### Wystawianie

```bash
# Podgląd: generuje i waliduje XML (XSD FA(3)), niczego nie wysyła; numer przewidywany
uv run ksef-invoice render --profile klient-a --month 2026-07 --net 1000 --net 500

# Wysyłka (domyślnie środowisko TESTOWE — bez skutków prawnych)
# --net podaje się raz na pozycję faktury, w kolejności pozycji z szablonu
uv run ksef-invoice send --profile klient-a --month 2026-07 --net 1000 --net 500
uv run ksef-invoice send --profile klient-b --month 2026-07 --net 800

# Wysyłka PRODUKCYJNA — faktura ma skutki prawne!
uv run ksef-invoice send --profile klient-a --month 2026-07 --net 1000 --net 500 --prod

# Status wystawionej faktury (z lokalnego rejestru); --prod czyta wpis produkcyjny
uv run ksef-invoice status --profile klient-a --month 2026-07

# Diagnostyka setupu (profile, szablony, token, licznik) — nic nie wysyła
uv run ksef-invoice doctor
```

`--profile` możesz pominąć, gdy masz tylko jeden profil. `--seq N` działa też w `render` —
przydaje się, żeby zobaczyć, jak wyjdzie faktura o konkretnym numerze.

Artefakty lądują w `out/<env>/<profil>/<miesiąc>_<numer>/` — ukośniki w numerze zamieniane są
na myślniki, więc katalog wygląda tak: `out/test/klient-a/2026-07_FS-1-2026/`. `render` zapisuje
tam `invoice.xml` oraz `invoice.html` (i `invoice.pdf`, jeśli masz pango); `send` dokłada
`upo.xml` (UPO) i `meta.json` (numer KSeF, numery referencyjne).

### Przeglądanie

Trzy komendy czytają to, co masz w katalogu projektu. Żadna nie dotyka sieci i żadna nie
potrzebuje tokenu:

```bash
# Co jest w config.toml: ile kwot --net bierze profil, VAT, termin, który szablon
uv run ksef-invoice profiles

# Historia wystawionych faktur z out/ledger.json
uv run ksef-invoice list
uv run ksef-invoice list --profile klient-a --year 2026 --prod

# Ścieżka do artefaktów — pod podstawienie w shellu (na Linuksie: xdg-open)
open "$(uv run ksef-invoice path --profile klient-a --month 2026-07)"
open "$(uv run ksef-invoice path --month 2026-07 --prod)/invoice.pdf"   # --profile zbędny przy jednym profilu
```

`list` czyta **lokalny rejestr**, nie KSeF — pokazuje numer, który przydzieliło to narzędzie,
i działa offline. Kolumna `pliki` mówi, czy artefakty faktury nadal leżą w `out/`; `—` znaczy,
że rejestr o fakturze wie, ale katalogu już nie ma. Tabela świadomie nie ma numeru KSeF ani
ścieżki — pełne dane daje `--json`, a jedną fakturę `status --month`.

Po `send --force` za ten sam miesiąc istnieje **więcej niż jeden** katalog, a `path` wypisuje
je wszystkie, po jednym w wierszu — podstawienie `"$(…)"` z przykładu wyżej się wtedy wykłada.
Wywołaj wtedy samo `path` i wybierz katalog ręcznie.

`path`, `status` i `pdf` przyjmują też profil, który jest już tylko w rejestrze (bez sekcji
w `config.toml`) — historia zostaje po zakończeniu współpracy z klientem. Samo wystawianie
(`render`/`send`) wymaga profilu w konfiguracji, bo bez niego nie ma szablonu ani stawki VAT.

Odczyt wprost z KSeF (np. żeby zobaczyć faktury wystawione poza tym narzędziem) wymagałby
tokenu z uprawnieniem **`invoice_read`** — w KSeF jest to zakres rozdzielny od `invoice_write`,
którym się wystawia. Nie ma tego jeszcze.

### Podgląd faktury (PDF/HTML)

`render` i `send` zapisują wizualizację same; dla wcześniejszej faktury:

```bash
uv run ksef-invoice pdf --profile klient-a --month 2026-06   # --prod dla produkcyjnej
```

**HTML powstaje zawsze.** PDF to dodatek — potrzebuje bibliotek natywnych WeasyPrint (pango).
Bez nich `doctor` odnotuje to jako opcję, a nie usterkę, i **wszystko poza samym PDF-em działa
normalnie**: render, walidacja XSD, wysyłka, UPO.

<details>
<summary><b>Chcesz też PDF — instalacja pango</b></summary>

Potrzebne jest pango i jego zależności — cairo ani gdk-pixbuf **nie** są potrzebne:

| System | Instalacja |
|---|---|
| macOS | `brew install pango` |
| Debian/Ubuntu | `sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libfontconfig1` |
| Fedora | `sudo dnf install pango harfbuzz fontconfig` |
| Arch | `sudo pacman -S pango harfbuzz fontconfig` |
| Windows | [GTK3 runtime](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows) |

Sprawdzenie: `uv run ksef-invoice doctor` ma w wierszu **PDF (opcjonalny)** napisać
„WeasyPrint działa".

Na macOS skrypt sam dokłada katalog bibliotek Homebrew (`/opt/homebrew/lib` na Apple Silicon,
`/usr/local/lib` na Intelu) do ścieżki wyszukiwania — samo `brew install pango` wystarcza.
Powód, dla którego to potrzebne: Python z Homebrew ma prefiks Homebrew we własnej domyślnej
liście, ale interpreter pobrany przez uv albo z python.org już nie, więc bez tego widziałby
tylko `/usr/local/lib`. Jeśli trzymasz Homebrew pod nietypowym prefiksem, wskaż go ręcznie:

```bash
export DYLD_LIBRARY_PATH="$(brew --prefix)/lib"   # do .zshrc / .bash_profile
```

Na Linuksie analogicznie działa `LD_LIBRARY_PATH`, gdy pango leży poza standardowymi
katalogami (nix, conda, własna kompilacja).

</details>

### Środowisko testowe w przeglądarce

Aplikacja Podatnika KSeF 2.0 — wersja testowa: <https://ap-test.ksef.mf.gov.pl>.
Na środowisku testowym logujesz się **bez profilu zaufanego** (tryb testowego
uwierzytelnienia): podaj NIP kontekstu (ten z `config.toml`) — zobaczysz wszystkie faktury
wysłane przez skrypt na TEST, z podglądem i pobieraniem XML/HTML/PDF. Faktury testowe nie mają
skutków prawnych; każdy może się tam uwierzytelnić dowolnym NIP-em, więc nie wysyłaj na TEST
prawdziwych kwot.

## Konfiguracja

Pełna, skomentowana referencja leży w `examples/config.example.toml`. Poniżej to, co warto
znać na start.

### Pozycje, VAT i terminy płatności (per profil)

- **Pozycje**: każda kwota `--net` odpowiada placeholderowi `{{line1_net}}`, `{{line2_net}}`, …
  w szablonie (kolejność jak na fakturze). Sumy `{{net}}`/`{{vat}}`/`{{gross}}` liczą się same.
  Zmiana opisów lub liczby pozycji = edycja `templates/<profil>.xml`.
- **VAT**: `vat_rate = "23"` (procent) albo `"np"` — faktura nie podlega VAT
  (np. odwrotne obciążenie przy usługach dla kontrahenta z UE): VAT brak, brutto = netto.
- **Termin płatności** — dokładnie jedna reguła w profilu:
  `due_days = N` (wystawienie + N dni) albo `due_day_next_month = D`
  (D. dzień miesiąca po miesiącu rozliczeniowym). Przy spóźnionym wystawieniu skrypt
  ostrzeże, jeśli termin wypada przed datą wystawienia.

Klucze `vat_rate`, `issue_day` i regułę terminu można podać raz na górze `config.toml` jako
domyślne dla wszystkich profili; profil je nadpisuje. Uwaga: podanie w profilu *którejkolwiek*
reguły terminu odrzuca **obie** reguły domyślne. Gdy nie ma jej nigdzie, obowiązuje
`due_days = 14`, a gdy nie ma `vat_rate` — `"23"`.

### Numeracja

Numer wylicza się z rocznego licznika w `out/ledger.json`, wspólnego dla wszystkich profili,
osobnego per środowisko. Licznik rośnie przy każdej udanej wysyłce. Format ustawia
`number_format` w `config.toml` (domyślnie `"FS/{seq}/{year}"`; dostępne też `{month}`
i `{month02}` — licznik pozostaje roczny, nie resetuje się co miesiąc).

**Przy pierwszej produkcyjnej wysyłce zasiej licznik flagą `--seq N`** (numer kolejnej faktury,
uwzględniający faktury wystawione w tym roku poza skryptem) — kolejne wysyłki kontynuują
automatycznie. `--seq` służy też do korekty przy rozjeździe.

## Bezpieczeństwo

### Test kontra produkcja

Domyślnie wszystko idzie na **środowisko testowe**; produkcja wymaga jawnego `--prod`
**albo** `KSEF_ENV=prod` w `.env`. Przed każdą wysyłką skrypt pokazuje podsumowanie
(ze środowiskiem — `PROD` na czerwono) i pyta o potwierdzenie; `--yes` je pomija.

⚠️ **`KSEF_ENV=prod` na stałe w `.env` znosi zabezpieczenie „domyślnie test"**: od tej chwili
`send` idzie na produkcję **bez** `--prod`, a `render`, `status` i katalog `out/` też pracują
na produkcji. Zostaje tylko czerwone `PROD` w podsumowaniu i pytanie o potwierdzenie.
Uwaga też na kolejność: zmienna wyeksportowana w shellu (np. w `.zshrc`) **wygrywa** z `.env`.

Wartość `KSEF_ENV=demo` jest obsługiwana przez kod, ale nieudokumentowana i bez własnej flagi —
używaj `test` albo `prod`.

### Token KSeF (produkcja)

1. Zaloguj się do Aplikacji Podatnika KSeF: <https://ksef.mf.gov.pl> (profil zaufany / e-dowód).
2. Wybierz kontekst swojego NIP.
3. Wygeneruj **token** z uprawnieniem do wystawiania faktur (InvoiceWrite).
4. Wpisz go do `.env` jako `KSEF_TOKEN=...`. Środowisko zostaw na `KSEF_ENV=test`
   i wybieraj produkcję flagą `--prod`.

Token daje pełne prawo wystawiania faktur w Twoim imieniu — traktuj jak hasło; ogranicz do
niego dostęp (`chmod 600 .env`). Na środowisku testowym token nie jest potrzebny (używany jest
certyfikat testowy generowany przez SDK dla NIP-u z `config.toml`).

### Co blokuje pomyłkę

- Rejestr `out/ledger.json` blokuje drugą fakturę z tego samego profilu za ten sam
  miesiąc (`--force` wymusza) oraz drugie użycie tego samego numeru.
- Pierwsza produkcyjna wysyłka w roku jest blokowana, dopóki nie zasiejesz licznika
  flagą `--seq N` (albo świadomie nie wymusisz `--force`).
- XML jest walidowany oficjalnym XSD FA(3) przed wysyłką; NIP sprzedawcy w szablonie
  musi zgadzać się z NIP-em w `config.toml`.
- **KSeF odrzuca faktury z datą wystawienia (P_1) w przyszłości** — domyślnie
  `issue_day = "today"` (data wystawienia = dzień uruchomienia). Data sprzedaży (P_6)
  może być w przyszłości (koniec miesiąca rozliczeniowego).
- Faktury w KSeF są **nieusuwalne** — pomyłkę na produkcji prostuje się fakturą korygującą.

### Co zostaje lokalnie

Repozytorium jest publiczne, ale **Twoje dane nigdy do niego nie trafiają**. Twój NIP, adres,
dane klientów, kwoty i szablony żyją wyłącznie lokalnie w `config.toml`, `.env` i `templates/`
(oraz w `out/`) — wszystkie w `.gitignore`. Nie commituj tych plików. Zawartość pokazują
[`profiles`, `list` i `path`](#przeglądanie); `--json` w `profiles` i `list` **nie** wynosi
tokenu, mimo że `load_config` wciąga go do konfiguracji.

Pamiętaj też o **pliku wejściowym**: `faktura.xml` pobrana z KSeF na potrzeby `templatize`
zawiera komplet danych — NIP-y obu stron, adresy, numer konta i kwoty. `.gitignore` wyłapuje
XML-e z korzenia repo, ale najbezpieczniej trzymać ją poza katalogiem projektu i podać ścieżkę:
`uv run ksef-invoice templatize ~/Downloads/faktura.xml --name klient-a …`.

Na środowisku testowym nie wysyłaj prawdziwych kwot (każdy może się tam uwierzytelnić
dowolnym NIP-em).

## Rozwiązywanie problemów

### Instalacja i setup

| Objaw | Co zrobić |
|---|---|
| `command not found: uv` | `brew install uv` albo `curl -LsSf https://astral.sh/uv/install.sh \| sh`; potem otwórz nowy terminal. |
| `Brak .../config.toml` | Jesteś poza katalogiem repo albo przed onboardingiem — `cd` do klonu i `uv run ksef-invoice init --nip <NIP>`. |
| `config.toml: brak sekcji [profiles.<nazwa>]` | `init` tworzy config bez profili. Dopisz profil krokiem 2: `templatize … --write-config`. |
| `NIP … ma niepoprawną sumę kontrolną` | Literówka w NIP-ie — podaj go jeszcze raz. |
| `doctor`: `–` `PDF (opcjonalny)` | To nie usterka, tylko niewłączona opcja: PDF nie powstaje, wszystko inne działa. Chcesz PDF → [instalacja pango](#podgląd-faktury-pdfhtml). |

### Szablon i profil

| Objaw | Co zrobić |
|---|---|
| `doctor`: ⚠ `NIP … to powtórzona cyfra` | Masz w configu NIP-atrapę (np. z `examples/`). Na TEST grozi to błędem 440 (duplikat) — wstaw prawdziwy NIP. |
| `NIP sprzedawcy w szablonie … różni się od NIP w config.toml` | KSeF odrzuciłby taką fakturę. Ustal, która wartość jest prawdziwa, i popraw drugą. |
| `Nie udało się przetworzyć <plik>` | XML nie przechodzi walidacji XSD FA(3) — to nie jest faktura FA(3) pobrana z KSeF. |
| `Podano N kwot --net, a szablon … nie ma placeholdera {{lineN_net}}` | Profil ma inną liczbę pozycji — `doctor` pokazuje, ile kwot bierze każdy profil. |

### Wysyłka i numeracja

| Objaw | Co zrobić |
|---|---|
| `To pierwsza produkcyjna wysyłka w <rok>` | Zasiej licznik: `--seq <numer kolejnej faktury>`. |
| `Miesiąc … — oczekiwany format RRRR-MM` | `--month 2026-07`, nie `07-2026`. |
| Faktura wystawiona w KSeF, ale `status` jej nie widzi | Wpis w `out/ledger.json` nie powstał (np. przerwanie po wysyłce). Sprawdź fakturę w Aplikacji Podatnika **zanim** ponowisz — ponowna wysyłka da błąd 440 (duplikat). |

## Rozwój projektu

```bash
uv run pytest            # testy
uv run ruff check        # linter (błędy, nieużywane importy, sortowanie importów)
uv run ruff format       # formatowanie (odpowiednik prettiera)
```

Te same bramki chodzą w CI na każdym pushu i PR-ze: testy na Pythonie **3.12 i 3.13**,
`ruff check`, `ruff format --check` oraz skan sekretów (trufflehog).

## Jak to działa

- [ksef2](https://github.com/artpods56/ksef2) — community SDK KSeF API 2.0 (auth, szyfrowanie
  AES-256/RSA-OAEP, sesje online, UPO); dolna granica wersji w `pyproject.toml`, dokładna
  wersja przypięta w `uv.lock`
- oficjalne XSD FA(3) (bundlowane w ksef2) do walidacji offline
- typer + rich (CLI), lxml (XML), WeasyPrint przez ksef2 (PDF), pytest, ruff (lint + format)

Pliki przykładowe (`config.example.toml`, `.env.example`, `template.example.xml`) leżą w `examples/`.

Decyzje projektowe, wnioski z integracji z KSeF i to, co świadomie zostało poza zakresem —
w [`SPEC.md`](SPEC.md). Scenariusz onboardingowego agenta:
[`.claude/skills/ksef-onboard/SKILL.md`](.claude/skills/ksef-onboard/SKILL.md).

Dokumentacja API: [CIRFMF/ksef-docs](https://github.com/CIRFMF/ksef-docs),
środowiska: test `api-test.ksef.mf.gov.pl`, demo `api-demo.ksef.mf.gov.pl`, prod `api.ksef.mf.gov.pl`.

## Licencja

MIT — zobacz [LICENSE](LICENSE).
