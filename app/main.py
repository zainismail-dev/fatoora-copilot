"""Web server: pages, JSON API and the email approval link. Business logic lives in services.py.

Run:  uvicorn app.main:app --reload
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from . import assistant, auth, db, extract, mailer, reconcile, reconciliations, scheduler, services
from .config import ROOT, settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("fatoora")
WEB = ROOT / "web"


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init(settings.database_path)
    auth.ensure_admin(settings.admin_email, settings.admin_name, settings.admin_password)
    if len(settings.secret_key) < 24 or settings.secret_key.startswith("change-me"):
        log.warning("SECRET_KEY in .env is missing or short. Set a long random value before sharing this app.")
    if not extract.configured_providers():
        log.warning("No AI key set (GEMINI_API_KEY / MISTRAL_API_KEY). Invoices will open for manual entry.")
    task = asyncio.create_task(scheduler.run_forever())
    yield
    task.cancel()


app = FastAPI(title="Fatoora Copilot", version="1.0", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax", max_age=60 * 60 * 12)
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.middleware("http")
async def no_stale_pages(request: Request, call_next):
    """Browsers must re-check the app's pages and scripts, so updates show up after a normal refresh."""
    response = await call_next(request)
    if request.url.path in ("/", "/login") or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@app.exception_handler(services.ActionError)
async def action_error(_: Request, e: services.ActionError):
    return JSONResponse({"ok": False, "code": e.code, "message": str(e)}, status_code=404 if e.code == "not_found" else 400)


@app.exception_handler(reconcile.ReconcileError)
async def reconcile_error(_: Request, e: reconcile.ReconcileError):
    return JSONResponse({"ok": False, "code": e.code, "message": str(e)}, status_code=404 if e.code == "not_found" else 400)


# ---------- auth ----------
def current_user(request: Request) -> dict:
    user = auth.get_user(request.session.get("uid"))
    if not user:
        raise HTTPException(401, "Sign in first")
    return user


def manager(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "manager":
        raise HTTPException(403, "Only finance managers can do this")
    return user


class Login(BaseModel):
    email: str
    password: str


class Decision(BaseModel):
    action: str
    reason: str = ""


class Question(BaseModel):
    question: str


class Details(BaseModel):
    supplier_name_ar: str = ""
    supplier_name_en: str = ""
    supplier_vat_number: str = ""
    invoice_number: str = ""
    invoice_date: str = ""
    currency: str = "SAR"
    subtotal: float = 0
    vat_amount: float = 0
    total: float = 0


@app.post("/api/login")
def login(body: Login, request: Request):
    key = body.email.strip().lower()
    if auth.throttle.blocked(key):
        return JSONResponse({"ok": False, "code": "too_many"}, status_code=429)
    user = auth.authenticate(body.email, body.password)
    if not user:
        auth.throttle.fail(key)
        return JSONResponse({"ok": False, "code": "bad_login"}, status_code=401)
    auth.throttle.reset(key)
    request.session["uid"] = user["id"]
    return {"ok": True, "user": user}


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return {"user": user, "company": settings.company_name, "inbox": settings.gmail_address,
            "email_enabled": settings.email_enabled, "ai": [p.__name__ for p in extract.configured_providers()]}


# ---------- pages ----------
@app.get("/", include_in_schema=False)
def home(request: Request):
    if not auth.get_user(request.session.get("uid")):
        return RedirectResponse("/login")
    return FileResponse(WEB / "index.html")


@app.get("/login", include_in_schema=False)
def login_page():
    return FileResponse(WEB / "login.html")


# ---------- invoices ----------
@app.get("/api/invoices")
def invoices(_: dict = Depends(current_user)):
    return {"invoices": services.list_invoices()}


@app.post("/api/ask")
def ask(body: Question, _: dict = Depends(current_user)):
    """Ask finance with AI. 503 means no AI could answer; the app then uses its built-in answers."""
    try:
        answer, by = assistant.ask(body.question)
    except ValueError:
        return JSONResponse({"ok": False, "code": "empty"}, status_code=400)
    except extract.providers.ProviderBusy:
        return JSONResponse({"ok": False, "code": "ai_busy"}, status_code=503)
    return {"ok": True, "answer": answer, "by": by}


@app.get("/api/invoices.csv")
def invoices_csv(_: dict = Depends(current_user)):
    return Response(services.ledger_csv(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="fatoora-ledger.csv"'})


@app.post("/api/invoices/upload")
def upload(file: UploadFile = File(...), user: dict = Depends(current_user)):
    invoice = services.ingest(file.file.read(), file.filename or "invoice", file.content_type, source="upload", sender=user["email"])
    return {"ok": True, "invoice": invoice}


@app.put("/api/invoices/{invoice_id}/details")
def details(invoice_id: str, body: Details, user: dict = Depends(current_user)):
    return {"ok": True, "invoice": services.update_details(invoice_id, body.model_dump(), user)}


@app.post("/api/invoices/{invoice_id}/retry")
def retry(invoice_id: str, _: dict = Depends(current_user)):
    return {"ok": True, "invoice": services.retry_ai(invoice_id)}


@app.post("/api/invoices/{invoice_id}/decide")
def decide(invoice_id: str, body: Decision, user: dict = Depends(manager)):
    return {"ok": True, "invoice": services.decide(invoice_id, body.action, reason=body.reason, decided_by=user["email"])}


@app.delete("/api/invoices/{invoice_id}")
def delete(invoice_id: str, _: dict = Depends(manager)):
    services.delete_invoice(invoice_id)
    return {"ok": True}


@app.get("/api/invoices/{invoice_id}/file")
def invoice_file(invoice_id: str, _: dict = Depends(current_user)):
    path, mime = services.file_for(invoice_id)
    return FileResponse(path, media_type=mime, filename=path.name.split("_", 1)[-1])


# ---------- bank reconciliation ----------
def _balance(v: str) -> float | None:
    v = (v or "").strip()
    return reconcile.parse_amount(v) / 100 if v else None


@app.post("/api/reconciliations")
def run_reconciliation(bank: UploadFile = File(...), book: UploadFile = File(...), bank_closing: str = Form(""),
                       book_closing: str = Form(""), user: dict = Depends(current_user)):
    rec = reconciliations.run(bank.file.read(), bank.filename or "bank.csv", book.file.read(), book.filename or "book.csv",
                              user, _balance(bank_closing), _balance(book_closing))
    return {"ok": True, "reconciliation": rec}


@app.get("/api/reconciliations")
def list_reconciliations(_: dict = Depends(current_user)):
    return {"reconciliations": reconciliations.list_all()}


@app.get("/api/reconciliations/{rid}")
def get_reconciliation(rid: str, _: dict = Depends(current_user)):
    return {"reconciliation": reconciliations.get(rid)}


@app.get("/api/reconciliations/{rid}/xlsx")
def reconciliation_xlsx(rid: str, _: dict = Depends(current_user)):
    return Response(reconciliations.xlsx(rid), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="bank-reconciliation-{rid}.xlsx"'})


@app.delete("/api/reconciliations/{rid}")
def delete_reconciliation(rid: str, _: dict = Depends(manager)):
    reconciliations.delete(rid)
    return {"ok": True}


# ---------- email approval link (the token is the permission) ----------
@app.get("/decide", response_class=HTMLResponse, include_in_schema=False)
def decide_from_email(id: str = "", action: str = "", token: str = ""):
    try:
        inv = services.decide(id, action, reason="Rejected from the approval email" if action == "reject" else "",
                              decided_by="email link", token=token)
        return mailer.result_page(inv["status"], f"{inv['supplier']['ar'] or inv['supplier']['en']} · {inv['number']}")
    except services.ActionError as e:
        return HTMLResponse(mailer.result_page(e.code), status_code=400)


@app.get("/api/health")
def health():
    return {"ok": True, "ai": [p.__name__ for p in extract.configured_providers()], "email": settings.email_enabled}
