"""Email intake: reads unread Gmail messages with an invoice attachment (IMAP + app password)."""
from __future__ import annotations

import email
import imaplib
import logging
import re
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr

from . import services
from .config import settings

log = logging.getLogger("fatoora.inbox")
SUBJECT_WORDS = re.compile(r"invoice|فاتورة|فاتوره", re.I)


def decode(value: str | None) -> str:
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return value or ""


def attachments(msg: Message) -> list[tuple[str, str, bytes]]:
    """(file name, mime type, content) for every PDF / image attachment."""
    found = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        name = decode(part.get_filename())
        mime = services.guess_mime(name, part.get_content_type())
        if mime in services.ALLOWED_TYPES and (name or part.get("Content-Disposition")):
            payload = part.get_payload(decode=True) or b""
            if payload:
                found.append((name or "invoice", mime, payload))
    return found


def process_message(raw: bytes) -> list[str]:
    """Ingest every invoice attachment of one raw email. Returns the new invoice ids."""
    msg = email.message_from_bytes(raw)
    if not SUBJECT_WORDS.search(decode(msg.get("Subject"))):
        return []
    sender = parseaddr(decode(msg.get("From")))[1]
    ids = []
    for name, mime, content in attachments(msg):
        try:
            ids.append(services.ingest(content, name, mime, source="email", sender=sender)["id"])
        except services.ActionError as e:
            log.warning("skipped attachment %s: %s", name, e)
    return ids


def poll_once() -> int:
    """Check the inbox once. Messages are marked as read only after they were processed."""
    if not settings.email_enabled:
        return 0
    count = 0
    with imaplib.IMAP4_SSL("imap.gmail.com") as imap:
        imap.login(settings.gmail_address, settings.gmail_app_password)
        imap.select("INBOX")
        status, data = imap.search(None, "UNSEEN")
        if status != "OK":
            return 0
        for num in data[0].split()[-20:]:  # at most 20 per round
            status, parts = imap.fetch(num, "(BODY.PEEK[])")
            if status != "OK" or not parts or not isinstance(parts[0], tuple):
                continue
            raw = parts[0][1]
            if not SUBJECT_WORDS.search(decode(email.message_from_bytes(raw).get("Subject"))):
                continue  # not an invoice email: leave it unread for the person
            count += len(process_message(raw))
            imap.store(num, "+FLAGS", "\\Seen")
    return count
