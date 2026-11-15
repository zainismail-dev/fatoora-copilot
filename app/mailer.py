"""Outgoing emails (Gmail SMTP with an app password) and the small pages shown after an email decision."""
from __future__ import annotations

import html
import json
import smtplib
from email.message import EmailMessage
from urllib.parse import quote

from .config import settings

INK, PAPER, NOTE, GREEN, RED, BLUE, SOFT, RULE = "#14302A", "#FAFCFA", "#123B31", "#0F7A50", "#B4322A", "#2A4D8F", "#5E6F69", "#C9D3CC"


def send(to: str, subject: str, body_html: str) -> None:
    msg = EmailMessage()
    msg["From"] = f"Fatoora Copilot <{settings.gmail_address}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content("This email needs an HTML-capable mail app.")
    msg.add_alternative(body_html, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(settings.gmail_address, settings.gmail_app_password)
        s.send_message(msg)


def _money(v: float) -> str:
    return f"{float(v or 0):,.2f}"


def _frame(title_ar: str, title_en: str, inner: str) -> str:
    return f"""<div dir="rtl" style="font-family:Tahoma,Arial,sans-serif;color:{INK};max-width:540px">
<div style="background:{NOTE};color:#E8F1EC;padding:18px 20px;border-radius:8px 8px 0 0">
<div style="font-size:13px;opacity:.8">فاتورة كوبايلت · Fatoora Copilot</div>
<div style="font-size:20px;font-weight:bold;margin-top:4px">{title_ar}</div>
<div style="font-size:13px;opacity:.8">{title_en}</div></div>
<div style="border:1px solid {RULE};border-top:0;padding:18px 20px;border-radius:0 0 8px 8px;background:{PAPER};font-size:14px">{inner}</div></div>"""


def _row(a: str, b: str) -> str:
    return f'<tr><td style="padding:6px 0;color:{SOFT}">{a}</td><td style="padding:6px 0;text-align:left;direction:ltr">{b}</td></tr>'


def approval_email(inv: dict) -> tuple[str, str]:
    name = html.escape(inv["supplier_ar"] or inv["supplier_en"])
    link = lambda action: f"{settings.app_url}/decide?id={quote(inv['id'])}&action={action}&token={quote(inv['token'])}"  # noqa: E731
    large = any(c.get("k") == "large" for c in json.loads(inv["checks"] or "[]"))
    inner = f"""<table style="width:100%;border-collapse:collapse">
{_row('المورد · Supplier', name)}{_row('رقم الفاتورة · Invoice no.', html.escape(inv['invoice_no']))}
{_row('التاريخ · Date', html.escape(inv['invoice_date']))}{_row('الضريبة · VAT', _money(inv['vat']) + ' ' + inv['currency'])}
{_row('<b>الإجمالي · Total</b>', '<b>' + _money(inv['total']) + ' ' + inv['currency'] + '</b>')}</table>
<p style="color:{GREEN};margin:14px 0 10px">✓ اجتازت كل الفحوصات المسبقة · Passed all pre-checks</p>
{f'<p style="color:{BLUE};margin:0 0 12px">! مبلغ أكبر من {settings.large_amount_sar:,.0f} ريال · Large amount</p>' if large else ''}
<a href="{link('approve')}" style="display:inline-block;background:{GREEN};color:#fff;text-decoration:none;padding:10px 18px;border-radius:6px;font-weight:bold">اعتمد · Approve</a>
&nbsp;<a href="{link('reject')}" style="display:inline-block;border:1px solid {RED};color:{RED};text-decoration:none;padding:9px 16px;border-radius:6px">ارفض · Reject</a>
<p style="font-size:12px;color:{SOFT};margin-top:16px">أو افتح التطبيق · Or open the app: <a href="{settings.app_url}" style="color:{BLUE}">{settings.app_url}</a></p>"""
    return f"اعتماد فاتورة · Approve invoice {inv['invoice_no']} · {inv['supplier_ar'] or inv['supplier_en']}", \
        _frame("فاتورة بانتظار اعتمادك", "An invoice is waiting for your approval", inner)


def digest_email(s: dict) -> tuple[str, str]:
    top = "".join(_row(html.escape(k), f"{v:,.0f}") for k, v in s["top"])
    inner = f"""<table style="width:100%;border-collapse:collapse">
{_row('فواتير هذا الأسبوع · Invoices this week', str(s['week_count']))}{_row('الإنفاق · Spend (SAR)', f"{s['week_spend']:,.0f}")}
{_row('بانتظار اعتمادك · Waiting for approval', str(s['pending']))}{_row('تحتاج مراجعة أو إدخال · Need review or entry', str(s['review']))}
{_row('ضريبة قابلة للاسترداد · Reclaimable VAT', f"{s['vat_approved']:,.0f}")}</table>
{f'<p style="margin:16px 0 6px;font-weight:bold">أعلى الموردين إنفاقاً · Top suppliers</p><table style="width:100%;border-collapse:collapse">{top}</table>' if top else ''}
<p style="margin-top:16px"><a href="{settings.app_url}" style="color:{BLUE}">افتح التطبيق · Open the app</a></p>"""
    return "ملخص الفواتير الأسبوعي · Weekly invoice digest", \
        _frame(f"ملخص الأسبوع: {s['week_count']} فاتورة", f"This week: SAR {s['week_spend']:,.0f}", inner)


RESULT_TEXT = {
    "approved": ("تم اعتماد الفاتورة", "Invoice approved", GREEN),
    "rejected": ("تم رفض الفاتورة", "Invoice rejected", RED),
    "not_found": ("لم نجد هذه الفاتورة", "Invoice not found", SOFT),
    "bad_action": ("رابط غير صالح", "This link is not valid", SOFT),
    "bad_token": ("الرابط مستخدم أو غير صالح", "This link was already used or is not valid", SOFT),
    "already_approved": ("الفاتورة معتمدة مسبقاً", "This invoice is already approved", SOFT),
    "already_rejected": ("الفاتورة مرفوضة مسبقاً", "This invoice is already rejected", SOFT),
    "already_review": ("الفاتورة تحتاج مراجعة", "This invoice needs review first", SOFT),
    "already_manual": ("الفاتورة تحتاج إدخال بيانات", "This invoice needs its details entered first", SOFT),
}


def result_page(code: str, subtitle: str = "") -> str:
    ar, en, color = RESULT_TEXT.get(code, ("حدث خطأ", "Something went wrong", SOFT))
    return f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{en}</title></head>
<body style="margin:0;background:#EEF2EE;font-family:Tahoma,Arial,sans-serif;color:{INK};display:grid;place-items:center;min-height:100vh;padding:16px;box-sizing:border-box">
<div style="background:{PAPER};border:1px solid {RULE};border-radius:10px;padding:28px 32px;max-width:420px;text-align:center">
<div style="display:inline-block;border:4px double {color};color:{color};border-radius:8px;padding:8px 18px;transform:rotate(-6deg);font-size:24px;font-weight:bold">{ar}</div>
<p style="margin:18px 0 4px">{en}</p><p style="margin:0;color:{SOFT};font-size:14px">{html.escape(subtitle)}</p>
<p style="margin-top:18px;font-size:13px"><a href="{settings.app_url}" style="color:{BLUE}">افتح التطبيق · Open the app</a></p></div></body></html>"""
