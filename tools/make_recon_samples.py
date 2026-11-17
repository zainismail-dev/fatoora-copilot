"""Builds the sample bank statements and cash books in samples/bank/ (October and November 2026).

Every case the reconciliation must handle is planted on purpose:
cheques cashed days later · cheques still outstanding · a deposit in transit · bank fees, profit and an
auto-debit missing from the books · a cheque recorded with the wrong amount · an entry posted twice ·
October items that clear (or don't) in November.
Run: python tools/make_recon_samples.py
"""
import csv
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "samples" / "bank"

# (book date, bank date or None, cheque no, book description (Arabic), bank description, amount; + optional bank amount)
OCT = [
    ("2026-10-02", "2026-10-02", "", "تحويل وارد من شركة نجد للمقاولات", "INWARD TRF NAJD CONTRACTING CO", 120000),
    ("2026-10-05", "2026-10-09", "100231", "شيك لمؤسسة الندى للقرطاسية", "CHQ PRESENTED", -3427),
    ("2026-10-08", "2026-10-14", "100232", "شيك لشركة سحاب للحلول التقنية", "CHQ PRESENTED", -26910),
    ("2026-10-10", "2026-10-10", "", "رواتب شهر أكتوبر", "PAYROLL WPS OCT", -185000),
    ("2026-10-15", "2026-10-16", "", "إيداع شيك عميل - مؤسسة البناء", "CHEQUE DEPOSIT AL BINA EST", 45500),
    ("2026-10-20", "2026-10-23", "100233", "شيك لأفق للاتصالات", "CHQ PRESENTED", -8236.25),
    ("2026-10-25", "2026-10-25", "", "سداد فاتورة الكهرباء", "SADAD SAUDI ELECTRICITY", -6840),
    ("2026-10-28", "2026-11-04", "100234", "شيك لمطابع الواحة", "CHQ PRESENTED", -5472),
    ("2026-10-30", None, "100235", "شيك لشركة الخليج للأثاث المكتبي", "", -18750),
    ("2026-10-31", "2026-11-02", "", "إيداع شيك عميل - شركة الصفوة", "CHEQUE DEPOSIT AL SAFWA CO", 32000),
    (None, "2026-10-31", "", "", "ACCOUNT MAINTENANCE FEE", -115),
    (None, "2026-10-31", "", "", "VAT ON BANK CHARGES", -17.25),
]
NOV = [
    ("2026-11-03", "2026-11-03", "", "تحويل وارد من شركة نجد للمقاولات", "INWARD TRF NAJD CONTRACTING CO", 250000),
    ("2026-11-05", "2026-11-12", "100236", "شيك لمؤسسة الندى للقرطاسية", "CHQ PRESENTED", -3427),
    ("2026-11-09", "2026-11-17", "100237", "شيك لشركة سحاب للحلول التقنية", "CHQ PRESENTED", -26910),
    ("2026-11-10", "2026-11-10", "", "رواتب شهر نوفمبر", "PAYROLL WPS NOV", -186500),
    ("2026-11-12", "2026-11-13", "", "اشتراكات التأمينات الاجتماعية", "GOSI CONTRIBUTION", -21300),
    ("2026-11-15", "2026-11-19", "100238", "شيك لمؤسسة المطلق للصيانة", "CHQ PRESENTED", -15400, -14500),
    ("2026-11-16", "2026-11-18", "100239", "شيك إيجار المكتب", "CHQ PRESENTED", -60000),
    ("2026-11-18", "2026-11-19", "", "تحويل وارد من مؤسسة البناء", "INWARD TRF AL BINA EST", 78250),
    ("2026-11-20", "2026-11-20", "", "سداد فاتورة الكهرباء", "SADAD SAUDI ELECTRICITY", -7215),
    ("2026-11-20", None, "", "سداد فاتورة الكهرباء", "", -7215),          # posted twice in the books
    ("2026-11-25", "2026-11-27", "100240", "شيك لأفق للاتصالات", "CHQ PRESENTED", -8236.25),
    ("2026-11-26", None, "100241", "شيك لشركة رواسي للخدمات اللوجستية", "", -20930),
    ("2026-11-28", None, "100242", "شيك لشركة المدار للصيانة", "", -67275),
    ("2026-11-30", None, "", "إيداع شيك عميل - شركة الرياض للأغذية", "", 41600),
    (None, "2026-11-21", "", "", "STC BUSINESS AUTO DEBIT", -1150),
    (None, "2026-11-30", "", "", "PROFIT CREDIT", 1284.60),
    (None, "2026-11-30", "", "", "ACCOUNT MAINTENANCE FEE", -115),
    (None, "2026-11-30", "", "", "VAT ON BANK CHARGES", -17.25),
]


def dmy(iso):
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


def money(h):
    return f"{h / 100:,.2f}" if h else ""


def write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows([header, *rows])


def build(name, month, events, bank_open, book_open, earlier=()):
    """month = 'YYYY-MM'. The bank only shows what it processed that month, including last month's late cheques."""
    bank = [(b, desc, chq, round((ev[6] if len(ev) > 6 else amt) * 100)) for ev in [*earlier, *events]
            for (k, b, chq, _, desc, amt) in [ev[:6]] if b and b.startswith(month)]
    bank.sort(key=lambda r: r[0])
    rows, bal = [["", "Opening Balance", "", "", "", money(bank_open)]], bank_open
    for i, (d, desc, chq, a) in enumerate(bank):
        bal += a
        # half the cheques carry their number in the Cheque No column, half only inside the description
        if chq and i % 2:
            desc, chq = f"{desc} CHQ NO {chq}", ""
        rows.append([dmy(d), desc, chq, money(-a if a < 0 else 0), money(a if a > 0 else 0), money(bal)])
    write(OUT / f"bank-statement-{name}.csv", ["Date", "Description", "Cheque No", "Debit", "Credit", "Balance"], rows)
    bank_close = bal

    book = sorted([(k, chq, d, round(amt * 100)) for (k, _, chq, d, _, amt, *rest) in events if k], key=lambda r: r[0])
    rows, bal = [["", "", "", "رصيد افتتاحي", "", "", money(book_open)]], book_open
    for n, (d, chq, desc, a) in enumerate(book, start=1):
        bal += a
        rows.append([dmy(d), f"PV-{name[:3].upper()}-{n:03d}", chq, desc, money(a if a > 0 else 0), money(-a if a < 0 else 0), money(bal)])
    write(OUT / f"cash-book-{name}.csv", ["التاريخ", "رقم السند", "رقم الشيك", "البيان", "مدين", "دائن", "الرصيد"], rows)
    return bank_close, bal


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    bank_oct, book_oct = build("oct-2026", "2026-10", OCT, 104_000_000, 104_000_000)
    # after October's reconciliation the accountant posted October's bank fees (132.25) in the books
    bank_nov, book_nov = build("nov-2026", "2026-11", NOV, bank_oct, book_oct - 13_225, OCT)
    print(f"October:  bank {bank_oct / 100:,.2f}  books {book_oct / 100:,.2f}")
    print(f"November: bank {bank_nov / 100:,.2f}  books {book_nov / 100:,.2f}")
