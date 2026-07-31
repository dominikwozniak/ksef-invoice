"""Lokalna wizualizacja faktury FA(3): HTML (zawsze) i PDF (jeśli działa WeasyPrint).

Używa oficjalnej wizualizacji XSLT z SDK ksef2. PDF jest opcjonalny (extra `[pdf]`) i
wymaga bibliotek natywnych (pango i zależności) — ich brak nie może blokować wystawiania
faktur, więc `to_pdf` zwraca None zamiast rzucać, HTML dostaje CSS druku i nadaje się do
„Zapisz jako PDF" w przeglądarce, a `PDF_HINT` mówi, czego brakuje na tej platformie.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from ksef2.infra.schema.fa3 import DEFAULT_CSS_OVERRIDES
from ksef2.services.renderers import InvoiceXSLTRenderer

# Katalog bibliotek Homebrew: /opt/homebrew na Apple Silicon, /usr/local na Intelu.
_HOMEBREW_LIB_DIRS = ("/opt/homebrew/lib", "/usr/local/lib")

_APT_PACKAGES = "libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libfontconfig1"

if sys.platform == "darwin":
    PDF_HINT = (
        "macOS: brew install pango (nietypowy prefiks Homebrew: "
        'export DYLD_LIBRARY_PATH="$(brew --prefix)/lib")'
    )
elif sys.platform.startswith("linux"):
    PDF_HINT = f"Debian/Ubuntu: sudo apt install {_APT_PACKAGES}"
else:
    PDF_HINT = "Windows: zainstaluj GTK3 runtime — patrz README, sekcja o bibliotekach natywnych"

# Trzy stany zamiast jednego „brak WeasyPrint": brak extry `[pdf]` i brak biblioteki
# systemowej wymagają różnych instrukcji naprawy.
PDF_OK = "ok"
PDF_NO_EXTRA = "brak-extry"
PDF_NO_PANGO = "brak-pango"


def _add_homebrew_to_dyld_path() -> None:
    """macOS: dołóż katalog bibliotek Homebrew do ścieżki wyszukiwania dylibów.

    WeasyPrint ładuje pango przez `cffi.dlopen`, a gdy to zawiedzie — przez
    `ctypes.util.find_library`, które czyta DYLD_LIBRARY_PATH dopiero w momencie
    wywołania. Python z Homebrew ma prefiks Homebrew we własnej domyślnej liście
    (łatka Homebrew), ale interpreter pobrany przez uv albo z python.org już nie —
    i wtedy sam `brew install pango` nie wystarcza. Dokładamy katalog tutaj, żeby
    nikt nie musiał eksportować zmiennej w swoim shellu.
    """
    if sys.platform != "darwin":
        return
    current = os.environ.get("DYLD_LIBRARY_PATH", "")
    existing = current.split(os.pathsep) if current else []
    missing = [path for path in _HOMEBREW_LIB_DIRS if path not in existing and Path(path).is_dir()]
    if missing:
        # Doklejamy na koniec — to, co ustawił użytkownik, ma pierwszeństwo.
        os.environ["DYLD_LIBRARY_PATH"] = os.pathsep.join([*existing, *missing])


def to_html(xml: bytes) -> bytes:
    """Oficjalna wizualizacja XSLT + CSS druku z SDK.

    CSS (`@page { size: A4 landscape }` i szerokości kolumn) stosuje normalnie tylko
    eksporter PDF. Wstrzykujemy go też do HTML-a, żeby Cmd/Ctrl+P w przeglądarce dawało
    ten sam układ — inaczej instalacja bez extry `[pdf]` byłaby okrojona, a nie po prostu
    generująca inaczej.
    """
    html = InvoiceXSLTRenderer().render_from_string(xml)
    style = f'<style type="text/css">\n{DEFAULT_CSS_OVERRIDES}\n</style>'
    if "</head>" in html:
        html = html.replace("</head>", f"{style}\n</head>", 1)
    else:
        html = style + html
    return html.encode("utf-8")


def pdf_status() -> str:
    """PDF_OK | PDF_NO_EXTRA | PDF_NO_PANGO — rozróżnienie dla `doctor`."""
    _add_homebrew_to_dyld_path()
    try:
        import weasyprint  # noqa: F401
    except ImportError:
        return PDF_NO_EXTRA
    except OSError:
        # cffi/ctypes nie znalazły libpango — to nie jest brak pakietu pythonowego.
        return PDF_NO_PANGO
    return PDF_OK


def to_pdf(xml: bytes) -> bytes | None:
    """PDF faktury albo None, gdy WeasyPrint/pango niedostępne."""
    _add_homebrew_to_dyld_path()
    try:
        from ksef2.services.renderers import InvoicePDFExporter

        return InvoicePDFExporter().export_from_string(xml)
    except (ImportError, OSError):
        return None
