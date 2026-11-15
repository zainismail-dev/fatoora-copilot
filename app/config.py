"""Settings, read once from environment variables (and the .env file in the project root)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:  # python-dotenv is optional at import time so tests can run without it
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # pragma: no cover
    pass


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass
class Settings:
    app_url: str = field(default_factory=lambda: _env("APP_URL", "http://localhost:8000").rstrip("/"))
    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY", "change-me-in-.env"))
    company_name: str = field(default_factory=lambda: _env("COMPANY_NAME", "Al Riyada Trading Co."))
    database_path: Path = field(default_factory=lambda: ROOT / _env("DATABASE_PATH", "data/fatoora.db"))
    uploads_dir: Path = field(default_factory=lambda: ROOT / _env("UPLOADS_DIR", "data/uploads"))
    large_amount_sar: float = field(default_factory=lambda: float(_env("LARGE_AMOUNT_SAR", "50000")))

    # AI providers, tried in this order. Leave a key empty to skip that provider.
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-3.6-flash,gemini-3.5-flash,gemini-2.5-flash"))
    mistral_api_key: str = field(default_factory=lambda: _env("MISTRAL_API_KEY"))
    mistral_model: str = field(default_factory=lambda: _env("MISTRAL_MODEL", "mistral-small-latest"))

    # First admin account, created on first start if no users exist.
    admin_email: str = field(default_factory=lambda: _env("ADMIN_EMAIL", "manager@example.com").lower())
    admin_password: str = field(default_factory=lambda: _env("ADMIN_PASSWORD", "change-me"))
    admin_name: str = field(default_factory=lambda: _env("ADMIN_NAME", "Finance Manager"))

    # Gmail (app password). Leave empty to turn email features off.
    gmail_address: str = field(default_factory=lambda: _env("GMAIL_ADDRESS"))
    gmail_app_password: str = field(default_factory=lambda: _env("GMAIL_APP_PASSWORD").replace(" ", ""))
    approver_email: str = field(default_factory=lambda: _env("APPROVER_EMAIL"))
    email_poll_seconds: int = field(default_factory=lambda: int(_env("EMAIL_POLL_SECONDS", "60")))

    @property
    def email_enabled(self) -> bool:
        return bool(self.gmail_address and self.gmail_app_password)


settings = Settings()
