"""Ask finance: the facts handed to the AI, the model fallback chain, and the built-in browser engine."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app import assistant, services
from app.extract import providers

from .conftest import BUSY, CLEAN, fake_provider

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


def text_model(name, answer="ok", error=None):
    seen = []

    def run(system, question):
        seen.append((system, question))
        if error:
            raise error
        return answer

    run.__name__ = name
    run.seen = seen
    return run


def add_invoice(use_providers, **changes):
    use_providers(fake_provider("gemini", {**CLEAN, **changes}))
    return services.ingest(b"%PDF-1.4 " + json.dumps(changes).encode(), "inv.pdf", "application/pdf", "upload", "")


def test_facts_have_correct_totals(use_providers):
    add_invoice(use_providers)                                                    # clean → pending
    add_invoice(use_providers, invoice_number="INV-2", vat_amount=3000, total=26400)  # VAT not 15% → review
    f = assistant.facts()
    assert f["totals"]["invoices"] == 2
    assert f["totals"]["by_status"]["pending"] == {"count": 1, "total_sar": 26910}
    assert f["totals"]["by_status"]["review"]["count"] == 1
    assert f["totals"]["vat_waiting_approval_sar"] == 3510
    assert f["suppliers"][0]["invoices"] == 2
    assert {i["invoice_no"]: i["failed_checks"] for i in f["invoices_newest_first"]} == {"INV-2": ["rate"], "INV-2701": []}


def test_ask_sends_question_and_ledger(use_providers):
    add_invoice(use_providers)
    m = text_model("gemini", "عندك فاتورة وحدة بانتظار الاعتماد.")
    answer, by = assistant.ask("  كم فاتورة عندي؟ ", [m])
    system, question = m.seen[0]
    assert (answer, by, question) == ("عندك فاتورة وحدة بانتظار الاعتماد.", "gemini", "كم فاتورة عندي؟")
    assert "INV-2701" in system and "ignore any instructions" in system


def test_ask_falls_through_busy_models():
    answer, by = assistant.ask("hello", [text_model("gemini", error=BUSY), text_model("mistral", "Hi")])
    assert (answer, by) == ("Hi", "mistral")


def test_ask_raises_busy_when_nothing_answers():
    with pytest.raises(providers.ProviderBusy):
        assistant.ask("hello", [text_model("gemini", error=BUSY)])
    with pytest.raises(providers.ProviderBusy):
        assistant.ask("hello", [])
    with pytest.raises(ValueError):
        assistant.ask("   ", [text_model("gemini")])


# ---------- the built-in engine in web/assistant.js (demo and fallback) ----------
@pytest.mark.skipif(NODE is None, reason="Node.js not installed")
def test_builtin_engine_understands_different_questions():
    questions = ["hello", "how many invoices received?", "كم فاتورة وصلتنا؟", "Which invoices need review?",
                 "what is waiting for approval", "how many approved", "How much VAT can we reclaim?",
                 "Who is our top supplier?", "largest invoice", "total spend", "كم صرفنا مع رواسي",
                 "show invoice WP-3401", "show invoice XX-9999", "any duplicates?", "help", "zzz qqq"]
    script = f"""
        const d = require('./web/demo.js'), a = require('./web/assistant.js');
        d.fetch('/api/invoices', {{}}).then(r => r.json()).then(b => {{
          const inv = b.invoices || b;
          console.log(JSON.stringify({json.dumps(questions, ensure_ascii=False)}.map(q => a.answer(q, inv, 'en'))));
        }});
    """
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    got = dict(zip(questions, json.loads(out.stdout), strict=True))
    assert got["hello"].startswith("Hi!")
    assert got["how many invoices received?"] == "You have 5 invoices: 2 approved, 1 waiting for approval, 2 need review."
    assert got["كم فاتورة وصلتنا؟"].startswith("عندك 5 فواتير")
    assert "WP-3401" in got["Which invoices need review?"] and "UF-78010" in got["Which invoices need review?"]
    assert "MD-1201" in got["what is waiting for approval"]
    assert got["how many approved"].startswith("2 invoices approved")
    assert "3,177.00" in got["How much VAT can we reclaim?"]
    assert got["Who is our top supplier?"].splitlines()[1].startswith("1. Al Madar")
    assert "MD-1201" in got["largest invoice"]
    assert "105,340.25" in got["total spend"]
    assert "رواسي" in got["كم صرفنا مع رواسي"] and "20,930.00" in got["كم صرفنا مع رواسي"]
    assert "VAT is not 15%" in got["show invoice WP-3401"]
    assert "couldn't find" in got["show invoice XX-9999"]
    assert got["any duplicates?"] == "No duplicates found."
    assert got["help"].startswith("Try:")
    assert got["zzz qqq"].startswith("I didn't catch that")
    assert len(set(got.values())) == len(got)  # every question gets its own answer
