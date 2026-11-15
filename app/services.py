"""What the app does with invoices: receive, check, approve, correct. No web framework code here."""
from __future__ import annotations

import json
import logging
import mimetypes
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import db, extract, mailer
from .checks import duplicate_key, run_checks
from .config import settings
from .extract.prompt import normalize

log = logging.getLogger("fatoora.services")
RIYADH = ZoneInfo("Asia/Riyadh")
ALLOWED_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
MAX_BYTES = 15 * 1024 * 1024


class ActionError(Exception):
    """A request the user can fix; `code` is shown in the UI."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def now_riyadh() -> str:
    return datetime.now(RIYADH).strftime("%Y-%m-%d %H:%M")


def guess_mime(file_name: str, given: str | None) -> str:
    mime = (given or "").split(";")[0].strip().lower()
    if mime in ALLOWED_TYPES:
        return mime
    return (mimetypes.guess_type(file_name)[0] or mime or "").lower()


def _earlier(exclude_id: str | None = None) -> dict[str, str]:
    rows = db.query("SELECT id, supplier_vat_no, supplier_en, supplier_ar, invoice_no, invoice_date FROM invoices "
                    "WHERE status != 'manual'")
    return {duplicate_key(r["supplier_vat_no"], r["supplier_en"] or r["supplier_ar"], r["invoice_no"]): r["invoice_date"]
            for r in rows if r["id"] != exclude_id and r["invoice_no"]}


def _apply_fields(fields: dict, exclude_id: str | None = None) -> dict:
    result = run_checks(fields, _earlier(exclude_id), settings.large_amount_sar)
    return {
        "supplier_ar": fields.get("supplier_name_ar", ""), "supplier_en": fields.get("supplier_name_en", ""),
        "supplier_vat_no": result.vat_no or str(fields.get("supplier_vat_number") or ""),
        "invoice_no": fields.get("invoice_number", ""), "invoice_date": fields.get("invoice_date", ""),
        "currency": result.currency, "subtotal": result.subtotal, "vat": result.vat, "total": result.total,
        "lines": db.dumps(fields.get("lines") or []), "checks": db.dumps(result.checks), "status": result.status,
    }


def ingest(content: bytes, file_name: str, mime: str | None, source: str, sender: str = "") -> dict:
    """Store the file, read it with AI (or queue it for manual entry), run the checks, notify the approver."""
    mime = guess_mime(file_name, mime)
    if mime not in ALLOWED_TYPES:
        raise ActionError("bad_file", "Send the invoice as a PDF, JPG, PNG or WebP file.")
    if not content or len(content) > MAX_BYTES:
        raise ActionError("bad_file", "The file is empty or larger than 15 MB.")

    invoice_id = "FC-" + datetime.now(RIYADH).strftime("%y%m%d") + "-" + secrets.token_hex(3).upper()
    safe_name = re.sub(r"[^\w.\-]+", "_", Path(file_name).name)[:80] or "invoice"
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    stored = settings.uploads_dir / f"{invoice_id}_{safe_name}"
    stored.write_bytes(content)

    result = extract.extract(content, mime)
    row = {"id": invoice_id, "token": secrets.token_urlsafe(24), "received_at": now_riyadh(), "source": source,
           "sender": sender, "file_name": safe_name, "file_path": str(stored), "file_sha256": extract.sha256(content),
           "extracted_by": result.provider, "note": "; ".join(result.errors)[:500]}
    if result.data is None:
        row.update({"status": "manual"})
    else:
        row.update(_apply_fields(result.data))
    db.insert("invoices", row)
    invoice = get_invoice(invoice_id, raw=True)
    _notify_if_pending(invoice)
    return serialize(invoice)


def update_details(invoice_id: str, fields: dict, user: dict) -> dict:
    """A clerk or manager types in or corrects the invoice details; the checks run again."""
    inv = get_invoice(invoice_id, raw=True)
    if inv["status"] not in ("manual", "review"):
        raise ActionError("locked", "Only invoices waiting for entry or review can be edited.")
    clean = normalize(fields)
    name = clean["supplier_name_ar"] or clean["supplier_name_en"]
    if not (name and clean["invoice_number"] and clean["invoice_date"] and clean["total"] > 0):
        raise ActionError("incomplete", "Fill in the supplier name, invoice number, date and total.")
    changes = _apply_fields(clean, exclude_id=invoice_id)
    changes["extracted_by"] = inv["extracted_by"] if inv["status"] == "review" and inv["extracted_by"] != "manual" else "manual"
    changes["note"] = f"Edited by {user['name']} at {now_riyadh()}"
    db.update("invoices", "id", invoice_id, changes)
    updated = get_invoice(invoice_id, raw=True)
    _notify_if_pending(updated)
    return serialize(updated)


def retry_ai(invoice_id: str) -> dict:
    """Read a stored invoice file with AI again (e.g. after the daily quota resets)."""
    inv = get_invoice(invoice_id, raw=True)
    if inv["status"] not in ("manual", "review"):
        raise ActionError("locked", "Only invoices waiting for entry or review can be read again.")
    path = Path(inv["file_path"])
    if not path.is_file():
        raise ActionError("not_found")
    result = extract.extract(path.read_bytes(), guess_mime(path.name, None))
    if result.data is None:
        db.update("invoices", "id", invoice_id, {"note": "; ".join(result.errors)[:500]})
        raise ActionError("ai_busy", "; ".join(result.errors)[:300])
    changes = _apply_fields(result.data, exclude_id=invoice_id)
    changes.update({"extracted_by": result.provider, "note": ""})
    db.update("invoices", "id", invoice_id, changes)
    updated = get_invoice(invoice_id, raw=True)
    _notify_if_pending(updated)
    return serialize(updated)


def decide(invoice_id: str, action: str, *, reason: str = "", decided_by: str, token: str | None = None) -> dict:
    inv = db.one("SELECT * FROM invoices WHERE id = ?", (invoice_id,))
    if not inv:
        raise ActionError("not_found")
    if action not in ("approve", "reject"):
        raise ActionError("bad_action")
    if token is not None and not secrets.compare_digest(token, inv["token"]):
        raise ActionError("bad_token")
    if inv["status"] != "pending":
        raise ActionError("already_" + inv["status"])
    status = "approved" if action == "approve" else "rejected"
    db.update("invoices", "id", invoice_id, {"status": status, "reason": reason.strip()[:300], "decided_at": now_riyadh(),
                                              "decided_by": decided_by, "token": secrets.token_urlsafe(24)})  # old links stop working
    return serialize(get_invoice(invoice_id, raw=True))


def delete_invoice(invoice_id: str) -> None:
    """Remove a wrong or test invoice. Approved invoices are kept for the audit trail."""
    inv = get_invoice(invoice_id, raw=True)
    if inv["status"] == "approved":
        raise ActionError("locked", "Approved invoices are kept for the audit trail and can't be deleted.")
    db.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))
    path = Path(inv["file_path"])
    if path.is_file() and settings.uploads_dir in path.parents:
        path.unlink(missing_ok=True)


CSV_COLUMNS = ["ID", "Status", "Supplier (AR)", "Supplier (EN)", "Supplier VAT No", "Invoice No", "Invoice Date",
               "Currency", "Subtotal", "VAT", "Total", "Failed checks", "Received At", "Source", "Read by",
               "Decided At", "Decided By", "Reason"]


def ledger_csv() -> str:
    """The whole ledger as CSV (UTF-8 with BOM so Excel shows Arabic correctly)."""
    import csv
    import io

    out = io.StringIO()
    out.write("\ufeff")
    w = csv.writer(out)
    w.writerow(CSV_COLUMNS)
    for r in db.query("SELECT * FROM invoices ORDER BY received_at, id"):
        failed = [c["k"] for c in json.loads(r["checks"] or "[]") if not c.get("pass")]
        w.writerow([r["id"], r["status"], r["supplier_ar"], r["supplier_en"], r["supplier_vat_no"], r["invoice_no"],
                    r["invoice_date"], r["currency"], f"{r['subtotal']:.2f}", f"{r['vat']:.2f}", f"{r['total']:.2f}",
                    " ".join(failed), r["received_at"], r["source"], r["extracted_by"], r["decided_at"], r["decided_by"],
                    r["reason"]])
    return out.getvalue()


def get_invoice(invoice_id: str, raw: bool = False) -> dict:
    inv = db.one("SELECT * FROM invoices WHERE id = ?", (invoice_id,))
    if not inv:
        raise ActionError("not_found")
    return inv if raw else serialize(inv)


def list_invoices() -> list[dict]:
    return [serialize(r) for r in db.query("SELECT * FROM invoices ORDER BY received_at, id")]


def serialize(inv: dict) -> dict:
    """The shape the web app uses. Never includes the approval token or server file paths."""
    return {
        "id": inv["id"], "status": inv["status"], "received_at": inv["received_at"], "source": inv["source"],
        "sender": inv["sender"], "file_name": inv["file_name"], "extracted_by": inv["extracted_by"], "note": inv["note"],
        "supplier": {"ar": inv["supplier_ar"], "en": inv["supplier_en"]}, "vat_no": inv["supplier_vat_no"],
        "number": inv["invoice_no"], "date": inv["invoice_date"], "currency": inv["currency"],
        "subtotal": inv["subtotal"], "vat": inv["vat"], "total": inv["total"],
        "lines": json.loads(inv["lines"] or "[]"), "checks": json.loads(inv["checks"] or "[]"),
        "reason": inv["reason"], "decided_at": inv["decided_at"], "decided_by": inv["decided_by"],
    }


def file_for(invoice_id: str) -> tuple[Path, str]:
    inv = get_invoice(invoice_id, raw=True)
    path = Path(inv["file_path"])
    if not path.is_file():
        raise ActionError("not_found")
    return path, guess_mime(path.name, None)


def _notify_if_pending(inv: dict) -> None:
    if inv["status"] == "pending" and settings.email_enabled and settings.approver_email:
        try:
            mailer.send(settings.approver_email, *mailer.approval_email(inv))
        except Exception as e:  # email trouble must never lose an invoice
            log.error("approval email failed for %s: %s", inv["id"], e)


def weekly_summary(today: datetime | None = None) -> dict:
    today = today or datetime.now(RIYADH)
    since = (today - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
    rows = db.query("SELECT * FROM invoices")
    week = [r for r in rows if r["received_at"] >= since]
    sar = lambda r: r["total"] if r["currency"] == "SAR" else 0  # noqa: E731
    by_supplier: dict[str, float] = {}
    for r in week:
        if r["status"] not in ("rejected", "manual"):
            name = r["supplier_ar"] or r["supplier_en"] or "—"
            by_supplier[name] = by_supplier.get(name, 0) + sar(r)
    return {
        "week_count": len(week),
        "week_spend": sum(sar(r) for r in week if r["status"] not in ("rejected", "manual")),
        "pending": sum(1 for r in rows if r["status"] == "pending"),
        "review": sum(1 for r in rows if r["status"] in ("review", "manual")),
        "vat_approved": sum(r["vat"] for r in rows if r["status"] == "approved"),
        "top": sorted(by_supplier.items(), key=lambda kv: -kv[1])[:5],
    }
