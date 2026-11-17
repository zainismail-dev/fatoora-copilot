/* Fatoora Copilot: demo mode for static hosting (GitHub Pages).
   Stands in for the FastAPI backend inside the browser: same API shape, same ZATCA pre-check rules
   (a port of app/checks.py, kept in sync by tests/test_demo_parity.py), fictional sample invoices.
   Uploaded files are not read; each upload uses the next sample invoice, as the real AI would return it. */
(function () {
"use strict";

/* ---------- pre-check rules (port of app/checks.py) ---------- */
const LARGE_AMOUNT_SAR = 50000;
const round2 = (v) => Math.round(((Number(v) || 0) + 1e-9) * 100) / 100;
const digitsOnly = (v) => String(v == null ? "" : v)
  .replace(/[٠-٩]/g, (d) => "٠١٢٣٤٥٦٧٨٩".indexOf(d)).replace(/[۰-۹]/g, (d) => "۰۱۲۳۴۵۶۷۸۹".indexOf(d)).replace(/\D/g, "");
const duplicateKey = (vatNo, supplier, invoiceNo) =>
  (digitsOnly(vatNo) || String(supplier || "").trim().toUpperCase()) + "|" + String(invoiceNo || "").trim().toUpperCase();

function runChecks(inv, earlier) {
  const checks = [];
  const vatNo = digitsOnly(inv.supplier_vat_number);
  checks.push({ k: "vatno", pass: /^3\d{13}3$/.test(vatNo) });
  const sub = round2(inv.subtotal), vat = round2(inv.vat_amount), total = round2(inv.total);
  const expected = round2(sub * 0.15);
  checks.push({ k: "rate", pass: Math.abs(vat - expected) <= 1, expected });
  const diff = round2(total - sub - vat);
  checks.push({ k: "total", pass: Math.abs(diff) < 0.05, diff });
  const name = String(inv.supplier_name_ar || "").trim() || String(inv.supplier_name_en || "").trim();
  checks.push({ k: "fields", pass: inv.is_invoice !== false && !!name && !!String(inv.invoice_number || "").trim() && !!String(inv.invoice_date || "").trim() && total > 0 });
  const dupDate = earlier[duplicateKey(vatNo, inv.supplier_name_en || name, inv.invoice_number)];
  checks.push(dupDate === undefined ? { k: "dup", pass: true } : { k: "dup", pass: false, dupDate });
  const currency = (String(inv.currency || "SAR").trim().toUpperCase() || "SAR");
  checks.push({ k: "cur", pass: currency === "SAR" });
  if (currency === "SAR" && total > LARGE_AMOUNT_SAR) checks.push({ k: "large", pass: true, note: true });
  return { checks, status: checks.some((c) => !c.pass) ? "review" : "pending", vatNo, sub, vat, total, currency };
}

/* ---------- sample invoices: the fields the AI returns for each file in samples/ ---------- */
const sample = (file, ar, en, vat, no, date, lines, opts) => {
  const o = opts || {}, rate = o.rate === undefined ? 0.15 : o.rate;
  const sub = round2(lines.reduce((a, l) => a + l[2] * l[3], 0)), v = round2(sub * rate);
  return { file, fields: { is_invoice: true, supplier_name_ar: ar, supplier_name_en: en, supplier_vat_number: vat, invoice_number: no,
    invoice_date: date, currency: o.cur || "SAR", subtotal: sub, vat_amount: v, total: round2(sub + v + (o.add || 0)),
    lines: lines.map((l) => ({ description: `${l[0]} ${l[1]}`, quantity: l[2], unit_price: l[3], amount: round2(l[2] * l[3]) })) } };
};
const SAMPLES = {
  sahab: sample("01-sahab-clean.pdf", "شركة سحاب للحلول التقنية", "Sahab Tech Solutions", "300512398700003", "INV-2701", "2026-11-12",
    [["رخص برمجيات سنوية", "Annual software licences", 10, 1800], ["خدمات دعم فني", "Technical support", 12, 450]]),
  nada: sample("02-nada-clean.pdf", "مؤسسة الندى للقرطاسية", "Al Nada Stationery", "310228745600003", "ND-5602", "2026-11-12",
    [["ورق طباعة A4", "A4 printing paper", 40, 28], ["أحبار طابعات", "Printer toner", 6, 310]]),
  rawasi: sample("03-rawasi-clean.pdf", "شركة رواسي للخدمات اللوجستية", "Rawasi Logistics", "300987654300003", "RW-1004", "2026-11-11",
    [["شحن بضائع الرياض–جدة", "Freight, Riyadh to Jeddah", 4, 3200], ["تخزين شهري", "Monthly warehousing", 1, 5400]]),
  madar: sample("04-madar-large-amount.pdf", "شركة المدار للصيانة", "Al Madar Maintenance", "300765432100003", "MD-1201", "2026-11-12",
    [["عقد صيانة سنوي للتكييف", "Annual AC maintenance contract", 1, 48000], ["قطع غيار", "Spare parts", 1, 10500]]),
  waha: sample("05-waha-wrong-vat-rate.pdf", "مطابع الواحة", "Al Waha Printing", "302345678900003", "WP-3401", "2026-11-11",
    [["طباعة كتيبات", "Brochure printing", 500, 6.4], ["بطاقات عمل", "Business cards", 10, 160]], { rate: 0.14 }),
  lamsa: sample("06-lamsa-invalid-vat-number.pdf", "مؤسسة لمسة للديكور", "Lamsa Decor", "31045678901234", "LD-0051", "2026-11-10",
    [["أعمال ديكور داخلي", "Interior fit-out", 1, 7200], ["أثاث مكتبي", "Office furniture", 4, 650]]),
  ufuq: sample("07-ufuq-total-mismatch.pdf", "شركة أفق للاتصالات", "Ufuq Telecom", "310987123400003", "UF-78010", "2026-11-12",
    [["باقة إنترنت أعمال", "Business internet plan", 1, 4200], ["خطوط جوال الموظفين", "Staff mobile lines", 25, 115]], { add: 100 }),
  cloud: sample("08-cloudline-foreign-currency.pdf", "كلاود لاين للبرمجيات", "Cloudline Software", "300111222300003", "CL-1210", "2026-11-12",
    [["استضافة سحابية", "Cloud hosting", 1, 950], ["خطة دعم", "Support plan", 1, 250]], { rate: 0, cur: "USD" }),
};
const SEED = [ // already in the ledger when the demo opens
  ["nada", "2026-11-12 09:14", "approved"], ["rawasi", "2026-11-12 09:40", "approved"], ["waha", "2026-11-12 10:05"],
  ["madar", "2026-11-12 11:22"], ["ufuq", "2026-11-12 12:48"],
];
const UPLOAD_ORDER = ["sahab", "lamsa", "cloud", "sahab"]; // the last one shows duplicate detection
const USER = { id: 1, name: "Demo Manager", email: "manager@riyada-demo.sa", role: "manager" };
const STORE = "fc-demo-v1";

/* ---------- ledger ---------- */
let db = null;
const nowRiyadh = () => {
  const p = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Riyadh", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date());
  const g = (t) => (p.find((x) => x.type === t) || {}).value;
  return `${g("year")}-${g("month")}-${g("day")} ${g("hour")}:${g("minute")}`;
};
const earlierMap = (excludeId) => {
  const m = {};
  db.invoices.forEach((x) => { if (x.id !== excludeId && x.status !== "manual" && x.number) m[duplicateKey(x.vat_no, x.supplier.en || x.supplier.ar, x.number)] = x.date; });
  return m;
};
function applyFields(x, f) {
  const r = runChecks(f, earlierMap(x.id));
  Object.assign(x, { supplier: { ar: f.supplier_name_ar || "", en: f.supplier_name_en || "" }, vat_no: r.vatNo || String(f.supplier_vat_number || ""),
    number: f.invoice_number || "", date: f.invoice_date || "", currency: r.currency, subtotal: r.sub, vat: r.vat, total: r.total,
    lines: f.lines || [], checks: r.checks, status: r.status });
  return x;
}
function ingest(key, receivedAt) {
  const s = SAMPLES[key];
  const x = { id: `FC-DEMO-${String(db.seq++).padStart(3, "0")}`, received_at: receivedAt || nowRiyadh(), source: "upload", sender: USER.email,
    file_name: s.file, extracted_by: "gemini", note: "", reason: "", decided_at: "", decided_by: "", sample: key };
  applyFields(x, s.fields);
  db.invoices.push(x);
  return x;
}
function seed() {
  db = { seq: 1, next: 0, invoices: [], recons: [], reconSeeded: false };
  SEED.forEach(([key, at, decided]) => {
    const x = ingest(key, at);
    if (decided) Object.assign(x, { status: decided, decided_at: at.replace(/\d\d:\d\d$/, "14:30"), decided_by: USER.email });
  });
  save();
}
function save() { try { localStorage.setItem(STORE, JSON.stringify(db)); } catch (e) { /* storage unavailable: keep in memory */ } }
function load() {
  try { const raw = localStorage.getItem(STORE); if (raw) { db = JSON.parse(raw); if (db && Array.isArray(db.invoices)) { db.recons = db.recons || []; return; } } } catch (e) { /* ignore */ }
  seed();
}
const publicInv = (x) => { const c = Object.assign({}, x); delete c.sample; return c; };
const normalize = (d) => {
  const num = (v) => { const n = parseFloat(String(v == null ? "" : v).replace(/,/g, "")); return Number.isFinite(n) ? n : 0; };
  return { is_invoice: true, supplier_name_ar: String(d.supplier_name_ar || "").trim(), supplier_name_en: String(d.supplier_name_en || "").trim(),
    supplier_vat_number: String(d.supplier_vat_number || "").trim(), invoice_number: String(d.invoice_number || "").trim(),
    invoice_date: String(d.invoice_date || "").trim().slice(0, 10), currency: (String(d.currency || "SAR").trim().toUpperCase() || "SAR").slice(0, 3),
    subtotal: num(d.subtotal), vat_amount: num(d.vat_amount), total: num(d.total) };
};

/* ---------- fake HTTP layer with the same routes as app/main.py ---------- */
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const reply = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const fail = (code, message, status) => reply(status || (code === "not_found" ? 404 : 400), { ok: false, code, message: message || code });

async function fetchDemo(path, options) {
  if (!db) load();
  const method = String((options && options.method) || "GET").toUpperCase();
  const url = String(path).split("?")[0];
  await sleep(method === "GET" ? 40 : 220);
  if (url === "/api/me") return reply(200, { user: USER, company: "Al Riyada Trading Co. (demo)", inbox: "invoices@riyada-demo.sa", email_enabled: true, ai: ["gemini"], demo: true });
  if (url === "/api/invoices" && method === "GET") return reply(200, { invoices: db.invoices.map(publicInv) });
  if (url === "/api/invoices/upload" && method === "POST") {
    if (db.next >= UPLOAD_ORDER.length) return fail("no_more_samples", "All sample invoices have been uploaded. Use Reset demo to start again.");
    await sleep(1300); // the AI reading step
    const x = ingest(UPLOAD_ORDER[db.next++]); save();
    return reply(200, { ok: true, invoice: publicInv(x) });
  }
  if (url.startsWith("/api/reconciliations")) return reconRoutes(url, method, options);
  const m = url.match(/^\/api\/invoices\/([^/]+)(?:\/(details|decide|retry))?$/);
  if (!m) return fail("not_found");
  const x = db.invoices.find((i) => i.id === decodeURIComponent(m[1]));
  if (!x) return fail("not_found");
  const body = options && typeof options.body === "string" ? JSON.parse(options.body) : {};
  if (!m[2] && method === "DELETE") {
    if (x.status === "approved") return fail("locked");
    db.invoices = db.invoices.filter((i) => i !== x); save();
    return reply(200, { ok: true });
  }
  if (m[2] === "decide") {
    if (!["approve", "reject"].includes(body.action)) return fail("bad_action");
    if (x.status !== "pending") return fail("already_" + x.status);
    Object.assign(x, { status: body.action === "approve" ? "approved" : "rejected", reason: String(body.reason || "").slice(0, 300), decided_at: nowRiyadh(), decided_by: USER.email });
    save(); return reply(200, { ok: true, invoice: publicInv(x) });
  }
  if (m[2] === "details") {
    if (!["manual", "review"].includes(x.status)) return fail("locked");
    const f = normalize(body);
    if (!((f.supplier_name_ar || f.supplier_name_en) && f.invoice_number && f.invoice_date && f.total > 0)) return fail("incomplete");
    f.lines = x.lines;
    applyFields(x, f); Object.assign(x, { extracted_by: "manual", note: `Edited by ${USER.name} at ${nowRiyadh()}` });
    save(); return reply(200, { ok: true, invoice: publicInv(x) });
  }
  if (m[2] === "retry") {
    if (!["manual", "review"].includes(x.status) || !x.sample) return fail("locked");
    applyFields(x, SAMPLES[x.sample].fields); Object.assign(x, { extracted_by: "gemini", note: "" });
    save(); return reply(200, { ok: true, invoice: publicInv(x) });
  }
  return fail("not_found");
}

/* ---------- bank reconciliation (same routes as app/main.py; the engine is web/reconcile.js) ---------- */
const engine = () => (typeof window !== "undefined" && window.FC_RECON_ENGINE) || require("./reconcile.js");
const SUMMARY_KEYS = ["id", "created_at", "created_by", "period_start", "period_end", "bank_file", "book_file", "bank_closing", "book_closing", "difference"];
const summary = (r) => Object.fromEntries(SUMMARY_KEYS.map((k) => [k, r[k]]));
const previousFor = (start) => db.recons.filter((r) => r.period_end < start).sort((a, b) => (a.period_end < b.period_end ? 1 : -1))[0] || null;

function saveRun(result, bankFile, bookFile, prev) {
  result.previous = prev ? { id: prev.id, period_end: prev.period_end } : null;
  const month = result.period.end.slice(0, 7), st = result.statement;
  db.recons = db.recons.filter((r) => r.period_end.slice(0, 7) !== month);
  const rec = { id: `RC-${month}-${Math.random().toString(16).slice(2, 6)}`, created_at: nowRiyadh(), created_by: USER.name,
    period_start: result.period.start, period_end: result.period.end, bank_file: bankFile, book_file: bookFile,
    bank_closing: st.bank_closing, book_closing: st.book_closing, difference: st.difference, result };
  db.recons.push(rec); save(); return rec;
}
function runFrom(bankRows, bankFile, bookRows, bookFile, bankClosing, bookClosing) {
  const E = engine(), entries = E.normalize(bankRows, "bank")[0];
  if (!entries.length) throw new E.ReconcileError("empty", "bank: no transactions found");
  const prev = previousFor(entries.map((e) => e.date).sort()[0]);
  const result = E.reconcile(bankRows, bookRows, E.previousFrom(prev ? prev.result.carry_forward : []), bankClosing, bookClosing);
  return saveRun(result, bankFile, bookFile, prev);
}
async function sampleRows(name) {
  const r = await fetch("samples/bank/" + name);
  if (!r.ok) throw new Error("sample missing: " + name);
  return engine().readCsv(await r.text());
}
// the demo opens with October already reconciled, so November shows items carried forward
async function seedRecon() {
  if (db.reconSeeded) return;
  db.reconSeeded = true;
  try { runFrom(await sampleRows("bank-statement-oct-2026.csv"), "bank-statement-oct-2026.csv", await sampleRows("cash-book-oct-2026.csv"), "cash-book-oct-2026.csv"); }
  catch (e) { /* offline or files missing: start empty */ }
  save();
}
async function reconRoutes(url, method, options) {
  await seedRecon();
  if (url === "/api/reconciliations" && method === "GET") return reply(200, { reconciliations: db.recons.map(summary).sort((a, b) => (a.period_end < b.period_end ? 1 : -1)) });
  if (url === "/api/reconciliations" && method === "POST") {
    const form = options.body, bank = form.get("bank"), book = form.get("book");
    if (!bank || !book || !bank.size || !book.size) return fail("need_files");
    if (![bank.name, book.name].every((n) => /\.(csv|txt)$/i.test(n))) return fail("demo_csv");
    const bal = (v) => (v && String(v).trim() ? engine().parseAmount(v) / 100 : null);
    try {
      await sleep(500);
      const rec = runFrom(engine().readCsv(await bank.text()), bank.name, engine().readCsv(await book.text()), book.name, bal(form.get("bank_closing")), bal(form.get("book_closing")));
      return reply(200, { ok: true, reconciliation: rec });
    } catch (e) { return fail(e.code || "bad_file", e.message); }
  }
  const m = url.match(/^\/api\/reconciliations\/([^/]+)$/);
  const rec = m && db.recons.find((r) => r.id === decodeURIComponent(m[1]));
  if (!rec) return fail("not_found");
  if (method === "DELETE") { db.recons = db.recons.filter((r) => r !== rec); save(); return reply(200, { ok: true }); }
  return reply(200, { reconciliation: rec });
}
async function sampleFiles() {
  const file = async (n) => new File([await (await fetch("samples/bank/" + n)).blob()], n, { type: "text/csv" });
  return [await file("bank-statement-nov-2026.csv"), await file("cash-book-nov-2026.csv")];
}

/* ---------- CSV export (same columns as app/services.py) ---------- */
function downloadCsv(invoices) {
  const cols = ["ID", "Status", "Supplier (AR)", "Supplier (EN)", "Supplier VAT No", "Invoice No", "Invoice Date", "Currency", "Subtotal", "VAT", "Total",
    "Failed checks", "Received At", "Source", "Read by", "Decided At", "Decided By", "Reason"];
  const cell = (v) => { const s = String(v == null ? "" : v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const rows = invoices.filter((x) => !x.checking).map((x) => [x.id, x.status, x.supplier.ar, x.supplier.en, x.vat_no, x.number, x.date, x.currency,
    x.subtotal.toFixed(2), x.vat.toFixed(2), x.total.toFixed(2), (x.checks || []).filter((c) => !c.pass).map((c) => c.k).join(" "),
    x.received_at, x.source, x.extracted_by, x.decided_at, x.decided_by, x.reason]);
  const text = "\ufeff" + [cols].concat(rows).map((r) => r.map(cell).join(",")).join("\r\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  a.download = "fatoora-ledger-demo.csv";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

const FC_DEMO = {
  fetch: fetchDemo,
  downloadCsv,
  reset() { try { localStorage.removeItem(STORE); } catch (e) { /* ignore */ } seed(); },
  fileUrl: (x) => "samples/" + encodeURIComponent(x.file_name),
  sampleFiles,
  remaining: () => { if (!db) load(); return UPLOAD_ORDER.length - db.next; },
  // exposed for tests
  _runChecks: runChecks, _samples: SAMPLES, _duplicateKey: duplicateKey,
};
if (typeof module !== "undefined" && module.exports) module.exports = FC_DEMO;
else window.FC_DEMO = FC_DEMO;
})();
