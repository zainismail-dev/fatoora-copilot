"""Saved bank reconciliations: run one, keep one per month, carry uncleared items forward, export to Excel."""
from __future__ import annotations

import io
import json
import secrets

from . import db, reconcile
from .services import now_riyadh

MAX_FILE = 5 * 1024 * 1024


def _previous_for(period_start: str) -> dict | None:
    """The latest saved reconciliation that ends before this one starts."""
    return db.one("SELECT * FROM reconciliations WHERE period_end < ? ORDER BY period_end DESC LIMIT 1", (period_start,))


def run(bank: bytes, bank_name: str, book: bytes, book_name: str, user: dict,
        bank_closing: float | None = None, book_closing: float | None = None) -> dict:
    if len(bank) > MAX_FILE or len(book) > MAX_FILE:
        raise reconcile.ReconcileError("too_big", "each file must be under 5 MB")
    bank_rows, book_rows = reconcile.read_table(bank, bank_name), reconcile.read_table(book, book_name)
    entries, _ = reconcile.normalize(bank_rows, "bank")
    if not entries:
        raise reconcile.ReconcileError("empty", "bank: no transactions found")
    prev = _previous_for(min(e["date"] for e in entries))
    carried = json.loads(prev["result"])["carry_forward"] if prev else []
    result = reconcile.reconcile(bank_rows, book_rows, reconcile.previous_from(carried), bank_closing, book_closing)
    result["previous"] = {"id": prev["id"], "period_end": prev["period_end"]} if prev else None

    # one reconciliation per month: running a month again replaces it
    month = result["period"]["end"][:7]
    db.execute("DELETE FROM reconciliations WHERE substr(period_end, 1, 7) = ?", (month,))
    rid = "RC-" + month + "-" + secrets.token_hex(2)
    st = result["statement"]
    db.insert("reconciliations", {
        "id": rid, "created_at": now_riyadh(), "created_by": user.get("name") or user.get("email", ""),
        "period_start": result["period"]["start"], "period_end": result["period"]["end"],
        "bank_file": bank_name, "book_file": book_name, "bank_closing": st["bank_closing"],
        "book_closing": st["book_closing"], "difference": st["difference"], "result": db.dumps(result)})
    return get(rid)


def _summary(row: dict) -> dict:
    return {k: row[k] for k in ("id", "created_at", "created_by", "period_start", "period_end", "bank_file", "book_file",
                                 "bank_closing", "book_closing", "difference")}


def list_all() -> list[dict]:
    return [_summary(r) for r in db.query("SELECT * FROM reconciliations ORDER BY period_end DESC")]


def get(rid: str) -> dict:
    row = db.one("SELECT * FROM reconciliations WHERE id = ?", (rid,))
    if not row:
        raise reconcile.ReconcileError("not_found", "reconciliation not found")
    return {**_summary(row), "result": json.loads(row["result"])}


def delete(rid: str) -> None:
    get(rid)
    db.execute("DELETE FROM reconciliations WHERE id = ?", (rid,))


# ---------- Excel export ----------
KINDS = {"charges": "Bank charges", "direct_debit": "Direct debit", "interest": "Profit / interest", "direct_credit": "Direct credit"}


def xlsx(rid: str) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    rec = get(rid)
    r, st = rec["result"], rec["result"]["statement"]
    wb = Workbook()
    bold, money = Font(bold=True), "#,##0.00;(#,##0.00)"
    head_fill = PatternFill("solid", fgColor="DDE7E1")

    def sheet(title, header, rows, money_cols):
        ws = wb.create_sheet(title)
        ws.append(header)
        for c in ws[1]:
            c.font, c.fill = bold, head_fill
        for row in rows:
            ws.append(row)
        for col in money_cols:
            for cell in ws.iter_rows(min_row=2, min_col=col, max_col=col):
                cell[0].number_format = money
        for i, h in enumerate(header, start=1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = max(12, min(48, len(h) + 6))
        ws.freeze_panes = "A2"
        return ws, len(rows) + 1

    def total(title, last, col="D"):
        return f"=SUM('{title}'!{col}2:{col}{max(last, 2)})"

    ws = wb.active
    ws.title = "Summary"
    _, n_out = sheet("Outstanding cheques", ["Date", "Cheque no", "Description", "Amount (SAR)", "Days outstanding", "Stale (6+ months)", "From earlier month"],
                     [[e["date"], e["ref"], e["description"], e["amount"], e["age"], "Yes" if e["stale"] else "", "Yes" if e.get("previous") else ""] for e in r["outstanding"]], [4])
    _, n_tr = sheet("Deposits in transit", ["Date", "Reference", "Description", "Amount (SAR)", "Days", "From earlier month"],
                    [[e["date"], e["ref"], e["description"], e["amount"], e["age"], "Yes" if e.get("previous") else ""] for e in r["in_transit"]], [4])
    _, n_bo = sheet("Bank-only items", ["Date", "Reference", "Description", "Amount (SAR)", "Type", "Post in books"],
                    [[e["date"], e["ref"], e["description"], e["amount"], KINDS[e["kind"]], "Yes"] for e in r["bank_only"]], [4])
    _, n_er = sheet("Errors", ["Cheque no", "Book date", "Book amount", "Bank amount", "Correction to books"],
                    [[e["book"]["ref"], e["book"]["date"], e["book"]["amount"], e["bank"]["amount"], e["difference"]] for e in r["errors"]], [3, 4, 5])
    _, n_du = sheet("Duplicates", ["Date", "Cheque no", "Description", "Amount (SAR)", "Correction to books"],
                    [[e["date"], e["ref"], e["description"], e["amount"], -e["amount"]] for e in r["duplicates"]], [4, 5])
    sheet("Matched", ["Book date", "Bank date", "Days", "Cheque no", "Book description", "Bank description", "Amount (SAR)", "Matched by"],
          [[p["book"]["date"], p["bank"]["date"], p["days"], p["book"]["ref"] or p["bank"]["ref"], p["book"]["description"],
            p["bank"]["description"], p["book"]["amount"], p["how"].replace("_", " ")] for p in r["matched"]], [7])
    sheet("Carry forward", ["Date", "Cheque / ref", "Description", "Amount (SAR)"],
          [[e["date"], e["ref"], e["description"], e["amount"]] for e in r["carry_forward"]], [4])

    p = r["period"]
    lines = [
        [f"Bank reconciliation · {p['start']} to {p['end']}", None],
        [None, None],
        ["Balance as per bank statement", st["bank_closing"]],
        ["Less: outstanding cheques", total("Outstanding cheques", n_out)],
        ["Add: deposits in transit", total("Deposits in transit", n_tr)],
        ["Adjusted bank balance", "=B3+B4+B5"],
        [None, None],
        ["Balance as per cash book", st["book_closing"]],
        ["Less/add: bank-only items (post these in the books)", total("Bank-only items", n_bo)],
        ["Add/less: recording errors corrected", total("Errors", n_er, "E")],
        ["Add back: duplicate entries removed", total("Duplicates", n_du, "E")],
        ["Adjusted book balance", "=B8+B9+B10+B11"],
        [None, None],
        ["Difference (should be 0)", "=ROUND(B6-B12,2)"],
    ]
    for row in lines:
        ws.append(row)
    ws["A1"].font = Font(bold=True, size=14)
    for ref in ("A6", "B6", "A12", "B12", "A14", "B14"):
        ws[ref].font = bold
    for i in range(3, 15):
        ws[f"B{i}"].number_format = money
        ws[f"B{i}"].alignment = Alignment(horizontal="right")
    ws["B14"].fill = PatternFill("solid", fgColor="C8E6C9" if abs(st["difference"]) < 0.005 else "F8C8C4")
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 52, 20
    ws.append([])
    ws.append([f"Prepared by Fatoora Copilot on {rec['created_at'][:16]} · to be reviewed and signed off by the accountant"])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
