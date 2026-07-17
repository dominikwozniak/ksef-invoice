"""Wysyłka faktury do KSeF: auth → sesja online → faktura → UPO."""

from __future__ import annotations

import time
from dataclasses import dataclass

from ksef2 import Client, Environment, FormSchema

from .config import Config

ENVIRONMENT_MAP = {
    "test": Environment.TEST,
    "demo": Environment.DEMO,
    "prod": Environment.PRODUCTION,
}

UPO_RETRIES = 12
UPO_RETRY_INTERVAL = 5.0


@dataclass(frozen=True)
class SendResult:
    ksef_number: str
    invoice_reference_number: str
    session_reference_number: str
    acquisition_date: str | None
    upo: bytes | None


def send_invoice(xml: bytes, config: Config) -> SendResult:
    environment = ENVIRONMENT_MAP[config.environment]
    client = Client(environment)

    if config.environment == "test":
        authed = client.authentication.with_test_certificate(nip=config.nip)
    else:
        if not config.ksef_token:
            raise ValueError(
                f"Środowisko {config.environment} wymaga KSEF_TOKEN w .env "
                "(token generuje się w Aplikacji Podatnika KSeF)."
            )
        authed = client.authentication.with_token(ksef_token=config.ksef_token, nip=config.nip)

    with authed.online_session(form_code=FormSchema.FA3) as session:
        status = session.send_invoice_and_wait(invoice_xml=xml, timeout=180.0)
        upo = _fetch_upo(session, status.ksef_number)
        session_reference = session.get_state().reference_number

    return SendResult(
        ksef_number=status.ksef_number,
        invoice_reference_number=status.reference_number,
        session_reference_number=session_reference,
        acquisition_date=str(status.acquisition_date) if status.acquisition_date else None,
        upo=upo,
    )


def _fetch_upo(session, ksef_number: str) -> bytes | None:
    """UPO bywa dostępne z opóźnieniem względem nadania numeru KSeF — stąd retry."""
    for attempt in range(UPO_RETRIES):
        try:
            return session.get_invoice_upo_by_ksef_number(ksef_number=ksef_number)
        except Exception:
            if attempt == UPO_RETRIES - 1:
                return None
            time.sleep(UPO_RETRY_INTERVAL)
    return None
