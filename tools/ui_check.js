// Browser check of the web app against a small mock of the FastAPI endpoints (for environments without Python deps).
// Usage: node tools/ui_check.js [screenshot-folder]
const http = require("http");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");
const WEB = path.join(__dirname, "..", "web");
const OUT = process.argv[2] || "/tmp";

const checksOk = [{ k: "vatno", pass: true }, { k: "rate", pass: true, expected: 3510 }, { k: "total", pass: true, diff: 0 }, { k: "fields", pass: true }, { k: "dup", pass: true }, { k: "cur", pass: true }];
const inv = (id, ar, en, no, sub, vat, total, status, extra) => Object.assign({ id, status, received_at: "2026-11-12 23:0" + id.slice(-1), source: "email", sender: "billing@x.sa", file_name: no.toLowerCase() + ".pdf", extracted_by: "gemini", note: "",
  supplier: { ar, en }, vat_no: "300512398700003", number: no, date: "2026-11-12", currency: "SAR", subtotal: sub, vat, total, lines: [{ description: "Services", quantity: 1, unit_price: sub, amount: sub }], checks: checksOk, reason: "", decided_at: "", decided_by: "" }, extra || {});
let invoices = [
  inv("FC-1", "شركة سحاب للحلول التقنية", "Sahab Tech Solutions", "INV-2701", 23400, 3510, 26910, "approved"),
  inv("FC-2", "مؤسسة الندى للقرطاسية", "Al Nada Stationery", "ND-5602", 2980, 447, 3427, "pending"),
  inv("FC-3", "مطابع الواحة", "Al Waha Printing", "WP-3401", 4800, 672, 5472, "review", { checks: checksOk.map((c) => (c.k === "rate" ? { k: "rate", pass: false, expected: 720 } : c)) }),
];
let role = "manager";

const server = http.createServer((req, res) => {
  const json = (code, body) => { res.writeHead(code, { "Content-Type": "application/json" }); res.end(JSON.stringify(body)); };
  const file = (p, type) => { res.writeHead(200, { "Content-Type": type }); res.end(fs.readFileSync(path.join(WEB, p))); };
  const url = req.url.split("?")[0];
  if (url === "/") return file("index.html", "text/html; charset=utf-8");
  if (url === "/login") return file("login.html", "text/html; charset=utf-8");
  if (url.startsWith("/static/")) return file(url.slice(8), url.endsWith(".css") ? "text/css" : "application/javascript");
  if (url === "/api/me") return json(200, { user: { id: 1, name: role === "manager" ? "Maha" : "Sara", email: "m@x.sa", role }, company: "Al Riyada Trading Co.", inbox: "ap@riyada.sa", email_enabled: true, ai: ["gemini", "mistral"] });
  if (url === "/api/invoices") return json(200, { invoices });
  let body = []; req.on("data", (d) => body.push(d)); req.on("end", () => {
    body = Buffer.concat(body);
    if (url === "/api/invoices/upload") { const n = inv("FC-4", "", "", "", 0, 0, 0, "manual", { checks: [], lines: [], number: "", file_name: "scan.pdf", extracted_by: "manual", note: "gemini: HTTP 429" }); invoices.push(n); return json(200, { ok: true, invoice: n }); }
    if (url === "/api/ask") { const q = JSON.parse(body.toString()).question; return q.includes("busy") ? json(503, { ok: false, code: "ai_busy" }) : json(200, { ok: true, answer: "AI: " + q, by: "gemini" }); }
    const r = url.match(/^\/api\/invoices\/(.+)\/retry$/);
    if (r) { const x = invoices.find((i) => i.id === r[1]); Object.assign(x, { supplier: { ar: "شركة رواسي", en: "Rawasi" }, number: "RW-1004", date: "2026-11-11", subtotal: 18200, vat: 2730, total: 20930, status: "pending", checks: checksOk, extracted_by: "gemini", note: "" }); return json(200, { ok: true, invoice: x }); }
    const m = url.match(/^\/api\/invoices\/(.+)\/(decide|details)$/);
    if (m) {
      const x = invoices.find((i) => i.id === m[1]); const b = JSON.parse(body.toString());
      if (m[2] === "decide") { if (role !== "manager") return json(403, { detail: "Only managers" }); x.status = b.action === "approve" ? "approved" : "rejected"; return json(200, { ok: true, invoice: x }); }
      Object.assign(x, { supplier: { ar: b.supplier_name_ar, en: b.supplier_name_en }, number: b.invoice_number, date: b.invoice_date, subtotal: b.subtotal, vat: b.vat_amount, total: b.total, status: "pending", checks: checksOk, extracted_by: "manual" });
      return json(200, { ok: true, invoice: x });
    }
    json(404, { ok: false });
  });
}).listen(0, async () => {
  const base = `http://127.0.0.1:${server.address().port}`;
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1360, height: 900 } });
  const errs = []; p.on("pageerror", (e) => errs.push(e.message));
  let fails = 0; const ok = (c, m) => { console.log(c ? "PASS" : "FAIL", m); if (!c) fails++; };

  await p.goto(base + "/"); await p.waitForTimeout(500);
  ok((await p.$$("#ledger tr.row")).length === 3, "ledger loads 3 invoices from the API");
  ok((await p.textContent("#t-mode")).includes("Gemini"), "header shows the AI chain");
  ok((await p.textContent("#t-user")).includes("Maha"), "signed-in user shown");
  await p.click('[data-approve="FC-2"]'); await p.waitForTimeout(200);
  ok(invoices[1].status === "approved", "manager approves from the desk");

  await p.setInputFiles("#file-in", { name: "scan.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF fake") });
  await p.waitForTimeout(500);
  ok(!(await p.$eval("#viewer", (e) => e.hidden)) && !!(await p.$("#details-form")), "manual-entry invoice opens with the entry form");
  ok(!!(await p.$("[data-retry]")) && (await p.textContent("#vbody")).includes("429"), "AI failure reason and retry button are shown");
  await p.click("[data-retry]"); await p.waitForTimeout(300);
  ok(invoices[3].status === "pending" && invoices[3].number === "RW-1004", "retry reads the invoice and checks it");
  await p.screenshot({ path: path.join(OUT, "ui-viewer.png") });
  await p.click("#v-close");
  const visible = async () => p.$$eval("[data-in]", (els) => els.filter((e) => !e.hidden).map((e) => e.id).join(","));
  ok(p.url().endsWith("#invoices") && (await visible()) === "sec-ledger", "upload switches to the Invoices page");
  await p.click('#nav a[data-view="spend"]'); await p.waitForTimeout(100);
  ok((await visible()) === "sec-spend" && (await p.textContent("#t-page")) === "الإنفاق", "Spend page shows only spend");
  await p.click('#nav a[data-view="intake"]'); await p.waitForTimeout(100);
  ok((await visible()) === "sec-intake", "Invoice intake page");
  await p.click('#nav a[data-view="approvals"]'); await p.waitForTimeout(100);
  ok((await visible()) === "sec-desk", "Approvals page");
  await p.click('#nav a[data-view="overview"]'); await p.waitForTimeout(100);
  ok((await visible()) === "sec-overview,pipe,sec-desk,sec-spend", "Overview shows banner, pipeline, approvals and spend");
  await p.screenshot({ path: path.join(OUT, "ui-main.png") });

  await p.click("#open-agent"); await p.fill("#ask-input", "how many invoices received?"); await p.press("#ask-input", "Enter"); await p.waitForTimeout(300);
  let last = await p.$$eval("#msgs .msg.bot", (e) => e[e.length - 1].textContent);
  ok(last.includes("AI: how many invoices received?") && last.includes("Gemini"), "Ask finance sends the question to the AI and labels the answer");
  await p.fill("#ask-input", "busy: how many invoices received?"); await p.press("#ask-input", "Enter"); await p.waitForTimeout(300);
  last = await p.$$eval("#msgs .msg.bot", (e) => e[e.length - 1].textContent);
  ok(/You have 4 invoices|عندك 4/.test(last), "when the AI is busy the built-in engine answers from the ledger: " + last.slice(0, 60));
  await p.screenshot({ path: path.join(OUT, "ui-ask.png") });
  await p.click("#close-agent");

  role = "clerk";
  const c = await b.newPage({ viewport: { width: 1360, height: 900 } }); await c.goto(base + "/"); await c.waitForTimeout(400);
  ok((await c.$$("[data-approve]")).length === 0, "clerk sees no approve buttons");
  const m = await b.newPage({ viewport: { width: 400, height: 860 } }); await m.goto(base + "/login"); await m.waitForTimeout(300);
  ok((await m.evaluate(() => document.documentElement.scrollWidth)) <= 400, "login page fits a phone");
  await m.screenshot({ path: path.join(OUT, "ui-login-phone.png") });
  ok(errs.length === 0, "no page errors " + errs.join(" | "));
  await b.close(); server.close();
  console.log(fails ? `${fails} FAILED` : "ALL PASS"); process.exit(fails ? 1 : 0);
});
