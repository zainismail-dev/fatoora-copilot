"""Bank reconciliation: match the bank statement against the company's cash book and explain every riyal of difference.

Plain code, no AI: the same files always give the same answer, and every match says which rule made it.

    reconcile(bank_rows, book_rows, previous=[...], bank_closing=None, book_closing=None) -> dict

Rows are the raw cells of a CSV or Excel sheet (header row included). Amounts are kept in halalas
(integers) while matching, so sums never drift. Sign convention: the company's view, money in > 0.

web/reconcile.js is a line-by-line port of this file for the GitHub Pages demo; tests/test_reconcile.py
checks that both give identical results.
"""
from __future__ import annotations

import csv
import io
import math
import re
from datetime import date, datetime

DATE_WINDOW = (-3, 7)   # a bank date may be up to 3 days before or 7 days after the book date
STALE_DAYS = 180        # cheques older than this are flagged as stale
CHARGE_WORDS = ("charge", "fee", "commission", "رسوم", "عموله", "عمولة")
INTEREST_WORDS = ("interest", "profit", "فائده", "فائدة", "ارباح", "أرباح", "عائد")
CHEQUE_RE = re.compile(r"(?:chq|cheque|check|شيك)\s*(?:no\.?|number|#|رقم)?\s*[:#]?\s*0*(\d{3,})", re.I)

HEADERS = {
    "date": ["date", "transaction date", "posting date", "txn date", "التاريخ", "تاريخ العمليه", "تاريخ العملية", "value date", "تاريخ القيمه"],
    "description": ["description", "details", "narrative", "particulars", "payee", "memo", "البيان", "الوصف", "التفاصيل"],
    "ref": ["cheque no", "cheque number", "chq no", "check no", "cheque", "reference", "ref", "ref no", "رقم الشيك", "المرجع", "رقم المرجع"],
    "amount": ["amount", "المبلغ"],
    "balance": ["balance", "running balance", "الرصيد"],
    # where money goes in and out depends on the side: a bank "debit" is money out, a cash book "debit" is money in
    "in": ["deposit", "deposits", "money in", "paid in", "receipt", "receipts", "ايداع", "إيداع"],
    "out": ["withdrawal", "withdrawals", "money out", "paid out", "payment", "payments", "سحب"],
    "debit": ["debit", "dr", "مدين"],
    "credit": ["credit", "cr", "دائن"],
}


class ReconcileError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


# ---------- reading files ----------
def read_table(content: bytes, file_name: str) -> list[list]:
    """CSV (UTF-8 or Arabic Windows encoding) or Excel → list of rows."""
    if file_name.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        try:
            sheet = load_workbook(io.BytesIO(content), read_only=True, data_only=True).worksheets[0]
        except Exception as e:  # noqa: BLE001  (a corrupt or non-Excel file)
            raise ReconcileError("bad_file", f"{file_name}: {e}") from e
        return [list(r) for r in sheet.iter_rows(values_only=True)]
    if not file_name.lower().endswith((".csv", ".txt")):
        raise ReconcileError("bad_file", f"{file_name}: use a CSV or Excel (.xlsx) file")
    for encoding in ("utf-8-sig", "cp1256"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ReconcileError("bad_file", f"{file_name}: unknown text encoding")
    return [row for row in csv.reader(io.StringIO(text))]


def norm(s) -> str:
    s = str(s or "").strip().lower()
    s = re.sub(r"[أإآ]", "ا", s).replace("ة", "ه").replace("ى", "ي")
    s = re.sub(r"[_.:#()/\\-]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _digits(s: str) -> str:
    return s.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))


def cents(x: float) -> int:
    """Riyals → halalas, rounding half away from zero (the same in Python and JavaScript)."""
    return (1 if x >= 0 else -1) * math.floor(abs(x) * 100 + 0.5)


def parse_amount(v) -> int:
    """→ halalas. Handles 1,234.50 · (1,234.50) · 1234.50- · SAR 1,234 · Arabic digits · blanks."""
    if v is None or v == "":
        return 0
    if isinstance(v, (int, float)):
        return cents(v)
    s = _digits(str(v)).strip().replace("٬", ",").replace("٫", ".")
    neg = s.startswith("(") and s.endswith(")") or s.endswith("-") or s.startswith("-")
    s = re.sub(r"[^0-9.]", "", s.replace(",", ""))
    if not s or s == ".":
        return 0
    n = cents(float(s))
    return -n if neg else n


def parse_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = _digits(str(v or "")).strip()
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    else:
        m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)   # day first, as Saudi banks print it
        if m:
            d, mo, y = int(m[1]), int(m[2]), int(m[3])
        else:
            m = re.match(r"^(\d{1,2})[ -]([a-z]{3})[a-z]*[ -](\d{2,4})", s.lower())
            months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
            if not m or m[2] not in months:
                return None
            d, mo, y = int(m[1]), months.index(m[2]) + 1, int(m[3])
        if y < 100:
            y += 2000
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def clean_ref(ref, description: str) -> str:
    if isinstance(ref, float) and ref.is_integer():   # Excel stores 100234 as 100234.0
        ref = int(ref)
    s = _digits(str(ref if ref is not None else "")).strip()
    s = re.sub(r"(?i)^(chq|cheque|check|ref|شيك)\s*(no\.?|#|رقم)?", "", s)
    s = re.sub(r"[^0-9A-Za-z]", "", s).lstrip("0").upper()
    if not s:
        m = CHEQUE_RE.search(_digits(description or ""))
        s = m[1].lstrip("0") if m else ""
    return s


def _find_columns(header: list) -> dict[str, int]:
    cells = [norm(h) for h in header]
    found: dict[str, int] = {}
    for key, names in HEADERS.items():
        for name in names:  # names are in order of preference
            if norm(name) in cells and cells.index(norm(name)) not in found.values():
                found[key] = cells.index(norm(name))
                break
    return found


def normalize(rows: list[list], side: str) -> tuple[list[dict], int | None]:
    """Raw rows → entries + the closing balance if the file shows one. side: 'bank' or 'book'."""
    for at, row in enumerate(rows[:20]):  # noqa: B007  (`at` is used after the loop)
        cols = _find_columns(row)
        if "date" in cols and ({"amount"} <= cols.keys() or {"in", "out"} <= cols.keys() or {"debit", "credit"} <= cols.keys()):
            break
    else:
        raise ReconcileError("no_columns", f"{side}: couldn't find the Date and Amount (or Debit/Credit) columns")

    def cell(row, key):
        i = cols.get(key)
        return row[i] if i is not None and i < len(row) else None

    entries, closing = [], None
    prefix = "B" if side == "bank" else "K"
    for n, row in enumerate(rows[at + 1:], start=at + 2):
        if not any(c not in (None, "") for c in row):
            continue
        desc = str(cell(row, "description") or "").strip()
        balance = cell(row, "balance")
        if re.search(r"opening balance|balance brought|الرصيد الافتتاحي|رصيد افتتاحي", norm(desc)):
            continue
        if re.search(r"closing balance|balance carried|الرصيد الختامي|رصيد ختامي", norm(desc)):
            if balance not in (None, ""):
                closing = parse_amount(balance)
            continue
        d = parse_date(cell(row, "date"))
        if d is None:
            continue
        if "amount" in cols:
            amount = parse_amount(cell(row, "amount"))
        elif "in" in cols:
            amount = parse_amount(cell(row, "in")) - parse_amount(cell(row, "out"))
        else:
            dr, cr = parse_amount(cell(row, "debit")), parse_amount(cell(row, "credit"))
            amount = (cr - dr) if side == "bank" else (dr - cr)
        if amount == 0:
            continue
        if balance not in (None, ""):
            closing = parse_amount(balance)
        entries.append({"id": f"{prefix}{n}", "row": n, "date": d.isoformat(), "description": desc,
                        "ref": clean_ref(cell(row, "ref"), desc), "amount": amount})
    return entries, closing


# ---------- matching ----------
def _days(a: str, b: str) -> int:
    return (date.fromisoformat(a) - date.fromisoformat(b)).days


def match(bank: list[dict], book: list[dict]) -> list[dict]:
    """Four passes; each row is used once. Returns [{bank, book, how, days}]."""
    pairs, used_b, used_k = [], set(), set()

    def take(b, k, how):
        used_b.add(b["id"]); used_k.add(k["id"])  # noqa: E702
        pairs.append({"bank": b, "book": k, "how": how, "days": _days(b["date"], k["date"])})

    def free(side, used):
        return [e for e in side if e["id"] not in used]

    for k in book:                                                       # 1. cheque number + amount
        if k["ref"]:
            for b in free(bank, used_b):
                if b["ref"] == k["ref"] and b["amount"] == k["amount"]:
                    take(b, k, "cheque"); break  # noqa: E702
    for k in free(book, used_k):                                         # 2. amount + same date
        for b in free(bank, used_b):
            if b["amount"] == k["amount"] and b["date"] == k["date"]:
                take(b, k, "same_date"); break  # noqa: E702
    for k in free(book, used_k):                                         # 3. amount + date close by
        near = [b for b in free(bank, used_b) if b["amount"] == k["amount"] and DATE_WINDOW[0] <= _days(b["date"], k["date"]) <= DATE_WINDOW[1]]
        if near:
            take(min(near, key=lambda b: abs(_days(b["date"], k["date"]))), k, "near_date")
    for k in free(book, used_k):                                         # 4. amount unique on both sides
        same_b = [b for b in free(bank, used_b) if b["amount"] == k["amount"] and _days(b["date"], k["date"]) >= DATE_WINDOW[0]]
        same_k = [x for x in free(book, used_k) if x["amount"] == k["amount"]]
        if len(same_b) == 1 and len(same_k) == 1:
            take(same_b[0], k, "unique_amount")
    return pairs


def _has(text: str, words) -> bool:
    t = norm(text)
    return any(norm(w) in t for w in words)


def reconcile(bank_rows: list[list], book_rows: list[list], previous: list[dict] | None = None,
              bank_closing: float | None = None, book_closing: float | None = None) -> dict:
    bank, bank_found = normalize(bank_rows, "bank")
    book, book_found = normalize(book_rows, "book")
    if not bank:
        raise ReconcileError("empty", "bank: no transactions found")
    b_close = cents(bank_closing) if bank_closing is not None else bank_found
    k_close = cents(book_closing) if book_closing is not None else book_found
    if b_close is None or k_close is None:
        raise ReconcileError("no_balance", "add the closing balance: the file has no Balance column")

    start = min(e["date"] for e in bank + book)
    end = max(e["date"] for e in bank + book)
    carried = [{**p, "id": f"P{i + 1}", "previous": True} for i, p in enumerate(previous or [])]
    pairs = match(bank, carried + book)
    used = {p["bank"]["id"] for p in pairs} | {p["book"]["id"] for p in pairs}
    left_b = [e for e in bank if e["id"] not in used]
    left_k = [e for e in carried + book if e["id"] not in used]

    # near-matches: same cheque number, different amount → a recording error
    errors = []
    for k in list(left_k):
        b = next((b for b in left_b if k["ref"] and b["ref"] == k["ref"] and (b["amount"] > 0) == (k["amount"] > 0)), None)
        if b:
            errors.append({"bank": b, "book": k, "difference": b["amount"] - k["amount"]})
            left_b.remove(b); left_k.remove(k)  # noqa: E702

    # the same book line entered twice
    duplicates, seen = [], []
    for k in book:
        key = (k["date"], k["amount"], k["ref"], norm(k["description"]))
        if key in seen and any(x["id"] == k["id"] for x in left_k):
            duplicates.append(k)
            left_k = [x for x in left_k if x["id"] != k["id"]]
        seen.append(key)

    end_d = date.fromisoformat(end)
    outstanding = [{**k, "age": (end_d - date.fromisoformat(k["date"])).days,
                    "stale": (end_d - date.fromisoformat(k["date"])).days > STALE_DAYS} for k in left_k if k["amount"] < 0]
    in_transit = [{**k, "age": (end_d - date.fromisoformat(k["date"])).days} for k in left_k if k["amount"] > 0]
    bank_keys = [(b["date"], b["amount"], norm(b["description"])) for b in bank]
    bank_only = [{**b, "kind": ("charges" if _has(b["description"], CHARGE_WORDS) else "direct_debit") if b["amount"] < 0
                  else ("interest" if _has(b["description"], INTEREST_WORDS) else "direct_credit"),
                  "repeat": bank_keys.count((b["date"], b["amount"], norm(b["description"]))) > 1} for b in left_b]

    s = sum
    st = {
        "bank_closing": b_close,
        "outstanding_cheques": s(e["amount"] for e in outstanding),
        "deposits_in_transit": s(e["amount"] for e in in_transit),
        "book_closing": k_close,
        "bank_debits": s(e["amount"] for e in bank_only if e["amount"] < 0),
        "bank_credits": s(e["amount"] for e in bank_only if e["amount"] > 0),
        "errors": s(e["difference"] for e in errors),
        "duplicates": -s(e["amount"] for e in duplicates),
    }
    st["adjusted_bank"] = st["bank_closing"] + st["outstanding_cheques"] + st["deposits_in_transit"]
    st["adjusted_book"] = st["book_closing"] + st["bank_debits"] + st["bank_credits"] + st["errors"] + st["duplicates"]
    st["difference"] = st["adjusted_bank"] - st["adjusted_book"]

    placed = {p["bank"]["id"] for p in pairs} | {e["bank"]["id"] for e in errors} | {e["id"] for e in bank_only}
    assert len(placed) == len(bank), "every bank row must be accounted for"
    placed = {p["book"]["id"] for p in pairs} | {e["book"]["id"] for e in errors} | {e["id"] for e in duplicates + outstanding + in_transit}
    assert {e["id"] for e in book} <= placed, "every book row must be accounted for"

    carry = [{"date": e["date"], "description": e["description"], "ref": e["ref"], "amount": e["amount"]}
             for e in sorted(outstanding + in_transit, key=lambda e: e["date"])]
    return _to_sar({
        "period": {"start": start, "end": end},
        "counts": {"bank_rows": len(bank), "book_rows": len(book), "carried_in": len(carried), "matched": len(pairs)},
        "statement": st,
        "matched": pairs,
        "outstanding": outstanding,
        "in_transit": in_transit,
        "bank_only": bank_only,
        "errors": errors,
        "duplicates": duplicates,
        "cleared_from_previous": [p for p in pairs if p["book"].get("previous")],
        "carry_forward": carry,
    })


def _to_sar(v):
    """Halalas → riyals, recursively, for every money field."""
    if isinstance(v, list):
        return [_to_sar(x) for x in v]
    if isinstance(v, dict):
        return {k: (round(x / 100, 2) if k in MONEY or isinstance(x, int) and k in STATEMENT_KEYS else _to_sar(x)) for k, x in v.items()}
    return v


MONEY = {"amount", "difference"}
STATEMENT_KEYS = {"bank_closing", "outstanding_cheques", "deposits_in_transit", "book_closing", "bank_debits", "bank_credits",
                  "errors", "duplicates", "adjusted_bank", "adjusted_book"}


def previous_from(carry_forward: list[dict]) -> list[dict]:
    """A saved carry-forward list (riyals) → entries for the next run (halalas)."""
    return [{"date": e["date"], "description": e["description"], "ref": e.get("ref", ""), "amount": cents(e["amount"])}
            for e in carry_forward]


__all__ = ["ReconcileError", "read_table", "normalize", "match", "reconcile", "previous_from", "parse_amount", "parse_date"]
