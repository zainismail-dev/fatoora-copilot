"""Reads an invoice file with AI: cache first, then each configured provider in order.

If every provider is busy or missing, the invoice is saved for manual entry, so nothing is lost
and the rest of the app keeps working without AI.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .. import db
from ..config import settings
from . import providers
from .prompt import normalize

log = logging.getLogger("fatoora.extract")
Provider = Callable[[bytes, str], dict]


@dataclass
class Extraction:
    data: dict | None      # normalized fields, or None when manual entry is needed
    provider: str          # gemini | mistral | cache:gemini | manual
    errors: list[str]


def configured_providers() -> list[Provider]:
    found: list[Provider] = []
    if settings.gemini_api_key:  # GEMINI_MODEL may list several models, tried in order
        for model in [m.strip() for m in settings.gemini_model.split(",") if m.strip()]:
            found.append(providers.gemini(settings.gemini_api_key, model))
    if settings.mistral_api_key:
        found.append(providers.mistral(settings.mistral_api_key, settings.mistral_model))
    return found


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def extract(content: bytes, mime: str, chain: list[Provider] | None = None) -> Extraction:
    digest = sha256(content)
    cached = db.one("SELECT provider, data FROM extraction_cache WHERE sha256 = ?", (digest,))
    if cached:
        return Extraction(json.loads(cached["data"]), f"cache:{cached['provider']}", [])

    errors: list[str] = []
    for provider in configured_providers() if chain is None else chain:
        name = getattr(provider, "__name__", "provider")
        try:
            data = normalize(provider(content, mime))
        except providers.ProviderError as e:  # includes ProviderBusy
            log.warning("%s failed: %s", name, e)
            errors.append(f"{name}: {e}")
            continue
        db.insert("extraction_cache", {"sha256": digest, "provider": name, "data": db.dumps(data),
                                       "created_at": datetime.now(UTC).isoformat(timespec="seconds")})
        return Extraction(data, name, errors)

    if not errors:
        errors.append("no AI provider configured (add GEMINI_API_KEY or MISTRAL_API_KEY to .env)")
    return Extraction(None, "manual", errors)
