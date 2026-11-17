"""Bank reconciliation: reading files, matching rules, the statement, carry-forward, Excel export."""
import io
import json
from pathlib import Path

import pytest

from app import reconcile as r
from app import reconciliations

SAMPLES = Path(__file__).resolve().parent.parent / "samples" / "bank"
USER = {"name": "Maha", "email": "m@x.sa", "role": "manager"}


def rows(name):
    return r.read_table((SAMPLES / name).read_bytes(), name)


def test_parsing_amounts_and_dates():
    assert r.parse_amount("1,234.50") == 123450 and r.parse_amount("(1,234.50)") == -123450
    assert r.parse_amount("1234.50-") == -123450 and r.parse_amount("SAR ١٬٢٣٤٫٥") == 123450 and r.parse_amount("") == 0
    assert r.parse_date("05/11/2026").isoformat() == "2026-11-05"      # day first
    assert r.parse_date("2026-11-05").isoformat() == "2026-11-05"
    assert r.parse_date("5 Nov 2026").isoformat() == "2026-11-05"
    assert r.parse_date("٠٥/١١/٢٠٢٦").isoformat() == "2026-11-05" and r.parse_date("Opening") is None
    assert r.clean_ref("Chq# 000123", "") == "123" and r.clean_ref("", "CHQ PRESENTED CHQ NO 100237") == "100237"


def test_october_balances_to_zero():
    o = r.reconcile(rows("bank-statement-oct-2026.csv"), rows("cash-book-oct-2026.csv"))
    st = o["statement"]
    assert (st["bank_closing"], st["book_closing"], st["difference"]) == (974954.5, 982864.75, 0)
    assert [e["ref"] for e in o["outstanding"]] == ["100234", "100235"]
    assert [e["amount"] for e in o["in_transit"]] == [32000]
    assert [e["kind"] for e in o["bank_only"]] == ["charges", "charges"]
    assert len(o["carry_forward"]) == 3


def test_november_explains_the_whole_gap():
    october = r.reconcile(rows("bank-statement-oct-2026.csv"), rows("cash-book-oct-2026.csv"))
    n = r.reconcile(rows("bank-statement-nov-2026.csv"), rows("cash-book-nov-2026.csv"), r.previous_from(october["carry_forward"]))
    st = n["statement"]
    assert (st["bank_closing"], st["book_closing"]) == (1001646.6, 928174.25)
    assert st["outstanding_cheques"] == -106955 and st["deposits_in_transit"] == 41600
    assert (st["bank_debits"], st["bank_credits"], st["errors"], st["duplicates"]) == (-1282.25, 1284.6, 900, 7215)
    assert st["adjusted_bank"] == st["adjusted_book"] == 936291.6 and st["difference"] == 0
    # October's late items clear in November; the furniture cheque stays outstanding and carries again
    assert sorted(p["book"]["ref"] or "deposit" for p in n["cleared_from_previous"]) == ["100234", "deposit"]
    assert [(e["ref"], e.get("previous", False)) for e in n["outstanding"]] == [("100235", True), ("100241", False), ("100242", False)]
    assert [(e["book"]["amount"], e["bank"]["amount"]) for e in n["errors"]] == [(-15400, -14500)]
    assert [d["amount"] for d in n["duplicates"]] == [-7215]
    assert {p["how"] for p in n["matched"]} == {"cheque", "same_date", "near_date"}


def test_unique_amount_and_stale_cheque():
    bank = [["Date", "Description", "Amount", "Balance"], ["30/11/2026", "Transfer", "-4,000", "96,000"]]
    book = [["Date", "Description", "Amount", "Balance"], ["01/11/2026", "Supplier transfer", "-4000", "92,500"]]
    previous = [{"date": "2026-04-02", "description": "Old cheque", "ref": "999", "amount": -350000}]
    res = r.reconcile(bank, book, previous)
    assert res["matched"][0]["how"] == "unique_amount"           # 29 days apart, but the only 4,000 on each side
    assert res["outstanding"][0]["stale"] and res["statement"]["difference"] == 0


def test_signs_follow_each_side():
    """A bank 'Debit' is money out; a cash book 'Debit' (مدين) is money in."""
    bank = [["Date", "Description", "Debit", "Credit", "Balance"], ["01/11/2026", "Fee", "10", "", "990"]]
    book = [["التاريخ", "البيان", "مدين", "دائن", "الرصيد"], ["01/11/2026", "إيداع", "500", "", "1,500"]]
    res = r.reconcile(bank, book)
    assert res["bank_only"][0]["amount"] == -10 and res["in_transit"][0]["amount"] == 500


def test_clear_errors():
    with pytest.raises(r.ReconcileError) as e:
        r.reconcile([["When", "What"], ["x", "y"]], [["Date", "Amount"]])
    assert e.value.code == "no_columns"
    with pytest.raises(r.ReconcileError) as e:
        r.reconcile([["Date", "Amount"], ["01/11/2026", "5"]], [["Date", "Amount"], ["01/11/2026", "5"]])
    assert e.value.code == "no_balance"
    res = r.reconcile([["Date", "Amount"], ["01/11/2026", "5"]], [["Date", "Amount"], ["01/11/2026", "5"]], bank_closing=100, book_closing=100)
    assert res["statement"]["difference"] == 0
    with pytest.raises(r.ReconcileError):
        r.read_table(b"x", "statement.pdf")


def run(name, month):
    return reconciliations.run(*[(SAMPLES / f).read_bytes() if i % 2 == 0 else f for i, f in
                                 enumerate([f"bank-statement-{month}.csv"] * 2 + [f"cash-book-{month}.csv"] * 2)], USER)


def test_saved_runs_carry_forward_and_export():
    oct_ = run("oct", "oct-2026")
    nov = run("nov", "nov-2026")
    assert nov["result"]["previous"]["id"] == oct_["id"] and nov["difference"] == 0
    assert [x["period_end"] for x in reconciliations.list_all()] == ["2026-11-30", "2026-10-31"]
    again = run("nov", "nov-2026")                                   # same month again replaces it
    assert len(reconciliations.list_all()) == 2 and again["id"] != nov["id"]

    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(reconciliations.xlsx(again["id"])))
    assert wb.sheetnames[:3] == ["Summary", "Outstanding cheques", "Deposits in transit"]
    summary = {row[0]: row[1] for row in wb["Summary"].iter_rows(values_only=True) if row[0]}
    assert summary["Balance as per bank statement"] == 1001646.6 and summary["Difference (should be 0)"].startswith("=ROUND")
    assert wb["Outstanding cheques"].max_row == 4
    json.dumps(again)  # the API can send it


# ---------- the browser copy of the engine (GitHub Pages demo) must agree with this one ----------
NODE = __import__("shutil").which("node")


def same(a, b, path="$"):
    if isinstance(a, dict):
        assert isinstance(b, dict) and a.keys() == b.keys(), f"{path}: keys {sorted(a)} vs {sorted(b) if isinstance(b, dict) else b}"
        for k in a:
            same(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        assert isinstance(b, list) and len(a) == len(b), f"{path}: length {len(a)} vs {len(b) if isinstance(b, list) else b}"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            same(x, y, f"{path}[{i}]")
    elif isinstance(a, float) or isinstance(b, float):
        assert abs(a - b) < 0.001, f"{path}: {a} vs {b}"
    else:
        assert a == b, f"{path}: {a!r} vs {b!r}"


@pytest.mark.skipif(NODE is None, reason="Node.js not installed")
def test_browser_engine_gives_identical_results():
    import subprocess
    root = SAMPLES.parent.parent
    script = """
      const fs = require('fs'), e = require('./web/reconcile.js');
      const read = (n) => e.readCsv(fs.readFileSync('samples/bank/' + n, 'utf8'));
      const oct = e.reconcile(read('bank-statement-oct-2026.csv'), read('cash-book-oct-2026.csv'));
      const nov = e.reconcile(read('bank-statement-nov-2026.csv'), read('cash-book-nov-2026.csv'), e.previousFrom(oct.carry_forward));
      const small = e.reconcile([['Date','Description','Amount','Balance'],['30/11/2026','Transfer','-4,000','96,000']],
        [['Date','Description','Amount','Balance'],['01/11/2026','Supplier transfer','-4000','92,500']],
        [{date:'2026-04-02', description:'Old cheque', ref:'999', amount:-350000}]);
      console.log(JSON.stringify([oct, nov, small]));
    """
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30, cwd=root)
    assert out.returncode == 0, out.stderr
    js = json.loads(out.stdout)
    october = r.reconcile(rows("bank-statement-oct-2026.csv"), rows("cash-book-oct-2026.csv"))
    november = r.reconcile(rows("bank-statement-nov-2026.csv"), rows("cash-book-nov-2026.csv"), r.previous_from(october["carry_forward"]))
    small = r.reconcile([["Date", "Description", "Amount", "Balance"], ["30/11/2026", "Transfer", "-4,000", "96,000"]],
                        [["Date", "Description", "Amount", "Balance"], ["01/11/2026", "Supplier transfer", "-4000", "92,500"]],
                        [{"date": "2026-04-02", "description": "Old cheque", "ref": "999", "amount": -350000}])
    for py, j in zip([october, november, small], js, strict=True):
        same(json.loads(json.dumps(py)), j)
