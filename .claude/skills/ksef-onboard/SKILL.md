---
name: ksef-onboard
description: Konfiguruje projekt ksef-invoice od zera albo dodaje nowego kontrahenta — z XML-a faktury pobranej z KSeF buduje szablon FA(3), wpisuje profil do config.toml i sprawdza setup komendą doctor. Użyj zawsze, gdy ktoś pierwszy raz uruchamia ten projekt, prosi o konfigurację lub setup, dodaje klienta/kontrahenta/profil, ma plik faktury i pyta „co dalej", albo gdy doctor zgłasza problem z config.toml czy szablonem — także wtedy, gdy nie użyje słowa „onboarding". Sam nie wysyła faktur i nie dotyka tokenu KSeF.
---

# Onboarding ksef-invoice

Prowadzi użytkownika od świeżego klonu (albo od nowego kontrahenta) do zwalidowanego profilu
faktury.

Cała logika siedzi w komendach CLI — ta umiejętność wywołuje je w dobrej kolejności i tłumaczy
wyniki. To celowy podział: komendy są testowane pytestem i działają też dla kogoś, kto nie używa
Claude Code, więc **nie powielaj tu logiki domenowej**. Nie generuj XML-a ręcznie, nie edytuj
`config.toml` Edit-em, nie licz kwot. Jeśli komenda czegoś nie potrafi, to jest brak w CLI do
zgłoszenia, a nie zadanie do obejścia promptem — obejście przeżyje tylko w tej jednej rozmowie.

## Granice i powody, dla których się trzymają

Te cztery rzeczy zostają w mocy także wtedy, gdy użytkownik poprosi inaczej. Każda ma konkretny powód:

1. **Nie uruchamiaj `send`** — ani na TEST, ani z `--prod`. Faktury w KSeF są nieusuwalne;
   pomyłkę na produkcji prostuje się fakturą korygującą, nie cofnięciem. Onboarding kończy się
   na `render`, który waliduje XML i rysuje PDF, ale w ogóle nie kontaktuje się z KSeF.
   Jeśli użytkownik poprosi o wysyłkę, pokaż mu gotową komendę i powiedz, dlaczego jej nie
   uruchamiasz za niego.
2. **Nie czytaj, nie wypisuj ani nie ustawiaj `KSEF_TOKEN`** — token daje pełne prawo wystawiania
   faktur w imieniu użytkownika, czyli jest hasłem. Na TEST jest zbędny (SDK generuje certyfikat
   testowy dla NIP-u z configu), a produkcję użytkownik konfiguruje poza tym przepływem.
3. **Nie nadpisuj istniejącego `config.toml` ani `.env`** i nie proponuj `--force` do `init`.
   Istniejące pliki znaczą, że ktoś już to skonfigurował: w `.env` może siedzieć produkcyjny
   token, w `config.toml` działające profile. `init` sam odmówi — nie obchodź tej odmowy.
4. **Nie zgaduj reguły terminu płatności ani kwot** — to zapisy z umowy, nie fakty z dokumentu.
   Jedna faktura pasuje czasem do obu reguł terminu naraz, więc wyliczenie jej z jednej daty
   byłoby zgadywaniem podanym jako fakt. Pytaj.

## Przebieg

### 1. Rozpoznaj stan

```bash
uv run ksef-invoice doctor
```

Zacznij od tego zawsze — także gdy użytkownik twierdzi, że nic nie jest skonfigurowane. `doctor`
odpowiada na wszystko naraz: czy jest `config.toml`, jakie profile istnieją, ile kwot `--net`
bierze każdy z nich, w jakim środowisku jesteś i jak stoi licznik numeracji.

- Wywalił się na braku `config.toml` → krok 2.
- Config jest, a użytkownik chce **dodać kontrahenta** → pomiń krok 2, przejdź do 3.
- Wszystko zielone i nie ma nowego profilu do dodania → nie ma tu nic do roboty. Powiedz to
  wprost, zamiast szukać sobie zajęcia.

### 2. Utwórz konfigurację (tylko gdy nie istnieje)

Potrzebny jest NIP sprzedawcy — czyli **firmy użytkownika**, nie klienta. To częste pomylenie,
więc dopytaj, jeśli coś nie pasuje. Gdy użytkownik ma już pod ręką XML faktury, odczytaj z niego
`Podmiot1/DaneIdentyfikacyjne/NIP` i zaproponuj tę wartość do potwierdzenia — szybciej niż pytanie
na pusto i od razu widać, czy plik jest tym, o który chodziło.

```bash
uv run ksef-invoice init --nip <NIP>
```

Suma kontrolna jest sprawdzana, więc literówka wyjdzie natychmiast. Powstaje `config.toml`
bez profili i `.env` ze środowiskiem `test`.

### 3. Zrób szablon i profil z prawdziwej faktury

Poproś o **XML faktury FA(3) pobranej z KSeF** — nie o PDF i nie o skan; z nich nie da się
odtworzyć struktury pól. Skąd go wziąć: Aplikacja Podatnika KSeF (<https://ksef.mf.gov.pl>,
testowa <https://ap-test.ksef.mf.gov.pl>) → lista faktur → wybrana faktura → pobierz XML.
Najlepsza jest ostatnia faktura dla tego kontrahenta, bo dane prawie się nie zmieniają.

Zanim uruchomisz komendę, **zapytaj o regułę terminu płatności** — pytaj o rzecz, nie o nazwę
klucza w TOML-u:

- „płatne do 15. dnia następnego miesiąca" → `--due-day-next-month 15`
- „płatne w 14 dni od wystawienia" → `--due-days 14`

Jeśli użytkownik nie wie, poproś, żeby zajrzał w umowę albo na termin widoczny na tej fakturze —
ale niech to on zdecyduje, a nie Ty za niego (powód: granica nr 4).

```bash
uv run ksef-invoice templatize <faktura.xml> --name <profil> --write-config --due-days 14
```

Nazwa profilu to krótki identyfikator kontrahenta (`airhelp`, `klient-a`) — będzie potem
w komendach jako `--profile`, więc niech będzie łatwa do wpisania. Komenda zapisuje
`templates/<profil>.xml`, dopisuje `[profiles.<profil>]` do `config.toml` i wypisuje ostrzeżenia.

### 4. Przeczytaj ostrzeżenia na głos

To najważniejszy moment całego onboardingu, bo tu szablon bywa **po cichu niedokładny** —
wszystko się waliduje i renderuje, a mimo to przy innych kwotach da złą fakturę. Streszczenie
„poszły jakieś warningi, ale jest OK" jest tu gorsze niż brak odpowiedzi. Wyjaśnij każde:

| Ostrzeżenie | Co znaczy naprawdę |
|---|---|
| `ilość P_8B=... ≠ 1` | Szablon podstawia kwotę i pod cenę jednostkową, i pod wartość pozycji. To poprawne tylko przy ilości 1. Przy większej ilości `--net` da złą fakturę — trzeba ręcznie poprawić `templates/<profil>.xml`. |
| `Wykryto dodatkowe stawki VAT` | Faktura ma więcej niż jedną stawkę, a model obsługuje jedną. Sumy pozostałych stawek zostały w szablonie jako **sztywne kwoty** — przy innych kwotach faktura się rozjedzie. |
| `Nie udało się odczytać stawki VAT` | Przyjęto 23% na wyczucie. Sprawdź `vat_rate` w `config.toml`. |
| `Nietypowa stawka P_12=...` | Stawki nie dało się zinterpretować, więc trafiła do configu jak leci. Zostawiona bez poprawki wywali każdą kolejną komendę — ustal `vat_rate` ręcznie. |
| `NIP sprzedawcy ... różni się od nip w config.toml` | KSeF taką fakturę odrzuci. Ustalcie, która wartość jest prawdziwa, i popraw drugą. |
| `Brak NIP-u sprzedawcy w Podmiot1` | To nie wygląda na fakturę sprzedażową z KSeF — poproś o inny plik. |
| `Brak pola P_1 / P_2 / P_6` | Brakuje daty wystawienia, numeru albo daty sprzedaży — placeholder trzeba wstawić ręcznie. Zwykle znaczy, że plik nie jest kompletną fakturą. |
| `Brak P_13_1/P_13_9 (suma netto)` / `Brak P_15 (brutto)` | Szablon nie ma gdzie wstawić sum — bez ręcznej poprawki `render` przerwie na niepodmienionym placeholderze. |
| `Brak Platnosc/TerminPlatnosci/Termin` | Faktura źródłowa nie miała terminu płatności — dodaj `{{payment_due}}` ręcznie. |

Przy ilości ≠ 1 i przy wielu stawkach VAT **powiedz wprost, że szablon wymaga ręcznej korekty**,
i wskaż, którego fragmentu `templates/<profil>.xml` to dotyczy. To dwa przypadki, w których
zielony `doctor` nie oznacza poprawnej faktury.

### 5. Zweryfikuj

```bash
uv run ksef-invoice doctor
```

Musi być zielone. Podaj użytkownikowi, **ile kwot `--net` bierze nowy profil** — to pierwsza
rzecz, o którą zapyta przy wystawianiu, a `doctor` to pokazuje.

### 6. Zrób próbny podgląd

```bash
uv run ksef-invoice render --profile <profil> --month <RRRR-MM> --net <kwota> [--net <kwota2>]
```

Kwoty **weź od użytkownika**, nie wymyślaj. Jeśli chce tylko sprawdzić, czy działa, zaproponuj
wprost kwoty próbne (`--net 1000`) i powiedz, że `render` nic nie wysyła.

Otwórz powstały podgląd i poproś użytkownika, żeby sprawdził to, czego kod nie oceni: opisy
pozycji, dane nabywcy, numer konta. Kwoty, daty i numer weryfikuje już `render` wraz z walidacją
XSD. Ścieżkę do otwarcia bierz z linii `Podgląd:` — bez bibliotek natywnych powstaje sam
`invoice.html` zamiast PDF-a i to jego wtedy otwierasz.

## Gdy coś nie zadziała

Komunikaty CLI są instruktażowe — zwykle mówią, co zrobić. Najczęstsze:

| Komunikat | Co z tym zrobić |
|---|---|
| `Brak <ścieżka>/config.toml. Utwórz go komendą ksef-invoice init --nip <NIP>` | Cofnij się do kroku 2. |
| `config.toml: brak sekcji [profiles.<nazwa>]` | Był sam `init`, nie ma jeszcze żadnego profilu — to krok 3, nie awaria. |
| `doctor`: ⚠ `brak bibliotek natywnych WeasyPrint` | Tylko PDF nie powstaje; XML, walidacja i wysyłka działają. Podaj użytkownikowi komendę instalacji z komunikatu i idź dalej — to nie blokuje onboardingu. |
| `Profil 'x' już jest w config.toml` | Nazwa zajęta. Zaproponuj inną (`--name`); nie sięgaj po `--force`, bo podmieni istniejący profil na nowy (jego szablon i regułę terminu). |
| `NIP ... ma niepoprawną sumę kontrolną` | Literówka. Poproś o NIP jeszcze raz, nie „popraw" go sam. |
| `Nie udało się przetworzyć <plik>` | XML nie przechodzi walidacji XSD FA(3) — najczęściej to nie faktura albo nie ten wzór. Poproś o plik pobrany wprost z KSeF. |
| `doctor`: `brak placeholderów {{line1_net}}` | Szablon nie ma zmiennych pozycji. Zwykle znaczy, że `templatize` dostał plik już będący szablonem, a nie fakturę. |

## Zakończenie

Podsumuj: jaki profil powstał, ile bierze kwot `--net`, jaka stawka VAT i jaki termin, gdzie leży
szablon. Odeślij do `README.md` po instrukcję pierwszej wysyłki i powiedz wyraźnie, że domyślnie
wszystko idzie na środowisko **testowe**, a produkcja wymaga tokenu KSeF i jawnej flagi `--prod`
— albo `KSEF_ENV=prod` w `.env`, co znosi to zabezpieczenie na stałe i dlatego nie jest zalecane.

Jeśli którykolwiek krok się nie udał, powiedz konkretnie, co zostało do zrobienia ręcznie.
Zielony `doctor` jest jedynym dowodem gotowego setupu — bez niego nie zostawiaj wrażenia,
że wszystko działa.
