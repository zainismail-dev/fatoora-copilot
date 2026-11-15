"""Users and passwords. PBKDF2-SHA256 from the standard library, no extra packages."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from datetime import UTC, datetime

from . import db

ITERATIONS = 310_000
ROLES = ("clerk", "manager")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt_b64, digest_b64 = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(iters))
        return hmac.compare_digest(digest, base64.b64decode(digest_b64))
    except (ValueError, TypeError):
        return False


def create_user(email: str, name: str, role: str, password: str) -> dict:
    email = email.strip().lower()
    if "@" not in email:
        raise ValueError("email must be a valid email address")
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    if db.one("SELECT id FROM users WHERE email = ?", (email,)):
        raise ValueError(f"a user with email {email} already exists")
    db.insert("users", {"email": email, "name": name.strip(), "role": role, "password_hash": hash_password(password),
                        "created_at": datetime.now(UTC).isoformat(timespec="seconds")})
    return public_user(db.one("SELECT * FROM users WHERE email = ?", (email,)))


def authenticate(email: str, password: str) -> dict | None:
    row = db.one("SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),))
    if row and verify_password(password or "", row["password_hash"]):
        return public_user(row)
    return None


def get_user(user_id: int | None) -> dict | None:
    if not user_id:
        return None
    row = db.one("SELECT * FROM users WHERE id = ?", (user_id,))
    return public_user(row) if row else None


def ensure_admin(email: str, name: str, password: str) -> None:
    """Create the first manager account if the database has no users yet."""
    if not db.one("SELECT id FROM users LIMIT 1"):
        if "@" not in (email or ""):
            raise ValueError("ADMIN_EMAIL in .env is empty or not an email address")
        if len(password) < 8:
            raise ValueError("ADMIN_PASSWORD in .env must be at least 8 characters")
        create_user(email, name, "manager", password)


def public_user(row: dict | None) -> dict | None:
    if not row:
        return None
    return {"id": row["id"], "email": row["email"], "name": row["name"], "role": row["role"]}


class LoginThrottle:
    """Blocks an email after too many failed sign-ins in a short time (in memory, per server)."""

    def __init__(self, max_failures: int = 5, window_seconds: int = 15 * 60, clock=time.monotonic):
        self.max_failures, self.window, self.clock = max_failures, window_seconds, clock
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        now = self.clock()
        hits = [t for t in self._failures.get(key, []) if now - t < self.window]
        self._failures[key] = hits
        return hits

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._recent(key)) >= self.max_failures

    def fail(self, key: str) -> None:
        with self._lock:
            self._recent(key).append(self.clock())

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


throttle = LoginThrottle()
