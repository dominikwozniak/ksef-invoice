"""Lokalna wizualizacja faktury FA(3): HTML (zawsze) i PDF (jeśli działa WeasyPrint).

Używa oficjalnej wizualizacji XSLT z SDK ksef2. PDF jest opcjonalny (extra `[pdf]`) i
wymaga natywnego pango — jego brak nie może blokować wystawiania faktur, dlatego HTML
dostaje CSS druku i nadaje się do „Zapisz jako PDF" w przeglądarce.
"""

from __future__ import annotations

import os
import sys

from ksef2.infra.schema.fa3 import DEFAULT_CSS_OVERRIDES
from ksef2.services.renderers import InvoiceXSLTRenderer

PDF_OK = "ok"
PDF_NO_EXTRA = "brak-extry"
PDF_NO_PANGO = "brak-pango"


def _fix_native_lib_lookup() -> None:
    """Dokłada prefiks Homebrew do listy, w której macOS szuka bibliotek natywnych.

    WeasyPrint ładuje pango przez `cffi.dlopen` po nazwie liścia ('pango-1.0'), co idzie
    do `ctypes.util.find_library`, a to na macOS konsultuje
    `ctypes.macholib.dyld.DEFAULT_LIBRARY_FALLBACK`. Python z Homebrew ma tę listę
    załataną o własny prefiks — czysty CPython (m.in. ten, który pobiera `uv`) nie ma.
    Dlatego PDF działał tylko pod interpreterem z Homebrew, a pod uv-owym milcząco nie.

    `export DYLD_LIBRARY_PATH` nie jest na to lekiem: SIP strippuje tę zmienną procesom
    uruchamianym z binarek podpisanych przez Apple, więc z /usr/bin/python3 nie działa.
    """
    if sys.platform != "darwin" or os.environ.get("KSEF_INVOICE_NO_DYLD_FIXUP"):
        return

    from ctypes.macholib import dyld

    prefix = os.environ.get("HOMEBREW_PREFIX")
    candidates = [f"{prefix}/lib"] if prefix else []
    candidates += ["/opt/homebrew/lib", "/usr/local/lib"]
    for candidate in candidates:
        if os.path.isdir(candidate) and candidate not in dyld.DEFAULT_LIBRARY_FALLBACK:
            dyld.DEFAULT_LIBRARY_FALLBACK.insert(0, candidate)


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
    """PDF_OK | PDF_NO_EXTRA | PDF_NO_PANGO — rozróżnienie dla `doctor`.

    Brak extry i brak biblioteki systemowej wymagają różnych instrukcji naprawy, a oba
    kończyły się dotąd tym samym „brak WeasyPrint".
    """
    _fix_native_lib_lookup()
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
    _fix_native_lib_lookup()
    try:
        from ksef2.services.renderers import InvoicePDFExporter

        return InvoicePDFExporter().export_from_string(xml)
    except (ImportError, OSError):
        return None
