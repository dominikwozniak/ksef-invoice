# SPEC: ksef-invoice

## Problem

Co miesiąc wystawiane są **dwie** niemal identyczne faktury sprzedażowe (stały sprzedawca,
nabywca i pozycja usługowa per faktura) — zmienia się tylko numer, daty i kwota. Od kwietnia
2026 faktury trzeba wystawiać w KSeF. Ręczne klikanie w Aplikacji Podatnika jest zbędnym narzutem.

## Rozwiązanie

CLI (`ksef-invoice`), które z trzech parametrów — profil, miesiąc i kwota netto — generuje
XML FA(3) z szablonu profilu, waliduje go oficjalnym XSD, wysyła przez KSeF API 2.0
(sesja interaktywna) i archiwizuje numer KSeF + UPO. Każda powtarzalna faktura = profil
(`[profiles.<nazwa>]` w config.toml + `templates/<nazwa>.xml`).

## Decyzje

| Decyzja | Wybór | Uzasadnienie |
|---|---|---|
| Integracja | oficjalne API 2.0 | za darmo, bez pośrednika, dane zostają u nas |
| Język / SDK | Python + [ksef2](https://github.com/artpods56/ksef2) | SDK załatwia auth, szyfrowanie AES/RSA, sesje, UPO |
| Wzór faktury | XML FA(3) poprzedniej faktury z KSeF | zero zgadywania pól; placeholdery tylko na zmienne |
| Auth TEST | certyfikat testowy generowany przez SDK | nie wymaga tokenu ani profilu zaufanego |
| Auth PROD | token KSeF z Aplikacji Podatnika | najprostsza droga dla osoby fizycznej z NIP |
| Kwoty | `Decimal`, `ROUND_HALF_UP` do groszy | zgodność z zasadami zaokrągleń VAT |
| Numeracja | wspólna roczna sekwencja `FS/{seq}/{year}` | licznik w ledgerze per środowisko, zasiewany/korygowany flagą `--seq` (pierwszą produkcyjną wysyłkę w roku trzeba zasiać) |
| Wiele faktur | profile w config.toml, np. `klient-a`, `klient-b` | osobny szablon i wpisy w ledgerze, wspólny NIP i licznik |
| Pozycje | `--net` per pozycja → `{{lineN_net}}` | profil może mieć wiele zmiennych pozycji; sumy liczone od pozycji |
| Faktura bez VAT | `vat_rate = "np"` | np. „np II" (odwrotne obciążenie przy usługach dla kontrahenta z UE) — suma w P_13_9, brutto=netto, P_18=1 w szablonie |
| Termin płatności | `due_days` XOR `due_day_next_month` | np. 15. dzień miesiąca po P_6 albo wystawienie + N dni |
| Onboarding | `init` → `templatize --write-config` → `doctor` | nowy użytkownik/kontrahent bez ręcznej edycji plików; skill `ksef-onboard` woła te same komendy |
| Reguła terminu przy onboardingu | podawana jawnie flagą, nie wnioskowana | to zapis z umowy, a jedna faktura pasuje czasem do obu reguł |
| Zapis profilu do `config.toml` | dopisanie tekstu, nie biblioteka TOML | `tomllib` jest read-only; dopisanie zachowuje komentarze bez nowej zależności |

## Akceptacja (zweryfikowane na api-test.ksef.mf.gov.pl, 2026-07-16)

- [x] `render` generuje XML przechodzący walidację XSD FA(3)
- [x] `send` na TEST: faktura przyjęta, numer KSeF nadany, UPO pobrane w sesji
- [x] drugi `send` z tego samego profilu za ten sam miesiąc odmawia bez `--force` (ledger)
- [x] wysyłka z P_1 w przyszłości blokowana lokalnie (KSeF odrzuca ją kodem 450)
- [x] NIP sprzedawcy w szablonie niezgodny z config → błąd przed wysyłką
- [x] dwa profile współdzielą licznik: kolejne wysyłki dostały FS/1/2026 i FS/2/2026 (TEST)
- [x] `--seq 40` wymusza numer FS/40/2026; brak `--profile` przy 2 profilach → czytelny błąd
- [x] dwa profile (VAT 23% z 2 pozycjami oraz „np II" bez P_14) przyjęte na TEST i przeszły
      walidację semantyczną KSeF
- [x] pierwsza wysyłka produkcyjna (`--prod --seq <N>`, token KSeF): faktura przyjęta, numer KSeF
      nadany, UPO podpisane przez „Ministerstwo Finansów" (bez dopisku o środowisku testowym),
      licznik produkcyjny zasiany flagą `--seq`. Numery i daty zostają lokalnie w `out/` i `TODO.md`

## Wnioski z integracji (istotne reguły KSeF)

- Kod 450 „Błąd weryfikacji semantyki": m.in. data wystawienia (P_1) w przyszłości.
  Data sprzedaży (P_6) może być przyszła.
- Kod 440 „Duplikat faktury": ta sama para (NIP, numer P_2) — na środowisku testowym
  publiczne NIP-y typu 1111111111 są „zużyte" przez innych integratorów; używać losowego
  NIP-u z poprawną sumą kontrolną.
- NIP w Podmiot1 musi być zgodny z kontekstem uwierzytelnienia.
- UPO faktury jest dostępne w ramach otwartej sesji zaraz po nadaniu numeru KSeF.
- FA(3): `Podmiot2` wymaga pól `JST` i `GV` (dla zwykłej firmy: `2`/`2`).

## Poza zakresem (świadomie)

- faktury korygujące, wiele pozycji, inne waluty niż szablon
- tryb wsadowy (batch) i offline
- pobieranie faktur zakupowych
- wiele stawek VAT na jednej fakturze oraz pozycje z ilością ≠ 1 — `templatize` i `doctor`
  mają je tylko czytelnie zgłaszać, nie obsługiwać
