"""Lokalna wizualizacja faktury FA(3): HTML (zawsze) i PDF (jeśli działa WeasyPrint).

Używa oficjalnej wizualizacji XSLT z SDK ksef2; PDF wymaga bibliotek natywnych
(macOS: `brew install pango`) — ich brak nie może blokować wystawiania faktur.
"""

from __future__ import annotations

from ksef2.services.renderers import InvoiceXSLTRenderer


def to_html(xml: bytes) -> bytes:
    return InvoiceXSLTRenderer().render_from_string(xml).encode("utf-8")


def to_pdf(xml: bytes) -> bytes | None:
    """PDF faktury albo None, gdy WeasyPrint/pango niedostępne."""
    try:
        from ksef2.services.renderers import InvoicePDFExporter

        return InvoicePDFExporter().export_from_string(xml)
    except (ImportError, OSError):
        return None
