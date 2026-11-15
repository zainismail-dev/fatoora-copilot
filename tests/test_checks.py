"""The ZATCA pre-check rules, against the values printed on the 8 sample invoices."""
import pytest

from app.checks import digits_only, duplicate_key, run_checks


def inv(name, vat_no, no, sub, vat, total, cur="SAR"):
    return {"supplier_name_en": name, "supplier_vat_number": vat_no, "invoice_number": no, "invoice_date": "2026-11-12",
            "subtotal": sub, "vat_amount": vat, "total": total, "currency": cur, "is_invoice": True}


@pytest.mark.parametrize("label,invoice,status,failed", [
    ("01 clean", inv("Sahab Tech Solutions", "300512398700003", "INV-2701", 23400, 3510, 26910), "pending", []),
    ("02 clean", inv("Al Nada Stationery", "310228745600003", "ND-5602", 2980, 447, 3427), "pending", []),
    ("03 clean", inv("Rawasi Logistics", "300987654300003", "RW-1004", 18200, 2730, 20930), "pending", []),
    ("04 large", inv("Al Madar Maintenance", "300765432100003", "MD-1201", 58500, 8775, 67275), "pending", []),
    ("05 vat 14%", inv("Al Waha Printing", "302345678900003", "WP-3401", 4800, 672, 5472), "review", ["rate"]),
    ("06 vat no", inv("Lamsa Decor", "31045678901234", "LD-0051", 9800, 1470, 11270), "review", ["vatno"]),
    ("07 total", inv("Ufuq Telecom", "310987123400003", "UF-78010", 7075, 1061.25, 8236.25), "review", ["total"]),
    ("08 usd", inv("Cloudline Software", "300111222300003", "CL-1210", 1200, 0, 1200, "USD"), "review", ["rate", "cur"]),
    ("arabic digits", inv("Sahab", "٣٠٠٥١٢٣٩٨٧٠٠٠٠٣", "X-1", 100, 15, 115), "pending", []),
    ("rounding 1 SAR", inv("Sahab", "300512398700003", "X-2", 100.33, 15.5, 115.83), "pending", []),
])
def test_sample_invoices(label, invoice, status, failed):
    r = run_checks(invoice, {})
    assert r.status == status, label
    assert [c["k"] for c in r.checks if not c["pass"]] == failed, label


def test_large_amount_is_a_note_not_a_failure():
    r = run_checks(inv("Al Madar", "300765432100003", "MD-1", 58500, 8775, 67275), {})
    assert any(c["k"] == "large" and c.get("note") for c in r.checks) and r.status == "pending"


def test_duplicate_detected_and_dated():
    earlier = {duplicate_key("300512398700003", "Sahab", "INV-2701"): "2026-11-10"}
    r = run_checks(inv("Sahab", "300 512 398 700 003", "inv-2701", 23400, 3510, 26910), earlier)
    dup = next(c for c in r.checks if c["k"] == "dup")
    assert r.status == "review" and not dup["pass"] and dup["dupDate"] == "2026-11-10"


def test_missing_fields_and_not_an_invoice():
    assert run_checks({"supplier_name_en": "X", "total": 0}, {}).status == "review"
    r = run_checks(dict(inv("Sahab", "300512398700003", "A", 100, 15, 115), is_invoice=False), {})
    assert not next(c for c in r.checks if c["k"] == "fields")["pass"]


def test_digits_only():
    assert digits_only("VAT: ٣٠٠-١٢") == "30012"
