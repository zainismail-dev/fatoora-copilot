"""Email intake parsing, outgoing email content, digest timing, users and passwords."""
from datetime import datetime
from email.message import EmailMessage

import pytest

from app import auth, inbox, mailer, scheduler, services

from .conftest import fake_provider


def make_email(subject, attach=True):
    msg = EmailMessage()
    msg["From"] = "Sahab Billing <billing@sahab.example>"
    msg["Subject"] = subject
    msg.set_content("Please find the invoice attached.")
    if attach:
        msg.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="INV-2701.pdf")
    return msg.as_bytes()


def test_invoice_email_is_ingested(use_providers):
    use_providers(fake_provider("gemini"))
    ids = inbox.process_message(make_email("فاتورة رقم INV-2701"))
    inv = services.get_invoice(ids[0])
    assert len(ids) == 1 and inv["source"] == "email" and inv["sender"] == "billing@sahab.example"


def test_other_emails_are_ignored(use_providers):
    use_providers(fake_provider("gemini"))
    assert inbox.process_message(make_email("Lunch on Thursday?")) == []
    assert inbox.process_message(make_email("Invoice INV-1", attach=False)) == []


def test_result_pages():
    assert "Invoice approved" in mailer.result_page("approved")
    assert "already used" in mailer.result_page("bad_token")


def test_digest_runs_sunday_morning_once():
    sunday_9 = datetime(2026, 11, 15, 9, 0)
    assert scheduler.digest_due(sunday_9, "")
    assert not scheduler.digest_due(sunday_9, "2026-11-15")
    assert not scheduler.digest_due(datetime(2026, 11, 15, 7, 0), "")
    assert not scheduler.digest_due(datetime(2026, 11, 16, 9, 0), "")


def test_passwords():
    stored = auth.hash_password("correct horse")
    assert auth.verify_password("correct horse", stored) and not auth.verify_password("wrong", stored)
    assert not auth.verify_password("x", "garbage")


def test_users_and_roles():
    auth.create_user("Clerk@Example.com", "Sara", "clerk", "password123")
    assert auth.authenticate("clerk@example.com", "password123")["role"] == "clerk"
    assert auth.authenticate("clerk@example.com", "nope") is None
    with pytest.raises(ValueError):
        auth.create_user("clerk@example.com", "Sara", "clerk", "password123")
    with pytest.raises(ValueError):
        auth.create_user("a@example.com", "A", "boss", "password123")
    with pytest.raises(ValueError):
        auth.create_user("b@example.com", "B", "clerk", "short")


def test_first_manager_created_once():
    auth.ensure_admin("m@example.com", "Maha", "password123")
    auth.ensure_admin("other@example.com", "X", "password123")
    assert auth.authenticate("m@example.com", "password123")["role"] == "manager"
    assert auth.authenticate("other@example.com", "password123") is None


def test_empty_admin_email_is_refused():
    with pytest.raises(ValueError, match="ADMIN_EMAIL"):
        auth.ensure_admin("", "Zain", "password123")


def test_login_throttle_blocks_then_expires():
    now = [0.0]
    t = auth.LoginThrottle(max_failures=3, window_seconds=60, clock=lambda: now[0])
    for _ in range(3):
        assert not t.blocked("a@x.sa")
        t.fail("a@x.sa")
    assert t.blocked("a@x.sa") and not t.blocked("b@x.sa")
    now[0] = 61
    assert not t.blocked("a@x.sa")
    t.fail("a@x.sa")
    t.reset("a@x.sa")
    assert not t.blocked("a@x.sa")
