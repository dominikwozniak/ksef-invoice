# ksef-invoice

Wystawianie powtarzalnych faktur sprzedażowych w KSeF (oficjalne API 2.0, schema FA(3)).
Każda powtarzalna faktura to **profil** z własnym szablonem XML; dane prawie się nie
zmieniają — skrypt podmienia tylko numer, daty i kwoty. Numeracja jest wspólna dla
wszystkich profili: roczna sekwencja `FS/<licznik>/<rok>`.

## Wymagania

- Python 3.12+ i [uv](https://docs.astral.sh/uv/)
- Konto w KSeF (na produkcji: token KSeF — patrz niżej)

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

`init` **nie nadpisze** istniejącego `config.toml` ani `.env` (w tym drugim może siedzieć token) —
do tego trzeba jawnego `--force`. `config.toml`, `.env`, `templates/` i `out/` są w `.gitignore`
— zawierają dane prywatne.

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
uv run ksef-invoice render --profile klient-a --month 2026-07 --net 1000 --net 500

# Wysyłka (domyślnie środowisko TESTOWE — bez skutków prawnych)
# --net podaje się raz na pozycję faktury, w kolejności pozycji z szablonu
uv run ksef-invoice send --profile klient-a --month 2026-07 --net 1000 --net 500
uv run ksef-invoice send --profile klient-b --month 2026-07 --net 800

# Wysyłka PRODUKCYJNA — faktura ma skutki prawne!
uv run ksef-invoice send --profile klient-a --month 2026-07 --net 1000 --net 500 --prod

# Status wystawionej faktury (z lokalnego rejestru)
uv run ksef-invoice status --profile klient-a --month 2026-07 [--prod]

# Diagnostyka setupu (profile, szablony, token, licznik) — nic nie wysyła
uv run ksef-invoice doctor
```

Po przyjęciu faktury w `out/<env>/<profil>/<miesiąc>_<numer>/` lądują: `invoice.xml`,
`invoice.html` + `invoice.pdf` (oficjalna wizualizacja), `upo.xml` (UPO) i `meta.json`
(numer KSeF, numery referencyjne).

### Podgląd faktur (PDF/HTML)

- `render` i `send` zapisują wizualizację automatycznie; dla starszych faktur:
  `uv run ksef-invoice pdf --profile klient-a --month 2026-06 [--prod]`.
- PDF wymaga bibliotek natywnych WeasyPrint — na macOS: `brew install pango`.
  Bez nich powstaje sam HTML (i ostrzeżenie), wysyłka działa normalnie.

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

Numer (`FS/<licznik>/<rok>`) wylicza się z rocznego licznika w `out/ledger.json`,
wspólnego dla wszystkich profili, osobnego per środowisko. Licznik rośnie przy każdej
udanej wysyłce. **Przy pierwszej produkcyjnej wysyłce zasiej licznik flagą `--seq N`**
(numer kolejnej faktury, uwzględniający faktury wystawione w tym roku poza skryptem) —
kolejne wysyłki kontynuują automatycznie. `--seq` służy też do korekty przy rozjeździe.

## Zabezpieczenia

- Domyślnie wszystko idzie na **środowisko testowe**; produkcja wymaga jawnego `--prod`.
- Przed wysyłką skrypt pokazuje podsumowanie i pyta o potwierdzenie (`--yes` pomija).
- Rejestr `out/ledger.json` blokuje drugą fakturę z tego samego profilu za ten sam
  miesiąc (`--force` wymusza).
- XML jest walidowany oficjalnym XSD FA(3) przed wysyłką; NIP sprzedawcy w szablonie
  musi zgadzać się z NIP-em w `config.toml`.
- **KSeF odrzuca faktury z datą wystawienia (P_1) w przyszłości** — domyślnie
  `issue_day = "today"` (data wystawienia = dzień uruchomienia). Data sprzedaży (P_6)
  może być w przyszłości (koniec miesiąca rozliczeniowego).
- Faktury w KSeF są **nieusuwalne** — pomyłkę na produkcji prostuje się fakturą korygującą.

## Prywatność

Repozytorium jest publiczne, ale **Twoje dane nigdy do niego nie trafiają**. Twój NIP, adres,
dane klientów, kwoty i szablony żyją wyłącznie lokalnie w `config.toml`, `.env` i `templates/`
(oraz w `out/`) — wszystkie w `.gitignore`. Nie commituj tych plików. Token KSeF trzymaj tylko
w `.env` i traktuj jak hasło. Na środowisku testowym nie wysyłaj prawdziwych kwot (każdy może się
tam uwierzytelnić dowolnym NIP-em).

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
- typer + rich (CLI), pytest, ruff (lint + format)

Pliki przykładowe (`config.example.toml`, `.env.example`, `template.example.xml`) leżą w `examples/`.

Dokumentacja API: [CIRFMF/ksef-docs](https://github.com/CIRFMF/ksef-docs),
środowiska: test `api-test.ksef.mf.gov.pl`, demo `api-demo.ksef.mf.gov.pl`, prod `api.ksef.mf.gov.pl`.

## Licencja

MIT — zobacz [LICENSE](LICENSE).
