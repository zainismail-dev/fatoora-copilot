"""ZATCA-style pre-checks for supplier invoices you RECEIVE. Plain rules, no AI.

These are pre-checks, not certified e-invoicing (FATOORA).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
VAT_RATE = 0.15


def digits_only(value: object) -> str:
    return re.sub(r"\D", "", str(value or "").translate(ARABIC_DIGITS))


def round2(value: object) -> float:
    try:
        return round(float(value or 0) + 1e-9, 2)
    except (TypeError, ValueError):
        return 0.0


def duplicate_key(vat_no: str, supplier: str, invoice_no: str) -> str:
    who = digits_only(vat_no) or (supplier or "").strip().upper()
    return f"{who}|{(invoice_no or '').strip().upper()}"


@dataclass
class CheckResult:
    checks: list[dict]
    status: str  # "pending" (clean) or "review"
    vat_no: str
    subtotal: float
    vat: float
    total: float
    currency: str


def run_checks(inv: dict, earlier: dict[str, str], large_amount_sar: float = 50000) -> CheckResult:
    """inv: extracted fields. earlier: duplicate_key -> invoice_date of invoices already in the ledger."""
    checks: list[dict] = []
    vat_no = digits_only(inv.get("supplier_vat_number"))
    checks.append({"k": "vatno", "pass": bool(re.fullmatch(r"3\d{13}3", vat_no))})

    sub, vat, total = round2(inv.get("subtotal")), round2(inv.get("vat_amount")), round2(inv.get("total"))
    expected = round2(sub * VAT_RATE)
    checks.append({"k": "rate", "pass": abs(vat - expected) <= 1, "expected": expected})
    diff = round2(total - sub - vat)
    checks.append({"k": "total", "pass": abs(diff) < 0.05, "diff": diff})

    name = (inv.get("supplier_name_ar") or "").strip() or (inv.get("supplier_name_en") or "").strip()
    has_fields = inv.get("is_invoice", True) is not False and bool(name) and bool((inv.get("invoice_number") or "").strip()) \
        and bool((inv.get("invoice_date") or "").strip()) and total > 0
    checks.append({"k": "fields", "pass": has_fields})

    key = duplicate_key(vat_no, inv.get("supplier_name_en") or name, inv.get("invoice_number") or "")
    dup_date = earlier.get(key)
    checks.append({"k": "dup", "pass": dup_date is None, **({"dupDate": dup_date} if dup_date is not None else {})})

    currency = (inv.get("currency") or "SAR").strip().upper() or "SAR"
    checks.append({"k": "cur", "pass": currency == "SAR"})
    if currency == "SAR" and total > large_amount_sar:
        checks.append({"k": "large", "pass": True, "note": True})

    status = "review" if any(not c["pass"] for c in checks) else "pending"
    return CheckResult(checks, status, vat_no, sub, vat, total, currency)
