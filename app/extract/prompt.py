"""The instructions and JSON shape every AI provider is asked to return."""

PROMPT = """You read supplier tax invoices from Saudi Arabia, written in Arabic, English or both.
Extract exactly what is printed. Do not correct, recalculate or guess values.
- The SUPPLIER is the seller who issued the invoice, not the buyer.
- supplier_name_ar / supplier_name_en: the seller's name in each language if printed, else empty string.
- supplier_vat_number: the seller's VAT / tax registration number, digits only, exactly as printed (do not add or remove digits).
- invoice_date: YYYY-MM-DD. If only a Hijri date is printed, convert it to Gregorian.
- currency: ISO code (SAR, USD...). Use SAR if the invoice says ريال or SR.
- subtotal, vat_amount, total: the printed amounts as numbers with Western digits.
- lines: each line item as printed.
- is_invoice: false if the document is not an invoice.
Use empty strings or 0 for anything not printed. Reply with JSON only."""

FIELDS = ["is_invoice", "supplier_name_ar", "supplier_name_en", "supplier_vat_number", "invoice_number",
          "invoice_date", "currency", "subtotal", "vat_amount", "total", "lines"]

GEMINI_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "is_invoice": {"type": "BOOLEAN"},
        "supplier_name_ar": {"type": "STRING"},
        "supplier_name_en": {"type": "STRING"},
        "supplier_vat_number": {"type": "STRING"},
        "invoice_number": {"type": "STRING"},
        "invoice_date": {"type": "STRING"},
        "currency": {"type": "STRING"},
        "subtotal": {"type": "NUMBER"},
        "vat_amount": {"type": "NUMBER"},
        "total": {"type": "NUMBER"},
        "lines": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "description": {"type": "STRING"}, "quantity": {"type": "NUMBER"},
            "unit_price": {"type": "NUMBER"}, "amount": {"type": "NUMBER"}}}},
    },
    "required": FIELDS,
}

JSON_SHAPE_HINT = (
    '{"is_invoice": true, "supplier_name_ar": "", "supplier_name_en": "", "supplier_vat_number": "", '
    '"invoice_number": "", "invoice_date": "YYYY-MM-DD", "currency": "SAR", "subtotal": 0, "vat_amount": 0, '
    '"total": 0, "lines": [{"description": "", "quantity": 0, "unit_price": 0, "amount": 0}]}'
)


def normalize(data: dict) -> dict:
    """Make sure every field exists with the right type, whatever the provider returned."""
    def num(v):
        try:
            return float(str(v).replace(",", "")) if v not in (None, "") else 0.0
        except ValueError:
            return 0.0

    out = {
        "is_invoice": data.get("is_invoice") is not False,
        "supplier_name_ar": str(data.get("supplier_name_ar") or "").strip(),
        "supplier_name_en": str(data.get("supplier_name_en") or "").strip(),
        "supplier_vat_number": str(data.get("supplier_vat_number") or "").strip(),
        "invoice_number": str(data.get("invoice_number") or "").strip(),
        "invoice_date": str(data.get("invoice_date") or "").strip()[:10],
        "currency": (str(data.get("currency") or "SAR").strip().upper() or "SAR")[:3],
        "subtotal": num(data.get("subtotal")),
        "vat_amount": num(data.get("vat_amount")),
        "total": num(data.get("total")),
        "lines": [],
    }
    for line in data.get("lines") or []:
        if isinstance(line, dict):
            out["lines"].append({"description": str(line.get("description") or "").strip(),
                                 "quantity": num(line.get("quantity")) or 1,
                                 "unit_price": num(line.get("unit_price")),
                                 "amount": num(line.get("amount"))})
    return out
