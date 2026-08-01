"""Lokalna wizualizacja faktury FA(3): HTML (zawsze) i PDF (jeśli działa WeasyPrint).

Używa oficjalnej wizualizacji XSLT z SDK ksef2. PDF wymaga bibliotek natywnych
(pango i jego zależności) — ich brak nie może blokować wystawiania faktur, więc
`to_pdf` zwraca None zamiast rzucać, a `PDF_HINT` mówi, czego brakuje na tej platformie.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

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
    return InvoiceXSLTRenderer().render_from_string(xml).encode("utf-8")


def to_pdf(xml: bytes) -> bytes | None:
    """PDF faktury albo None, gdy WeasyPrint/pango niedostępne."""
    _add_homebrew_to_dyld_path()
    try:
        from ksef2.services.renderers import InvoicePDFExporter

        return InvoicePDFExporter().export_from_string(xml)
    except (ImportError, OSError):
        return None
