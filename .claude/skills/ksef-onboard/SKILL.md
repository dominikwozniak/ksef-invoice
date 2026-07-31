---
name: ksef-onboard
description: Konfiguruje projekt ksef-invoice od zera albo dodaje nowego kontrahenta — z XML-a faktury pobranej z KSeF buduje szablon FA(3), wpisuje profil do config.toml i sprawdza setup komendą doctor. Użyj zawsze, gdy ktoś pierwszy raz uruchamia ten projekt, prosi o konfigurację lub setup, dodaje klienta/kontrahenta/profil, ma plik faktury i pyta „co dalej", albo gdy doctor zgłasza problem z config.toml czy szablonem — także wtedy, gdy nie użyje słowa „onboarding". Sam nie wysyła faktur i nie dotyka tokenu KSeF.
---

# Onboarding ksef-invoice

Prowadzi użytkownika od świeżej instalacji (albo od nowego kontrahenta) do zwalidowanego
profilu faktury.

Stan — `config.toml`, `.env`, `templates/`, `out/` — leży w `~/.ksef-invoice`, nie w katalogu
repozytorium. Nadpisuje to `--home <katalog>` (flaga **przed** komendą) albo zmienna
`KSEF_INVOICE_HOME`. `doctor` wypisuje rozwiązaną ścieżkę w pierwszej linii — **podawaj ją
użytkownikowi**, bo przy trzech źródłach rozwiązania „gdzie ono szuka?" jest pierwszym
pytaniem przy każdym problemie.

Cała logika siedzi w komendach CLI — ta umiejętność wywołuje je w dobrej kolejności i tłumaczy
wyniki. To celowy podział: komendy są testowane pytestem i działają też dla kogoś, kto nie używa
Claude Code, więc **nie powielaj tu logiki domenowej**. Nie generuj XML-a ręcznie, nie edytuj
`config.toml` Edit-em, nie licz kwot. Jeśli komenda czegoś nie potrafi, to jest brak w CLI do
zgłoszenia, a nie zadanie do obejścia promptem — obejście przeżyje tylko w tej jednej rozmowie.

## Granice i powody, dla których się trzymają

Te cztery rzeczy zostają w mocy także wtedy, gdy użytkownik poprosi inaczej. Każda ma konkretny powód:

1. **Nie uruchamiaj `send`** — ani na TEST, ani z `--prod`. Faktury w KSeF są nieusuwalne;
   pomyłkę na produkcji prostuje się fakturą korygującą, nie cofnięciem. Onboarding kończy się
   na `render`, który waliduje XML i zapisuje wizualizację, ale w ogóle nie kontaktuje się
   z KSeF. Jeśli użytkownik poprosi o wysyłkę, pokaż mu gotową komendę i powiedz, dlaczego jej
   nie uruchamiasz za niego.
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
ksef-invoice doctor
```

Zacznij od tego zawsze — także gdy użytkownik twierdzi, że nic nie jest skonfigurowane. `doctor`
odpowiada na wszystko naraz: w którym katalogu pracuje, czy jest `config.toml`, jakie profile
istnieją, ile kwot `--net` bierze każdy z nich, w jakim środowisku jesteś i jak stoi licznik
numeracji. Potrzebujesz wyniku maszynowo (np. do sprawdzenia jednego pola) — `doctor --json`
daje `{home, checks, failed}`.

- Wywalił się na braku `config.toml` → krok 2.
- Jest check `migracja` → użytkownik ma stan po starszej wersji, w katalogu repo. **Nie rób
  `init`** (utworzyłby pusty config obok istniejącego stanu). Pokaż przepis `cp -a` z tego
  checka, każ sprawdzić `doctor` po obu stronach i dopiero potem usunąć kopie. Przenoszenia
  nie wykonuj za użytkownika: pomylony licznik numeracji to duplikat numeru faktury.
- Config jest, a użytkownik chce **dodać kontrahenta** → pomiń krok 2, przejdź do 3.
- Wszystko zielone i nie ma nowego profilu do dodania → nie ma tu nic do roboty. Powiedz to
  wprost, zamiast szukać sobie zajęcia.

### 2. Utwórz konfigurację (tylko gdy nie istnieje)

Potrzebny jest NIP sprzedawcy — czyli **firmy użytkownika**, nie klienta. To częste pomylenie,
więc dopytaj, jeśli coś nie pasuje. Gdy użytkownik ma już pod ręką XML faktury, odczytaj z niego
`Podmiot1/DaneIdentyfikacyjne/NIP` i zaproponuj tę wartość do potwierdzenia — szybciej niż pytanie
na pusto i od razu widać, czy plik jest tym, o który chodziło.

```bash
ksef-invoice init --nip <NIP>
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
ksef-invoice templatize <faktura.xml> --name <profil> --write-config --due-days 14
```

Nazwa profilu to krótki identyfikator kontrahenta (`airhelp`, `klient-a`) — będzie potem
w komendach jako `--profile`, więc niech będzie łatwa do wpisania. Komenda zapisuje
`~/.ksef-invoice/templates/<profil>.xml`, dopisuje `[profiles.<profil>]` do `config.toml`
i wypisuje ostrzeżenia. Ścieżka nie zależy od katalogu, z którego uruchamiasz komendę.

### 4. Przeczytaj ostrzeżenia na głos

To najważniejszy moment całego onboardingu, bo tu szablon bywa **po cichu niedokładny** —
wszystko się waliduje i renderuje, a mimo to przy innych kwotach da złą fakturę. Streszczenie
„poszły jakieś warningi, ale jest OK" jest tu gorsze niż brak odpowiedzi. Wyjaśnij każde:

| Ostrzeżenie | Co znaczy naprawdę |
|---|---|
| `ilość P_8B=... ≠ 1` | Szablon podstawia kwotę i pod cenę jednostkową, i pod wartość pozycji. To poprawne tylko przy ilości 1. Przy większej ilości `--net` da złą fakturę — trzeba ręcznie poprawić `templates/<profil>.xml`. |
| `Wykryto dodatkowe stawki VAT` | Faktura ma więcej niż jedną stawkę, a model obsługuje jedną. Sumy pozostałych stawek zostały w szablonie jako **sztywne kwoty** — przy innych kwotach faktura się rozjedzie. |
| `Nie udało się odczytać stawki VAT` | Przyjęto 23% na wyczucie. Sprawdź `vat_rate` w `config.toml`. |
| `NIP sprzedawcy ... różni się od nip w config.toml` | KSeF taką fakturę odrzuci. Ustalcie, która wartość jest prawdziwa, i popraw drugą. |
| `Brak pola P_1 / P_2 / P_6 / P_15 / Termin` | XML nie jest kompletną fakturą sprzedażową — poproś o inny plik. |

Przy ilości ≠ 1 i przy wielu stawkach VAT **powiedz wprost, że szablon wymaga ręcznej korekty**,
i wskaż, którego fragmentu `templates/<profil>.xml` to dotyczy. To dwa przypadki, w których
zielony `doctor` nie oznacza poprawnej faktury.

### 5. Zweryfikuj

```bash
ksef-invoice doctor
```

Musi być zielone. Podaj użytkownikowi, **ile kwot `--net` bierze nowy profil** — to pierwsza
rzecz, o którą zapyta przy wystawianiu, a `doctor` to pokazuje.

### 6. Zrób próbny podgląd

```bash
ksef-invoice render --profile <profil> --month <RRRR-MM> --net <kwota> [--net <kwota2>]
```

Kwoty **weź od użytkownika**, nie wymyślaj. Jeśli chce tylko sprawdzić, czy działa, zaproponuj
wprost kwoty próbne (`--net 1000`) i powiedz, że `render` nic nie wysyła.

`render` wypisuje ścieżkę pod „Podgląd" — to `invoice.pdf` albo, przy instalacji bez extry
`[pdf]`, `invoice.html` (ma CSS druku, więc w przeglądarce wygląda tak samo). Otwórz ten plik
i poproś użytkownika, żeby sprawdził to, czego kod nie oceni: opisy pozycji, dane nabywcy,
numer konta. Kwoty, daty i numer weryfikuje już `render` wraz z walidacją XSD. Ostrzeżenie
o pominiętym PDF-ie nie jest błędem setupu — nie strasz nim użytkownika.

## Gdy coś nie zadziała

Komunikaty CLI są instruktażowe — zwykle mówią, co zrobić. Najczęstsze:

| Komunikat | Co z tym zrobić |
|---|---|
| `Brak <ścieżka>/config.toml` | Cofnij się do kroku 2 — ale najpierw sprawdź, czy `doctor` nie zgłasza też checka `migracja`; wtedy config istnieje, tylko w starym miejscu. Podaj użytkownikowi ścieżkę z komunikatu, bo mówi, gdzie narzędzie szukało. |
| `doctor`: check `migracja` | Stan po starszej wersji leży w katalogu repo. Przepis `cp -a` jest w treści checka. Nie wykonuj przenoszenia za użytkownika i nie proponuj `mv`. |
| `Profil 'x' już jest w config.toml` | Nazwa zajęta. Zaproponuj inną (`--name`); nie sięgaj po `--force`, bo nadpisze cudzy profil. |
| `NIP ... ma niepoprawną sumę kontrolną` | Literówka. Poproś o NIP jeszcze raz, nie „popraw" go sam. |
| `Nie udało się przetworzyć <plik>` | XML nie przechodzi walidacji XSD FA(3) — najczęściej to nie faktura albo nie ten wzór. Poproś o plik pobrany wprost z KSeF. |
| `doctor`: `brak placeholderów {{line1_net}}` | Szablon nie ma zmiennych pozycji. Zwykle znaczy, że `templatize` dostał plik już będący szablonem, a nie fakturę. |

## Zakończenie

Podsumuj: jaki profil powstał, ile bierze kwot `--net`, jaka stawka VAT i jaki termin, gdzie leży
szablon i **w którym katalogu roboczym** (ścieżka z `doctor`) — to ten katalog użytkownik ma
backupować, bo w nim siedzi licznik numeracji. Odeślij do `README.md` po instrukcję pierwszej
wysyłki i powiedz wyraźnie, że domyślnie wszystko idzie na środowisko **testowe**, a produkcja
wymaga jawnej flagi `--prod` i tokenu KSeF.

Jeśli którykolwiek krok się nie udał, powiedz konkretnie, co zostało do zrobienia ręcznie.
Zielony `doctor` jest jedynym dowodem gotowego setupu — bez niego nie zostawiaj wrażenia,
że wszystko działa.
