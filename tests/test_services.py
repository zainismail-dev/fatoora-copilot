"""Receiving, checking, correcting and approving invoices, without the web layer."""
import pytest

from app import db, mailer, services
from app.config import settings

from .conftest import BUSY, CLEAN, fake_provider

PDF = b"%PDF-1.4 fake invoice"
MANAGER = {"name": "Maha", "email": "maha@example.com", "role": "manager"}


def test_clean_invoice_waits_for_approval(use_providers):
    use_providers(fake_provider("gemini"))
    inv = services.ingest(PDF, "01-sahab.pdf", "application/pdf", source="upload")
    assert inv["status"] == "pending" and inv["extracted_by"] == "gemini"
    assert "token" not in inv and "file_path" not in inv  # never sent to the browser


def test_wrong_file_type_is_refused(use_providers):
    use_providers(fake_provider("gemini"))
    with pytest.raises(services.ActionError) as e:
        services.ingest(b"hello", "notes.txt", "text/plain", source="upload")
    assert e.value.code == "bad_file"


def test_duplicate_goes_to_review(use_providers):
    use_providers(fake_provider("gemini"))
    services.ingest(PDF, "a.pdf", "application/pdf", source="upload")
    second = services.ingest(PDF + b"x", "b.pdf", "application/pdf", source="email")
    assert second["status"] == "review" and not next(c for c in second["checks"] if c["k"] == "dup")["pass"]


def test_busy_ai_saves_for_manual_entry_then_checks(use_providers):
    use_providers(fake_provider("gemini", error=BUSY))
    inv = services.ingest(PDF, "c.pdf", "application/pdf", source="upload")
    assert inv["status"] == "manual" and "429" in inv["note"]
    fixed = services.update_details(inv["id"], dict(CLEAN), MANAGER)
    assert fixed["status"] == "pending" and fixed["extracted_by"] == "manual"


def test_correcting_a_misread_invoice(use_providers):
    use_providers(fake_provider("gemini", result=dict(CLEAN, vat_amount=3400)))
    inv = services.ingest(PDF, "d.pdf", "application/pdf", source="upload")
    assert inv["status"] == "review"
    assert services.update_details(inv["id"], dict(CLEAN), MANAGER)["status"] == "pending"


def test_edit_does_not_flag_itself_as_duplicate(use_providers):
    use_providers(fake_provider("gemini", result=dict(CLEAN, vat_amount=1)))
    inv = services.ingest(PDF, "e.pdf", "application/pdf", source="upload")
    assert services.update_details(inv["id"], dict(CLEAN), MANAGER)["status"] == "pending"


def test_decisions(use_providers):
    use_providers(fake_provider("gemini"))
    inv = services.ingest(PDF, "f.pdf", "application/pdf", source="upload")
    token = db.one("SELECT token FROM invoices WHERE id = ?", (inv["id"],))["token"]
    with pytest.raises(services.ActionError) as e:
        services.decide(inv["id"], "approve", decided_by="email link", token="wrong")
    assert e.value.code == "bad_token"
    done = services.decide(inv["id"], "approve", decided_by="email link", token=token)
    assert done["status"] == "approved" and done["decided_by"] == "email link"
    with pytest.raises(services.ActionError) as e:
        services.decide(inv["id"], "reject", decided_by="x", token=token)  # old link no longer works
    assert e.value.code == "bad_token"
    with pytest.raises(services.ActionError) as e:
        services.decide(inv["id"], "reject", decided_by="maha@example.com")
    assert e.value.code == "already_approved"
    with pytest.raises(services.ActionError):
        services.update_details(inv["id"], dict(CLEAN), MANAGER)  # approved invoices are locked


def test_review_invoice_cannot_be_approved(use_providers):
    use_providers(fake_provider("gemini", result=dict(CLEAN, supplier_vat_number="123")))
    inv = services.ingest(PDF, "g.pdf", "application/pdf", source="upload")
    with pytest.raises(services.ActionError) as e:
        services.decide(inv["id"], "approve", decided_by="maha@example.com")
    assert e.value.code == "already_review"


def test_approval_email_sent_for_clean_invoices(use_providers, monkeypatch):
    sent = []
    monkeypatch.setattr(settings, "gmail_address", "ap@example.com")
    monkeypatch.setattr(settings, "gmail_app_password", "abcd")
    monkeypatch.setattr(settings, "approver_email", "boss@example.com")
    monkeypatch.setattr(mailer, "send", lambda to, subject, html: sent.append((to, subject, html)))
    use_providers(fake_provider("gemini"))
    inv = services.ingest(PDF, "h.pdf", "application/pdf", source="upload")
    token = db.one("SELECT token FROM invoices WHERE id = ?", (inv["id"],))["token"]
    assert len(sent) == 1 and sent[0][0] == "boss@example.com" and f"token={token}" in sent[0][2]


def test_email_failure_never_loses_the_invoice(use_providers, monkeypatch):
    monkeypatch.setattr(settings, "gmail_address", "ap@example.com")
    monkeypatch.setattr(settings, "gmail_app_password", "abcd")
    monkeypatch.setattr(settings, "approver_email", "boss@example.com")
    monkeypatch.setattr(mailer, "send", lambda *a: (_ for _ in ()).throw(OSError("smtp down")))
    use_providers(fake_provider("gemini"))
    inv = services.ingest(PDF, "i.pdf", "application/pdf", source="upload")
    assert services.get_invoice(inv["id"])["status"] == "pending"


def test_weekly_summary(use_providers):
    use_providers(fake_provider("gemini"))
    inv = services.ingest(PDF, "j.pdf", "application/pdf", source="upload")
    services.decide(inv["id"], "approve", decided_by="maha@example.com")
    s = services.weekly_summary()
    assert s["week_count"] == 1 and s["vat_approved"] == 3510 and s["top"][0][1] == 26910


def test_empty_details_are_refused(use_providers):
    use_providers(fake_provider("gemini", error=BUSY))
    inv = services.ingest(PDF, "k.pdf", "application/pdf", source="upload")
    with pytest.raises(services.ActionError) as e:
        services.update_details(inv["id"], {"supplier_name_ar": "", "invoice_number": "", "total": 0}, MANAGER)
    assert e.value.code == "incomplete" and services.get_invoice(inv["id"])["status"] == "manual"


def test_retry_ai_after_quota_resets(use_providers):
    use_providers(fake_provider("gemini", error=BUSY))
    inv = services.ingest(PDF, "l.pdf", "application/pdf", source="upload")
    with pytest.raises(services.ActionError) as e:
        services.retry_ai(inv["id"])  # still busy: stays in manual entry, reason kept
    assert e.value.code == "ai_busy" and "429" in services.get_invoice(inv["id"])["note"]
    use_providers(fake_provider("gemini"))  # quota is back
    done = services.retry_ai(inv["id"])
    assert done["status"] == "pending" and done["extracted_by"] == "gemini" and done["note"] == ""


def test_delete_wrong_invoice_but_keep_approved(use_providers):
    use_providers(fake_provider("gemini"))
    wrong = services.ingest(PDF, "m.pdf", "application/pdf", source="upload")
    stored = db.one("SELECT file_path FROM invoices WHERE id = ?", (wrong["id"],))["file_path"]
    services.delete_invoice(wrong["id"])
    with pytest.raises(services.ActionError):
        services.get_invoice(wrong["id"])
    assert not __import__("pathlib").Path(stored).exists()
    kept = services.ingest(PDF + b"2", "n.pdf", "application/pdf", source="upload")
    services.decide(kept["id"], "approve", decided_by="maha@example.com")
    with pytest.raises(services.ActionError) as e:
        services.delete_invoice(kept["id"])
    assert e.value.code == "locked"


def test_ledger_csv_has_arabic_and_failed_checks(use_providers):
    use_providers(fake_provider("gemini", result=dict(CLEAN, vat_amount=3000)))
    services.ingest(PDF, "o.pdf", "application/pdf", source="upload")
    text = services.ledger_csv()
    assert text.startswith("﻿") and "شركة سحاب" in text and "rate" in text and "26910.00" in text
