# ksef-invoice

Wystawianie powtarzalnych faktur sprzedażowych w KSeF (oficjalne API 2.0, schema FA(3)).
Każda powtarzalna faktura to **profil** z własnym szablonem XML; dane prawie się nie
zmieniają — skrypt podmienia tylko numer, daty i kwoty. Numeracja jest wspólna dla
wszystkich profili: roczna sekwencja `FS/<licznik>/<rok>`.

## Instalacja

```bash
uv tool install ksef-invoice
```

To wszystko. Nie potrzebujesz wcześniej Pythona — `uv` dociągnie własny (macOS ma
w systemie 3.9, a tu potrzebne jest 3.12+). Nie masz `uv`?
`curl -LsSf https://astral.sh/uv/install.sh | sh` albo `brew install uv`.

Sprawdzenie: `ksef-invoice --version`. Aktualizacja: `uv tool upgrade ksef-invoice`.
Odinstalowanie: `uv tool uninstall ksef-invoice` (dane w `~/.ksef-invoice` zostają).

Domyślna instalacja nie wymaga **żadnych** bibliotek systemowych. Jedyne wymaganie poza
tym to konto w KSeF (na produkcji dodatkowo token — patrz niżej).

<details>
<summary>Inne sposoby instalacji</summary>

```bash
pipx install ksef-invoice                                           # jeśli masz już pipx i Pythona 3.12+
uv tool install git+https://github.com/dominikwozniak/ksef-invoice  # wprost z gita
git clone … && cd ksef-invoice && uv sync --extra pdf               # do rozwoju: uv run ksef-invoice …
```

Nie używaj `pip install --user` — brak izolacji, a na nowszych systemach zablokuje to
PEP 668 (`externally-managed-environment`).
</details>

### PDF (opcjonalnie)

`render` i `send` zawsze zapisują `invoice.html` — oficjalną wizualizację KSeF, z CSS-em
druku, więc Cmd/Ctrl+P → „Zapisz jako PDF" daje ten sam układ A4 co plik generowany
lokalnie. Jeśli chcesz od razu `invoice.pdf`, dołóż bibliotekę systemową i wariant `[pdf]`:

```bash
brew install pango                                    # macOS
# sudo apt install libpango-1.0-0 libpangoft2-1.0-0   # Debian/Ubuntu
uv tool install --force 'ksef-invoice[pdf]'
```

PDF jest opcjonalny, bo WeasyPrint wymaga natywnego `pango`, którego nie da się
zainstalować pipem — bez tego podziału każda instalacja ciągnęłaby 11 pakietów za
funkcję działającą tylko u części osób. `ksef-invoice doctor` powie, w którym trybie jesteś.

## Gdzie leżą Twoje dane

Wszystko w jednym katalogu: **`~/.ksef-invoice/`** (tworzy go `init`, z prawami `700`).

```
config.toml      profile faktur i NIP sprzedawcy
.env             środowisko i token KSeF (prawa 600 — traktuj jak hasło)
templates/       szablony FA(3) — dane kontrahentów
out/             wystawione faktury, UPO, meta.json
out/ledger.json  licznik numeracji — źródło prawdy dla numerów faktur
```

To zwykłe pliki — przeglądasz je w Finderze, a szablony edytujesz w edytorze. Z CLI zawartość
pokazują [`profiles`, `list` i `path`](#przegl%C4%85danie).

Jeden katalog do backupu. Chcesz go trzymać w Dropboksie albo mieć osobny na inną firmę:

```bash
export KSEF_INVOICE_HOME=~/Dropbox/ksef-invoice
```

albo jednorazowo `ksef-invoice --home <katalog> doctor` — flaga idzie **przed** komendą.
Precedencja: `--home` > `KSEF_INVOICE_HOME` > `~/.ksef-invoice`.

Katalog jest jeden na użytkownika i **nie** jest szukany w górę od katalogu roboczego —
świadomie. Numer faktury to roczna sekwencja z `out/ledger.json`; gdyby zależał od tego,
gdzie stoi shell, przypadkowy pusty ledger wystartowałby numerację od `FS/1` po raz drugi.

<details>
<summary>Migracja ze starszej wersji (stan trzymany w klonie repo)</summary>

Wcześniej `config.toml`, `.env`, `templates/` i `out/` leżały w katalogu repozytorium.
`doctor` sam wypisze ten przepis, gdy wykryje stary układ. Kolejność ma znaczenie:

```bash
# 1. sprawdź, co widzi narzędzie w starym katalogu — zapisz licznik
ksef-invoice --home ~/sciezka/do/klonu doctor    # np. „licznik prod: 9"

# 2. skopiuj (cp, NIE mv — oryginał zostaje jako kopia zapasowa)
mkdir -m 700 -p ~/.ksef-invoice
cp -a config.toml .env templates out ~/.ksef-invoice/
chmod 600 ~/.ksef-invoice/.env

# 3. ten sam licznik bez flagi? dopiero wtedy usuń kopie ze starego katalogu
ksef-invoice doctor
```

Licznik musi się zgadzać po obu stronach. Utracony ledger jest głośny (pierwsza
produkcyjna wysyłka w roku odmówi i poprosi o `--seq`), ale ledger **nieaktualny** jest
cichy i kończy się duplikatem numeru — dlatego `cp -a` i weryfikacja, nigdy `mv`.
</details>

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
ksef-invoice init --nip 5252000019

# 2. szablon z prawdziwej faktury + wpisanie profilu do config.toml
#    dokładnie jedna reguła terminu: --due-days N ALBO --due-day-next-month D
ksef-invoice templatize faktura.xml --name klient-a --write-config --due-day-next-month 15

# 3. weryfikacja setupu — nic nie wysyła
ksef-invoice doctor
```

Po tym `doctor` mówi między innymi **ile kwot `--net` bierze każdy profil**, jaka jest stawka VAT
i termin płatności oraz jak stoi licznik numeracji. Kolejnego kontrahenta dodajesz samym krokiem 2.

`init` **nie nadpisze** istniejącego `config.toml` ani `.env` (w tym drugim może siedzieć token) —
do tego trzeba jawnego `--force`.

### Autouzupełnianie i skrypty

```bash
ksef-invoice --install-completion    # uzupełnianie nazw komend i flag w Twoim shellu
ksef-invoice doctor --json           # wynik diagnostyki maszynowo: {home, checks, failed}
ksef-invoice profiles --json         # profile z config.toml (bez tokenu)
ksef-invoice list --json | jq -r '.invoices[].dir'   # katalogi wszystkich faktur
```

Kody wyjścia: `0` — OK, `1` — błąd (brak configu, guard numeracji, `doctor` zgłosił FAIL),
`2` — błąd użycia (nieznana flaga). Błędy i ostrzeżenia idą na stderr, więc
`ksef-invoice doctor --json | jq` nie psuje się od ostrzeżenia wypadającego w środku.

### Co robi `templatize`

Mapuje pola FA(3) na placeholdery (`{{issue_date}}`, `{{invoice_number}}`, `{{sale_date}}`,
`{{net}}`, `{{vat}}`, `{{gross}}`, `{{line1_net}}`, `{{line2_net}}`, …, `{{payment_due}}`,
`{{generated_at}}`) — po **ścieżkach elementów**, nie po wartościach, więc te same liczby
w różnych polach nie mylą się ze sobą. Wnioskuje stawkę VAT i liczbę pozycji, wyciąga NIP
sprzedawcy i ostrzega, gdy nie zgadza się z `config.toml`.

**Czytaj ostrzeżenia.** Dwa przypadki dają szablon po cichu niedokładny i wymagają ręcznej korekty
`templates/<profil>.xml`:

- **ilość ≠ 1** — kwota `--net` wchodzi i pod cenę jednostkową (P_9A), i pod wartość pozycji (P_11),
  co jest poprawne tylko przy ilości 1
- **wiele stawek VAT** — model obsługuje jedną stawkę; sumy pozostałych zostają jako sztywne kwoty

Bez `--write-config` komenda tylko drukuje blok `[profiles.<nazwa>]` do skopiowania —
przydaje się, gdy chcesz najpierw zobaczyć wynik. Wzór placeholderów jest też
w `examples/template.example.xml`.

## Użycie

```bash
# Podgląd: generuje i waliduje XML (XSD FA(3)), niczego nie wysyła; numer przewidywany
ksef-invoice render --profile klient-a --month 2026-07 --net 1000 --net 500

# Wysyłka (domyślnie środowisko TESTOWE — bez skutków prawnych)
# --net podaje się raz na pozycję faktury, w kolejności pozycji z szablonu
ksef-invoice send --profile klient-a --month 2026-07 --net 1000 --net 500
ksef-invoice send --profile klient-b --month 2026-07 --net 800

# Wysyłka PRODUKCYJNA — faktura ma skutki prawne!
ksef-invoice send --profile klient-a --month 2026-07 --net 1000 --net 500 --prod

# Status wystawionej faktury (z lokalnego rejestru)
ksef-invoice status --profile klient-a --month 2026-07 [--prod]

# Diagnostyka setupu (profile, szablony, token, licznik) — nic nie wysyła
ksef-invoice doctor
```

### Przeglądanie

Trzy komendy czytają to, co masz w katalogu roboczym. Żadna nie dotyka sieci i żadna nie
potrzebuje tokenu:

```bash
# Co jest w config.toml: ile kwot --net bierze profil, VAT, termin, który szablon
ksef-invoice profiles

# Historia wystawionych faktur z out/ledger.json
ksef-invoice list
ksef-invoice list --profile klient-a --year 2026 --prod

# Ścieżka do artefaktów — pod podstawienie w shellu
open $(ksef-invoice path --profile klient-a --month 2026-07)
open $(ksef-invoice path --month 2026-07 --prod)/invoice.pdf   # --profile zbędny przy jednym profilu
```

`list` czyta **lokalny rejestr**, nie KSeF — pokazuje numer, który przydzieliło to narzędzie,
i działa offline. Kolumna `pliki` mówi, czy artefakty faktury nadal leżą w `out/`; `—` po
migracji znaczy, że ledger został skopiowany bez `out/`. Tabela świadomie nie ma numeru KSeF
ani ścieżki — pełne dane daje `--json`, a jedną fakturę `status --month`.

Odczyt wprost z KSeF (np. żeby zobaczyć faktury wystawione poza tym narzędziem) wymagałby
tokenu z uprawnieniem **`invoice_read`** — w KSeF jest to zakres rozdzielny od `invoice_write`,
którym się wystawia. Nie ma tego jeszcze.

Po przyjęciu faktury w `~/.ksef-invoice/out/<env>/<profil>/<miesiąc>_<numer>/` lądują:
`invoice.xml`, `invoice.html` (oficjalna wizualizacja; `invoice.pdf` przy instalacji
z extrą `[pdf]`), `upo.xml` (UPO) i `meta.json` (numer KSeF, numery referencyjne).

### Podgląd faktur (PDF/HTML)

- `render` i `send` zapisują wizualizację automatycznie; dla starszych faktur:
  `ksef-invoice pdf --profile klient-a --month 2026-06 [--prod]`.
- `invoice.html` powstaje zawsze i ma CSS druku — Cmd/Ctrl+P w przeglądarce daje ten sam
  układ A4 co lokalny PDF. Wysyłka nie zależy od PDF-a w żaden sposób.
- `invoice.pdf` wymaga extry `[pdf]` i natywnego `pango` — patrz [PDF](#pdf-opcjonalnie).
- Nie musisz ustawiać `DYLD_LIBRARY_PATH`. Wcześniej było to potrzebne, bo WeasyPrint
  szuka `pango` przez `ctypes.util.find_library`, a to na macOS czyta listę
  `DEFAULT_LIBRARY_FALLBACK`, którą Python z Homebrew ma załataną o własny prefiks, a
  czysty CPython (m.in. ten pobierany przez `uv`) nie. Teraz narzędzie dokłada tę ścieżkę
  samo. (`DYLD_LIBRARY_PATH` i tak nie działało z `/usr/bin/python3` — SIP strippuje tę
  zmienną.) Awaryjnie można wyłączyć poprawkę: `KSEF_INVOICE_NO_DYLD_FIXUP=1`.

### Środowisko testowe w przeglądarce

Aplikacja Podatnika KSeF 2.0 — wersja testowa: <https://ap-test.ksef.mf.gov.pl>.
Na środowisku testowym logujesz się **bez profilu zaufanego** (tryb testowego
uwierzytelnienia): podaj NIP kontekstu (ten z `config.toml`) — zobaczysz wszystkie faktury
wysłane przez skrypt na TEST, z podglądem i pobieraniem XML/HTML/PDF. Faktury testowe nie mają
skutków prawnych; każdy może się tam uwierzytelnić dowolnym NIP-em, więc nie wysyłaj na TEST
prawdziwych kwot.

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

### Numeracja

Numer (`FS/<licznik>/<rok>`) wylicza się z rocznego licznika w `~/.ksef-invoice/out/ledger.json`,
wspólnego dla wszystkich profili, osobnego per środowisko. Licznik rośnie przy każdej
udanej wysyłce. **Przy pierwszej produkcyjnej wysyłce zasiej licznik flagą `--seq N`**
(numer kolejnej faktury, uwzględniający faktury wystawione w tym roku poza skryptem) —
kolejne wysyłki kontynuują automatycznie. `--seq` służy też do korekty przy rozjeździe.

## Zabezpieczenia

- Domyślnie wszystko idzie na **środowisko testowe**; produkcja wymaga jawnego `--prod`.
- Przed wysyłką skrypt pokazuje podsumowanie i pyta o potwierdzenie (`--yes` pomija).
- Rejestr `out/ledger.json` blokuje drugą fakturę z tego samego profilu za ten sam
  miesiąc oraz powtórne użycie tego samego numeru (`--force` wymusza).
- XML jest walidowany oficjalnym XSD FA(3) przed wysyłką; NIP sprzedawcy w szablonie
  musi zgadzać się z NIP-em w `config.toml`.
- **KSeF odrzuca faktury z datą wystawienia (P_1) w przyszłości** — domyślnie
  `issue_day = "today"` (data wystawienia = dzień uruchomienia). Data sprzedaży (P_6)
  może być w przyszłości (koniec miesiąca rozliczeniowego).
- Faktury w KSeF są **nieusuwalne** — pomyłkę na produkcji prostuje się fakturą korygującą.

## Prywatność

Repozytorium jest publiczne, ale **Twoje dane nigdy do niego nie trafiają** — od tej wersji
nie leżą już nawet w jego katalogu. Twój NIP, adres, dane klientów, kwoty i szablony żyją
wyłącznie w `~/.ksef-invoice/` (prawa `700`, `.env` z tokenem `600`). Token KSeF trzymaj
tylko w `.env` i traktuj jak hasło. Na środowisku testowym nie wysyłaj prawdziwych kwot
(każdy może się tam uwierzytelnić dowolnym NIP-em).

`out/` i `templates/` pozostają w `.gitignore` na wypadek starszego układu i pracy nad
kodem — ale narzędzie nic już tam nie zapisuje.

## Token KSeF (produkcja)

1. Zaloguj się do Aplikacji Podatnika KSeF: <https://ksef.mf.gov.pl> (profil zaufany / e-dowód).
2. Wybierz kontekst swojego NIP.
3. Wygeneruj **token** z uprawnieniem do wystawiania faktur (InvoiceWrite).
4. Wpisz go do `.env` jako `KSEF_TOKEN=...` (i `KSEF_ENV=prod` albo używaj flagi `--prod`).

Token daje pełne prawo wystawiania faktur w Twoim imieniu — traktuj jak hasło.
Na środowisku testowym token nie jest potrzebny (używany jest certyfikat testowy
generowany przez SDK dla NIP-u z `config.toml`).

## Testy i jakość kodu

```bash
uv run pytest            # testy
uv run ruff check        # linter (błędy, nieużywane importy, sortowanie importów)
uv run ruff format       # formatowanie (odpowiednik prettiera)
```

## Stack

- [ksef2](https://github.com/artpods56/ksef2) — community SDK KSeF API 2.0 (auth, szyfrowanie
  AES-256/RSA-OAEP, sesje online, UPO); wersja przypięta w `pyproject.toml`
- oficjalne XSD FA(3) (bundlowane w ksef2) do walidacji offline
- typer + rich (CLI), lxml (XML), pytest, ruff (lint + format)
- pakowane `uv_build`; PDF (WeasyPrint) w opcjonalnej extrze `[pdf]`

Pliki przykładowe (`config.example.toml`, `.env.example`, `template.example.xml`) leżą
w `examples/` i służą wyłącznie jako dokumentacja — narzędzie ich nie czyta w trakcie
działania (wzorce `config.toml` i `.env` są wbudowane w kod).

Dokumentacja API: [CIRFMF/ksef-docs](https://github.com/CIRFMF/ksef-docs),
środowiska: test `api-test.ksef.mf.gov.pl`, demo `api-demo.ksef.mf.gov.pl`, prod `api.ksef.mf.gov.pl`.

## Zmiany

Historia wersji i instrukcja migracji: [CHANGELOG.md](CHANGELOG.md).

## Licencja

MIT — zobacz [LICENSE](LICENSE).
