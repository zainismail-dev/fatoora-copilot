"""AI reading: fallback order, manual entry when every provider is busy, cache, cleanup of model output."""
from app import extract
from app.extract import providers
from app.extract.prompt import normalize

from .conftest import BUSY, CLEAN, fake_provider


def test_first_provider_wins():
    a, b = fake_provider("gemini"), fake_provider("mistral")
    r = extract.extract(b"pdf-1", "application/pdf", [a, b])
    assert r.provider == "gemini" and r.data["invoice_number"] == "INV-2701" and len(b.calls) == 0


def test_falls_back_when_first_is_rate_limited():
    a, b = fake_provider("gemini", error=BUSY), fake_provider("mistral")
    r = extract.extract(b"pdf-2", "application/pdf", [a, b])
    assert r.provider == "mistral" and "gemini" in r.errors[0]


def test_any_provider_error_falls_through():
    a = fake_provider("gemini", error=providers.ProviderError("bad JSON"))
    r = extract.extract(b"pdf-3", "application/pdf", [a, fake_provider("mistral")])
    assert r.provider == "mistral"


def test_manual_entry_when_all_busy():
    r = extract.extract(b"pdf-4", "application/pdf", [fake_provider("gemini", error=BUSY), fake_provider("mistral", error=BUSY)])
    assert r.data is None and r.provider == "manual" and len(r.errors) == 2


def test_manual_entry_when_no_provider_configured():
    r = extract.extract(b"pdf-5", "application/pdf", [])
    assert r.data is None and "no AI provider" in r.errors[0]


def test_same_file_is_read_only_once():
    a = fake_provider("gemini")
    extract.extract(b"same-file", "application/pdf", [a])
    r = extract.extract(b"same-file", "application/pdf", [a])
    assert len(a.calls) == 1 and r.provider == "cache:gemini"


def test_normalize_cleans_model_output():
    out = normalize({"subtotal": "23,400.00", "vat_amount": None, "currency": "sar ", "is_invoice": "yes",
                     "lines": [{"description": " A ", "quantity": None}, "junk"], "invoice_date": "2026-11-12T00:00:00"})
    assert out["subtotal"] == 23400.0 and out["vat_amount"] == 0 and out["currency"] == "SAR"
    assert out["lines"] == [{"description": "A", "quantity": 1, "unit_price": 0.0, "amount": 0.0}]
    assert out["invoice_date"] == "2026-11-12" and out["is_invoice"] is True


def test_json_from_text_handles_code_fences():
    assert providers._json_from_text('```json\n{"a": 1}\n```') == {"a": 1}


def test_clean_fixture_is_valid():
    assert normalize(CLEAN)["total"] == 26910


def test_several_gemini_models_are_tried_in_order(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "gemini_api_key", "k")
    monkeypatch.setattr(settings, "gemini_model", "gemini-a, gemini-b ,")
    monkeypatch.setattr(settings, "mistral_api_key", "m")
    assert [p.__name__ for p in extract.configured_providers()] == ["gemini", "gemini", "mistral"]
