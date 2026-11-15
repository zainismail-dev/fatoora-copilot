"""The HTTP layer end to end. Needs the packages from requirements.txt (skipped otherwise)."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, db  # noqa: E402
from app.main import app  # noqa: E402

from .conftest import fake_provider  # noqa: E402

PDF = ("inv.pdf", b"%PDF-1.4 fake", "application/pdf")


@pytest.fixture
def client(use_providers, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "admin_email", "manager@example.com")
    monkeypatch.setattr(settings, "admin_password", "password123")
    use_providers(fake_provider("gemini"))
    with TestClient(app) as c:
        auth.create_user("clerk@example.com", "Sara", "clerk", "password123")
        yield c


def sign_in(c, email):
    assert c.post("/api/login", json={"email": email, "password": "password123"}).status_code == 200


def test_pages_need_sign_in(client):
    assert client.get("/", follow_redirects=False).status_code in (302, 307)
    assert client.get("/api/invoices").status_code == 401
    assert client.post("/api/login", json={"email": "manager@example.com", "password": "bad"}).status_code == 401


def test_manager_flow(client):
    sign_in(client, "manager@example.com")
    assert client.get("/").status_code == 200
    inv = client.post("/api/invoices/upload", files={"file": PDF}).json()["invoice"]
    assert inv["status"] == "pending"
    assert client.get("/api/invoices").json()["invoices"][0]["id"] == inv["id"]
    assert client.get(f"/api/invoices/{inv['id']}/file").status_code == 200
    done = client.post(f"/api/invoices/{inv['id']}/decide", json={"action": "approve"}).json()
    assert done["invoice"]["status"] == "approved"
    again = client.post(f"/api/invoices/{inv['id']}/decide", json={"action": "approve"})
    assert again.status_code == 400 and again.json()["code"] == "already_approved"


def test_clerk_cannot_approve(client):
    sign_in(client, "clerk@example.com")
    inv = client.post("/api/invoices/upload", files={"file": PDF}).json()["invoice"]
    assert client.post(f"/api/invoices/{inv['id']}/decide", json={"action": "approve"}).status_code == 403


def test_email_link(client):
    sign_in(client, "manager@example.com")
    inv = client.post("/api/invoices/upload", files={"file": PDF}).json()["invoice"]
    token = db.one("SELECT token FROM invoices WHERE id = ?", (inv["id"],))["token"]
    client.post("/api/logout")
    ok = client.get("/decide", params={"id": inv["id"], "action": "approve", "token": token})
    assert ok.status_code == 200 and "Invoice approved" in ok.text
    reused = client.get("/decide", params={"id": inv["id"], "action": "approve", "token": token})
    assert reused.status_code == 400


def test_csv_delete_and_throttle(client):
    sign_in(client, "manager@example.com")
    inv = client.post("/api/invoices/upload", files={"file": PDF}).json()["invoice"]
    csv = client.get("/api/invoices.csv")
    assert csv.status_code == 200 and inv["id"] in csv.text and csv.headers["content-type"].startswith("text/csv")
    assert client.get("/").headers["x-frame-options"] == "DENY"
    assert client.delete(f"/api/invoices/{inv['id']}").json()["ok"]
    assert client.get("/api/invoices").json()["invoices"] == []
    client.post("/api/logout")
    from app import auth as a
    a.throttle.reset("clerk@example.com")
    for _ in range(5):
        client.post("/api/login", json={"email": "clerk@example.com", "password": "wrong"})
    assert client.post("/api/login", json={"email": "clerk@example.com", "password": "password123"}).status_code == 429
    a.throttle.reset("clerk@example.com")


def test_clerk_cannot_delete(client):
    sign_in(client, "clerk@example.com")
    inv = client.post("/api/invoices/upload", files={"file": PDF}).json()["invoice"]
    assert client.delete(f"/api/invoices/{inv['id']}").status_code == 403


def test_ask_finance(client, monkeypatch):
    from app import assistant
    assert client.post("/api/ask", json={"question": "hi"}).status_code == 401
    sign_in(client, "clerk@example.com")
    monkeypatch.setattr(assistant, "text_models", lambda: [])
    assert client.post("/api/ask", json={"question": "hi"}).status_code == 503
    def model(system, question):
        return "Hello"
    model.__name__ = "gemini"
    monkeypatch.setattr(assistant, "text_models", lambda: [model])
    assert client.post("/api/ask", json={"question": "hi"}).json() == {"ok": True, "answer": "Hello", "by": "gemini"}
    assert client.post("/api/ask", json={"question": "  "}).status_code == 400
