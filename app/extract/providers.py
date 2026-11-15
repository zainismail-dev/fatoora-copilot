"""AI providers. Each one takes the file bytes and returns the invoice fields as a dict.

A provider raises:
- ProviderBusy when it is rate-limited or temporarily down (the next provider is tried),
- ProviderError for anything else (also falls through to the next provider).
"""
from __future__ import annotations

import base64
import json
import re
import time
from collections.abc import Callable

from .prompt import GEMINI_SCHEMA, JSON_SHAPE_HINT, PROMPT

TIMEOUT = 90


class ProviderError(Exception):
    pass


class ProviderBusy(ProviderError):
    pass


def _client():
    import httpx  # imported lazily so the rest of the app (and its tests) don't need it

    return httpx


def _post(url: str, *, headers: dict | None = None, params: dict | None = None, payload: dict) -> dict:
    """POST with one quick retry on rate limits / server errors."""
    httpx = _client()
    for attempt in range(2):
        try:
            r = httpx.post(url, headers=headers, params=params, json=payload, timeout=TIMEOUT)
        except httpx.HTTPError as e:  # network problem or timeout
            if attempt == 0:
                time.sleep(2)
                continue
            raise ProviderBusy(f"network error: {e}") from e
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == 0:
                wait = str(r.headers.get("retry-after", ""))
                time.sleep(min(float(wait), 10) if wait.replace(".", "", 1).isdigit() else 3)
                continue
            raise ProviderBusy(f"HTTP {r.status_code}: {r.text[:200]}")
        if r.status_code >= 400:
            raise ProviderError(f"HTTP {r.status_code}: {r.text[:300]}")
        return r.json()
    raise ProviderBusy("no response")


def _json_from_text(text: str) -> dict:
    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ProviderError("the model did not return JSON")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ProviderError(f"invalid JSON from the model: {e}") from e


def gemini(api_key: str, model: str) -> Callable[[bytes, str], dict]:
    def run(content: bytes, mime: str) -> dict:
        payload = {
            "contents": [{"parts": [{"text": PROMPT},
                                    {"inline_data": {"mime_type": mime, "data": base64.b64encode(content).decode()}}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseSchema": GEMINI_SCHEMA},
        }
        data = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                     params={"key": api_key}, payload=payload)
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"unexpected Gemini response: {str(data)[:200]}") from e
        return _json_from_text(text)

    run.__name__ = "gemini"
    return run


def mistral(api_key: str, model: str) -> Callable[[bytes, str], dict]:
    """Two steps: Mistral OCR turns the PDF/image into text, then a chat model returns the JSON."""
    def run(content: bytes, mime: str) -> dict:
        headers = {"Authorization": f"Bearer {api_key}"}
        data_uri = f"data:{mime};base64,{base64.b64encode(content).decode()}"
        document = ({"type": "document_url", "document_url": data_uri} if mime == "application/pdf"
                    else {"type": "image_url", "image_url": data_uri})
        ocr = _post("https://api.mistral.ai/v1/ocr", headers=headers, payload={"model": "mistral-ocr-latest", "document": document})
        text = "\n\n".join(p.get("markdown", "") for p in ocr.get("pages", []))
        if not text.strip():
            raise ProviderError("OCR returned no text")
        chat = _post("https://api.mistral.ai/v1/chat/completions", headers=headers, payload={
            "model": model, "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": PROMPT + "\nReturn this JSON shape: " + JSON_SHAPE_HINT},
                         {"role": "user", "content": "Invoice text (OCR):\n\n" + text[:20000]}]})
        try:
            return _json_from_text(chat["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"unexpected Mistral response: {str(chat)[:200]}") from e

    run.__name__ = "mistral"
    return run


# ---------- plain text answers (used by the finance assistant) ----------
def gemini_text(api_key: str, model: str) -> Callable[[str, str], str]:
    def run(system: str, question: str) -> str:
        data = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                     params={"key": api_key}, payload={
                         "systemInstruction": {"parts": [{"text": system}]},
                         "contents": [{"role": "user", "parts": [{"text": question}]}],
                         "generationConfig": {"temperature": 0.2, "maxOutputTokens": 600}})
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"unexpected Gemini response: {str(data)[:200]}") from e

    run.__name__ = "gemini"
    return run


def mistral_text(api_key: str, model: str) -> Callable[[str, str], str]:
    def run(system: str, question: str) -> str:
        data = _post("https://api.mistral.ai/v1/chat/completions", headers={"Authorization": f"Bearer {api_key}"}, payload={
            "model": model, "temperature": 0.2, "max_tokens": 600,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": question}]})
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"unexpected Mistral response: {str(data)[:200]}") from e

    run.__name__ = "mistral"
    return run
