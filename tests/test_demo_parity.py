"""The GitHub Pages demo runs the pre-checks in JavaScript (web/demo.js).
These tests make sure it gives exactly the same results as the Python rules in app/checks.py."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.checks import duplicate_key, run_checks

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js not installed")

CASES = [
    {"supplier_name_en": "A", "supplier_vat_number": "300512398700003", "invoice_number": "X1", "invoice_date": "2026-11-12", "subtotal": 100, "vat_amount": 15, "total": 115},
    {"supplier_name_en": "A", "supplier_vat_number": "٣٠٠٥١٢٣٩٨٧٠٠٠٠٣", "invoice_number": "X2", "invoice_date": "2026-11-12", "subtotal": 100.33, "vat_amount": 15.5, "total": 115.83},
    {"supplier_name_en": "B", "supplier_vat_number": "3001", "invoice_number": "X3", "invoice_date": "2026-11-12", "subtotal": 100, "vat_amount": 14, "total": 120, "currency": "usd"},
    {"supplier_name_en": "", "supplier_name_ar": "", "invoice_number": "", "invoice_date": "", "subtotal": 0, "vat_amount": 0, "total": 0},
    {"supplier_name_en": "C", "supplier_vat_number": "300765432100003", "invoice_number": "X5", "invoice_date": "2026-11-12", "subtotal": 58500, "vat_amount": 8775, "total": 67275},
]


def run_js(script: str):
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_same_results_as_python_rules():
    earlier = {duplicate_key("300512398700003", "A", "X1"): "2026-11-01"}
    js = run_js(f"""
        const d = require('./web/demo.js');
        const cases = {json.dumps(CASES, ensure_ascii=False)};
        const earlier = {{[d._duplicateKey('300512398700003', 'A', 'X1')]: '2026-11-01'}};
        console.log(JSON.stringify(cases.map(c => d._runChecks(c, earlier))));
    """)
    for case, j in zip(CASES, js, strict=True):
        p = run_checks(case, earlier)
        assert j["status"] == p.status, case
        assert j["checks"] == p.checks, case
        assert (j["vatNo"], j["sub"], j["vat"], j["total"], j["currency"]) == (p.vat_no, p.subtotal, p.vat, p.total, p.currency)


def test_demo_samples_match_the_pdfs():
    """Each demo sample gets the status its PDF is designed to trigger."""
    js = run_js("""
        const d = require('./web/demo.js');
        const out = {};
        for (const [k, s] of Object.entries(d._samples)) out[k] = d._runChecks(s.fields, {});
        console.log(JSON.stringify(out));
    """)
    failed = {k: [c["k"] for c in v["checks"] if not c["pass"]] for k, v in js.items()}
    assert failed == {"sahab": [], "nada": [], "rawasi": [], "madar": [], "waha": ["rate"], "lamsa": ["vatno"],
                      "ufuq": ["total"], "cloud": ["rate", "cur"]}
    assert js["sahab"]["total"] == 26910 and js["ufuq"]["total"] == 8236.25 and js["waha"]["vat"] == 672
