"""Background jobs while the server runs: check the inbox, send the Sunday digest."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from . import db, inbox, mailer, services
from .config import settings

log = logging.getLogger("fatoora.scheduler")


def digest_due(now: datetime, last_sent: str) -> bool:
    """Sunday from 08:00 Riyadh time, once per day."""
    return now.weekday() == 6 and now.hour >= 8 and last_sent != now.strftime("%Y-%m-%d")


def send_digest_if_due() -> bool:
    now = datetime.now(services.RIYADH)
    if not (settings.email_enabled and settings.approver_email) or not digest_due(now, db.get_state("digest_sent")):
        return False
    mailer.send(settings.approver_email, *mailer.digest_email(services.weekly_summary(now)))
    db.set_state("digest_sent", now.strftime("%Y-%m-%d"))
    return True


async def run_forever() -> None:
    if not settings.email_enabled:
        log.info("Email is off (no GMAIL_ADDRESS / GMAIL_APP_PASSWORD in .env). Upload still works.")
        return
    log.info("Checking %s every %s seconds", settings.gmail_address, settings.email_poll_seconds)
    while True:
        try:
            n = await asyncio.to_thread(inbox.poll_once)
            if n:
                log.info("Received %s invoice(s) by email", n)
            await asyncio.to_thread(send_digest_if_due)
        except Exception as e:  # keep the loop alive whatever happens
            log.error("background job failed: %s", e)
        await asyncio.sleep(max(20, settings.email_poll_seconds))
