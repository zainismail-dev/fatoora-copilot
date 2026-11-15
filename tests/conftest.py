import pytest

from app import db, extract
from app.config import settings
from app.extract import providers

CLEAN = {"is_invoice": True, "supplier_name_ar": "شركة سحاب للحلول التقنية", "supplier_name_en": "Sahab Tech Solutions",
         "supplier_vat_number": "300512398700003", "invoice_number": "INV-2701", "invoice_date": "2026-11-12",
         "currency": "SAR", "subtotal": 23400, "vat_amount": 3510, "total": 26910,
         "lines": [{"description": "Annual software licences", "quantity": 10, "unit_price": 1800, "amount": 18000}]}


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    """Every test gets its own empty database and upload folder, with email and real AI turned off."""
    monkeypatch.setattr(settings, "database_path", tmp_path / "test.db")
    monkeypatch.setattr(settings, "uploads_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "gmail_address", "")
    monkeypatch.setattr(settings, "gmail_app_password", "")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "mistral_api_key", "")
    db.init(settings.database_path)
    yield


def fake_provider(name, result=None, error=None):
    calls = []

    def run(content, mime):
        calls.append((len(content), mime))
        if error:
            raise error
        return dict(result if result is not None else CLEAN)

    run.__name__ = name
    run.calls = calls
    return run


@pytest.fixture
def use_providers(monkeypatch):
    """use_providers(p1, p2, ...) makes the app use these fake AI providers."""
    def set_chain(*chain):
        monkeypatch.setattr(extract, "configured_providers", lambda: list(chain))
    return set_chain


BUSY = providers.ProviderBusy("HTTP 429: quota")
