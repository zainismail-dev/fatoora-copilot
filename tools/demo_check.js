// End-to-end check of the GitHub Pages demo (docs/), served under a sub-path like github.io/<repo>/.
// Usage: python tools/build_demo.py && node tools/demo_check.js [screenshot-folder]
const http = require("http");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");
const DOCS = path.join(__dirname, "..", "docs");
const OUT = process.argv[2] || "/tmp";
const BASE_PATH = "/fatoora-copilot/";
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css", ".pdf": "application/pdf" };

const server = http.createServer((req, res) => {
  let url = decodeURIComponent(req.url.split("?")[0]);
  if (!url.startsWith(BASE_PATH)) { res.writeHead(404); return res.end(); }
  let file = path.join(DOCS, url.slice(BASE_PATH.length) || "index.html");
  if (file.endsWith(path.sep)) file = path.join(file, "index.html");
  if (!file.startsWith(DOCS) || !fs.existsSync(file)) { res.writeHead(404); return res.end("not found"); }
  res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
}).listen(0, async () => {
  const site = `http://127.0.0.1:${server.address().port}${BASE_PATH}`;
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1360, height: 900 }, acceptDownloads: true });
  const p = await ctx.newPage();
  const errs = []; p.on("pageerror", (e) => errs.push(e.message)); p.on("requestfailed", (r) => { if (!/fonts\.g/.test(r.url())) errs.push("failed " + r.url()); });
  let fails = 0; const ok = (c, m) => { console.log(c ? "PASS" : "FAIL", m); if (!c) fails++; };
  const rows = () => p.$$eval("#ledger tr.row[data-open]", (r) => r.length);
  const visible = () => p.$$eval("[data-in]", (els) => els.filter((e) => !e.hidden).map((e) => e.id).join(","));

  await p.goto(site); await p.waitForTimeout(600);
  ok((await p.textContent("#t-mode")).includes("تجريبية"), "demo badge shown");
  ok((await p.textContent("#hero-h")).includes("1"), "overview: 1 invoice waiting (seeded)");
  ok((await p.textContent("#denom-big")) === "3,177", "reclaimable VAT from 2 approved seeded invoices");
  await p.screenshot({ path: path.join(OUT, "demo-overview-ar.png") });

  await p.click("#lang-en"); await p.waitForTimeout(150);
  await p.click('#nav a[data-view="invoices"]'); await p.waitForTimeout(150);
  ok((await rows()) === 5 && (await visible()) === "sec-ledger", "invoices page lists 5 seeded invoices");

  await p.setInputFiles("#file-in", { name: "any.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF") });
  await p.waitForTimeout(2000);
  ok((await rows()) === 6 && (await p.textContent("#ledger")).includes("Sahab Tech Solutions"), "upload 1 adds Sahab (clean)");
  await p.setInputFiles("#file-in", { name: "any.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF") });
  await p.waitForTimeout(2000);
  ok((await p.textContent("#ledger")).includes("Lamsa Decor"), "upload 2 adds Lamsa (invalid VAT number)");

  await p.fill("#ledger-search", "lamsa"); await p.waitForTimeout(100);
  ok((await rows()) === 1 && (await p.textContent("#ledger-count")).includes("1 of"), "search filters the ledger");
  await p.click("#ledger tr.row[data-open]"); await p.waitForTimeout(250);
  const body = await p.textContent("#vbody");
  ok(body.includes("VAT number is invalid") && !!(await p.$(".parties .bad")), "Lamsa: VAT number flagged in red");
  await p.screenshot({ path: path.join(OUT, "demo-viewer-en.png") });
  const href = await p.getAttribute(".filelink", "href");
  const pdf = await p.request.get(new URL(href, site).toString());
  ok(pdf.status() === 200 && (await pdf.body()).slice(0, 4).toString() === "%PDF", "original PDF opens from samples/");
  await p.click("[data-delete]"); await p.click("[data-confirm-delete]"); await p.waitForTimeout(400);
  ok(!(await p.textContent("#ledger")).includes("Lamsa"), "manager deletes a wrong invoice");
  await p.fill("#ledger-search", ""); await p.dispatchEvent("#ledger-search", "input");

  await p.click('#nav a[data-view="approvals"]'); await p.waitForTimeout(150);
  const before = await p.$$eval("[data-approve]", (b) => b.length);
  await p.click("[data-approve]"); await p.waitForTimeout(400);
  ok((await p.$$eval("[data-approve]", (b) => b.length)) === before - 1, "approve from the approvals page");

  const dl = p.waitForEvent("download", { timeout: 4000 });
  await p.click('#nav a[data-view="invoices"]'); await p.click("#export-csv");
  const file = await dl; const csv = fs.readFileSync(await file.path(), "utf8");
  ok(csv.startsWith("﻿ID,Status") && csv.includes("Sahab Tech Solutions") && csv.includes("شركة"), "CSV export with Arabic");

  await p.reload(); await p.waitForTimeout(500);
  ok((await rows()) === 6, "demo data survives a page reload");
  await p.click("#logout"); await p.waitForTimeout(500);
  ok((await p.textContent("#hero-h")).includes("1") && p.url().endsWith("#overview"), "Reset demo restores the starting data");
  await p.click('#nav a[data-view="spend"]'); await p.waitForTimeout(150);
  ok((await visible()) === "sec-spend", "spend page");
  await p.screenshot({ path: path.join(OUT, "demo-spend-en.png") });

  await p.click("#open-agent");
  const askBot = async (q) => { await p.fill("#ask-input", q); await p.press("#ask-input", "Enter"); await p.waitForTimeout(300); return p.$$eval("#msgs .msg.bot", (e) => e[e.length - 1].textContent); };
  const a1 = await askBot("hello"), a2 = await askBot("how many invoices received?"), a3 = await askBot("كم فاتورة وصلتنا؟"), a4 = await askBot("show invoice WP-3401");
  ok(new Set([a1, a2, a3, a4]).size === 4 && a2.startsWith("You have 5 invoices") && a3.startsWith("عندك 5") && a4.includes("VAT is not 15%"), "Ask finance gives a different, correct answer to each question");
  await p.screenshot({ path: path.join(OUT, "demo-ask.png") });
  await p.click("#close-agent");

  await p.click('#nav a[data-view="reconcile"]'); await p.waitForTimeout(1200);
  ok((await p.$$eval(".rc-hist", (e) => e.length)) === 1, "bank reconciliation opens with October already reconciled");
  await p.click("#rc-sample"); await p.waitForTimeout(2000);
  const diff = await p.$eval(".rc-st tr.diff td", (e) => e.textContent.trim());
  ok(diff === "0.00" && (await p.$$eval(".rc-hist", (e) => e.length)) === 2, "November sample reconciles to a 0.00 difference");
  ok((await p.$$eval('[data-sec="outstanding"] tbody tr', (e) => e.length)) === 3 && (await p.textContent('[data-sec="outstanding"]')).includes("100235"), "October's uncashed cheque is carried into November");
  await p.screenshot({ path: path.join(OUT, "demo-reconcile.png"), fullPage: true });

  const m = await b.newPage({ viewport: { width: 390, height: 844 } });
  await m.goto(site); await m.waitForTimeout(500);
  ok((await m.evaluate(() => document.documentElement.scrollWidth)) <= 390, "fits a phone screen");
  await m.screenshot({ path: path.join(OUT, "demo-phone-ar.png") });
  ok(errs.length === 0, "no errors or broken links " + errs.join(" | "));
  await b.close(); server.close();
  console.log(fails ? `${fails} FAILED` : "ALL PASS"); process.exit(fails ? 1 : 0);
});
