/* Bank reconciliation engine for the browser (GitHub Pages demo).
   A line-by-line port of app/reconcile.py: tests/test_reconcile.py checks that both give identical results.
   FC_RECON_ENGINE.reconcile(bankRows, bookRows, previous, bankClosing, bookClosing) → result */
(function () {
"use strict";

const DATE_WINDOW = [-3, 7];
const STALE_DAYS = 180;
const CHARGE_WORDS = ["charge", "fee", "commission", "رسوم", "عموله", "عمولة"];
const INTEREST_WORDS = ["interest", "profit", "فائده", "فائدة", "ارباح", "أرباح", "عائد"];
const CHEQUE_RE = /(?:chq|cheque|check|شيك)\s*(?:no\.?|number|#|رقم)?\s*[:#]?\s*0*(\d{3,})/i;
const HEADERS = {
  date: ["date", "transaction date", "posting date", "txn date", "التاريخ", "تاريخ العمليه", "تاريخ العملية", "value date", "تاريخ القيمه"],
  description: ["description", "details", "narrative", "particulars", "payee", "memo", "البيان", "الوصف", "التفاصيل"],
  ref: ["cheque no", "cheque number", "chq no", "check no", "cheque", "reference", "ref", "ref no", "رقم الشيك", "المرجع", "رقم المرجع"],
  amount: ["amount", "المبلغ"],
  balance: ["balance", "running balance", "الرصيد"],
  in: ["deposit", "deposits", "money in", "paid in", "receipt", "receipts", "ايداع", "إيداع"],
  out: ["withdrawal", "withdrawals", "money out", "paid out", "payment", "payments", "سحب"],
  debit: ["debit", "dr", "مدين"],
  credit: ["credit", "cr", "دائن"],
};

class ReconcileError extends Error { constructor(code, detail) { super(detail || code); this.code = code; } }

/* ---------- reading files ---------- */
function readCsv(text) {
  const rows = []; let row = [], cell = "", q = false;
  text = text.replace(/^﻿/, "");
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else q = false; } else cell += c; }
    else if (c === '"') q = true;
    else if (c === ",") { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") { if (c === "\r" && text[i + 1] === "\n") i++; row.push(cell); rows.push(row); row = []; cell = ""; }
    else cell += c;
  }
  if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

const norm = (s) => String(s == null ? "" : s).trim().toLowerCase()
  .replace(/[أإآ]/g, "ا").replace(/ة/g, "ه").replace(/ى/g, "ي")
  .replace(/[_.:#()/\\-]+/g, " ").replace(/\s+/g, " ").trim();
const digits = (s) => s.replace(/[٠-٩]/g, (d) => "٠١٢٣٤٥٦٧٨٩".indexOf(d));
const cents = (x) => (x >= 0 ? 1 : -1) * Math.floor(Math.abs(x) * 100 + 0.5);
const blank = (v) => v === null || v === undefined || v === "";

function parseAmount(v) {
  if (blank(v)) return 0;
  if (typeof v === "number") return cents(v);
  let s = digits(String(v)).trim().replace(/٬/g, ",").replace(/٫/g, ".");
  const neg = (s.startsWith("(") && s.endsWith(")")) || s.endsWith("-") || s.startsWith("-");
  s = s.replace(/,/g, "").replace(/[^0-9.]/g, "");
  if (!s || s === ".") return 0;
  const n = cents(parseFloat(s));
  return neg ? -n : n;
}

const iso = (y, mo, d) => { const t = new Date(Date.UTC(y, mo - 1, d)); return t.getUTCFullYear() === y && t.getUTCMonth() === mo - 1 && t.getUTCDate() === d ? t.toISOString().slice(0, 10) : null; };
function parseDate(v) {
  const s = digits(String(v == null ? "" : v)).trim();
  let m = s.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/), y, mo, d;
  if (m) { y = +m[1]; mo = +m[2]; d = +m[3]; }
  else {
    m = s.match(/^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})/);
    if (m) { d = +m[1]; mo = +m[2]; y = +m[3]; }
    else {
      m = s.toLowerCase().match(/^(\d{1,2})[ -]([a-z]{3})[a-z]*[ -](\d{2,4})/);
      const months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
      if (!m || !months.includes(m[2])) return null;
      d = +m[1]; mo = months.indexOf(m[2]) + 1; y = +m[3];
    }
    if (y < 100) y += 2000;
  }
  return iso(y, mo, d);
}

function cleanRef(ref, description) {
  let s = digits(String(ref == null ? "" : ref)).trim();
  s = s.replace(/^(chq|cheque|check|ref|شيك)\s*(no\.?|#|رقم)?/i, "");
  s = s.replace(/[^0-9A-Za-z]/g, "").replace(/^0+/, "").toUpperCase();
  if (!s) { const m = digits(description || "").match(CHEQUE_RE); s = m ? m[1].replace(/^0+/, "") : ""; }
  return s;
}

function findColumns(header) {
  const cells = header.map(norm), found = {};
  for (const [key, names] of Object.entries(HEADERS)) {
    for (const name of names) {
      const i = cells.indexOf(norm(name));
      if (i >= 0 && !Object.values(found).includes(i)) { found[key] = i; break; }
    }
  }
  return found;
}

function normalize(rows, side) {
  let at = -1, cols;
  for (let i = 0; i < Math.min(rows.length, 20); i++) {
    cols = findColumns(rows[i]);
    if ("date" in cols && ("amount" in cols || ("in" in cols && "out" in cols) || ("debit" in cols && "credit" in cols))) { at = i; break; }
  }
  if (at < 0) throw new ReconcileError("no_columns", side + ": couldn't find the Date and Amount (or Debit/Credit) columns");
  const cell = (row, key) => { const i = cols[key]; return i !== undefined && i < row.length ? row[i] : null; };
  const entries = []; let closing = null;
  const prefix = side === "bank" ? "B" : "K";
  rows.slice(at + 1).forEach((row, j) => {
    const n = at + 2 + j;
    if (!row.some((c) => !blank(c))) return;
    const desc = String(cell(row, "description") == null ? "" : cell(row, "description")).trim();
    const balance = cell(row, "balance");
    if (/opening balance|balance brought|الرصيد الافتتاحي|رصيد افتتاحي/.test(norm(desc))) return;
    if (/closing balance|balance carried|الرصيد الختامي|رصيد ختامي/.test(norm(desc))) { if (!blank(balance)) closing = parseAmount(balance); return; }
    const d = parseDate(cell(row, "date"));
    if (d === null) return;
    let amount;
    if ("amount" in cols) amount = parseAmount(cell(row, "amount"));
    else if ("in" in cols) amount = parseAmount(cell(row, "in")) - parseAmount(cell(row, "out"));
    else { const dr = parseAmount(cell(row, "debit")), cr = parseAmount(cell(row, "credit")); amount = side === "bank" ? cr - dr : dr - cr; }
    if (amount === 0) return;
    if (!blank(balance)) closing = parseAmount(balance);
    entries.push({ id: prefix + n, row: n, date: d, description: desc, ref: cleanRef(cell(row, "ref"), desc), amount });
  });
  return [entries, closing];
}

/* ---------- matching ---------- */
const days = (a, b) => Math.round((Date.parse(a) - Date.parse(b)) / 864e5);

function match(bank, book) {
  const pairs = [], usedB = new Set(), usedK = new Set();
  const take = (b, k, how) => { usedB.add(b.id); usedK.add(k.id); pairs.push({ bank: b, book: k, how, days: days(b.date, k.date) }); };
  const free = (side, used) => side.filter((e) => !used.has(e.id));
  for (const k of book) {
    if (!k.ref) continue;
    const b = free(bank, usedB).find((b) => b.ref === k.ref && b.amount === k.amount);
    if (b) take(b, k, "cheque");
  }
  for (const k of free(book, usedK)) {
    const b = free(bank, usedB).find((b) => b.amount === k.amount && b.date === k.date);
    if (b) take(b, k, "same_date");
  }
  for (const k of free(book, usedK)) {
    const near = free(bank, usedB).filter((b) => b.amount === k.amount && days(b.date, k.date) >= DATE_WINDOW[0] && days(b.date, k.date) <= DATE_WINDOW[1]);
    if (near.length) take(near.reduce((best, b) => (Math.abs(days(b.date, k.date)) < Math.abs(days(best.date, k.date)) ? b : best)), k, "near_date");
  }
  for (const k of free(book, usedK)) {
    const sameB = free(bank, usedB).filter((b) => b.amount === k.amount && days(b.date, k.date) >= DATE_WINDOW[0]);
    const sameK = free(book, usedK).filter((x) => x.amount === k.amount);
    if (sameB.length === 1 && sameK.length === 1) take(sameB[0], k, "unique_amount");
  }
  return pairs;
}

const hasWord = (text, words) => { const t = norm(text); return words.some((w) => t.includes(norm(w))); };
const sum = (list, f) => list.reduce((a, x) => a + f(x), 0);

function reconcile(bankRows, bookRows, previous, bankClosing, bookClosing) {
  const [bank, bankFound] = normalize(bankRows, "bank");
  const [book, bookFound] = normalize(bookRows, "book");
  if (!bank.length) throw new ReconcileError("empty", "bank: no transactions found");
  const bClose = blank(bankClosing) ? bankFound : cents(bankClosing);
  const kClose = blank(bookClosing) ? bookFound : cents(bookClosing);
  if (bClose === null || kClose === null) throw new ReconcileError("no_balance", "add the closing balance: the file has no Balance column");

  const all = bank.concat(book).map((e) => e.date).sort();
  const start = all[0], end = all[all.length - 1];
  const carried = (previous || []).map((p, i) => Object.assign({}, p, { id: "P" + (i + 1), previous: true }));
  const pairs = match(bank, carried.concat(book));
  const used = new Set(pairs.flatMap((p) => [p.bank.id, p.book.id]));
  let leftB = bank.filter((e) => !used.has(e.id));
  let leftK = carried.concat(book).filter((e) => !used.has(e.id));

  const errors = [];
  for (const k of leftK.slice()) {
    const b = leftB.find((b) => k.ref && b.ref === k.ref && (b.amount > 0) === (k.amount > 0));
    if (b) { errors.push({ bank: b, book: k, difference: b.amount - k.amount }); leftB = leftB.filter((x) => x !== b); leftK = leftK.filter((x) => x !== k); }
  }

  const duplicates = [], seen = [];
  for (const k of book) {
    const key = [k.date, k.amount, k.ref, norm(k.description)].join("\u0001");
    if (seen.includes(key) && leftK.some((x) => x.id === k.id)) { duplicates.push(k); leftK = leftK.filter((x) => x.id !== k.id); }
    seen.push(key);
  }

  const age = (e) => days(end, e.date);
  const outstanding = leftK.filter((k) => k.amount < 0).map((k) => Object.assign({}, k, { age: age(k), stale: age(k) > STALE_DAYS }));
  const inTransit = leftK.filter((k) => k.amount > 0).map((k) => Object.assign({}, k, { age: age(k) }));
  const bankKey = (b) => [b.date, b.amount, norm(b.description)].join("\u0001");
  const bankKeys = bank.map(bankKey);
  const bankOnly = leftB.map((b) => Object.assign({}, b, {
    kind: b.amount < 0 ? (hasWord(b.description, CHARGE_WORDS) ? "charges" : "direct_debit") : (hasWord(b.description, INTEREST_WORDS) ? "interest" : "direct_credit"),
    repeat: bankKeys.filter((k) => k === bankKey(b)).length > 1,
  }));

  const st = {
    bank_closing: bClose,
    outstanding_cheques: sum(outstanding, (e) => e.amount),
    deposits_in_transit: sum(inTransit, (e) => e.amount),
    book_closing: kClose,
    bank_debits: sum(bankOnly.filter((e) => e.amount < 0), (e) => e.amount),
    bank_credits: sum(bankOnly.filter((e) => e.amount > 0), (e) => e.amount),
    errors: sum(errors, (e) => e.difference),
    duplicates: -sum(duplicates, (e) => e.amount),
  };
  st.adjusted_bank = st.bank_closing + st.outstanding_cheques + st.deposits_in_transit;
  st.adjusted_book = st.book_closing + st.bank_debits + st.bank_credits + st.errors + st.duplicates;
  st.difference = st.adjusted_bank - st.adjusted_book;

  const carry = outstanding.concat(inTransit).slice().sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
    .map((e) => ({ date: e.date, description: e.description, ref: e.ref, amount: e.amount }));
  return toSar({
    period: { start, end },
    counts: { bank_rows: bank.length, book_rows: book.length, carried_in: carried.length, matched: pairs.length },
    statement: st, matched: pairs, outstanding, in_transit: inTransit, bank_only: bankOnly, errors, duplicates,
    cleared_from_previous: pairs.filter((p) => p.book.previous), carry_forward: carry,
  });
}

const MONEY = ["amount", "difference"];
const STATEMENT_KEYS = ["bank_closing", "outstanding_cheques", "deposits_in_transit", "book_closing", "bank_debits", "bank_credits", "errors", "duplicates", "adjusted_bank", "adjusted_book"];
function toSar(v) {
  if (Array.isArray(v)) return v.map(toSar);
  if (v && typeof v === "object") {
    const out = {};
    for (const [k, x] of Object.entries(v)) out[k] = typeof x === "number" && (MONEY.includes(k) || STATEMENT_KEYS.includes(k)) ? x / 100 : toSar(x);
    return out;
  }
  return v;
}
const previousFrom = (carry) => (carry || []).map((e) => ({ date: e.date, description: e.description, ref: e.ref || "", amount: cents(e.amount) }));

const API = { reconcile, readCsv, previousFrom, normalize, parseAmount, parseDate, cleanRef, ReconcileError };
if (typeof module !== "undefined" && module.exports) module.exports = API;
else window.FC_RECON_ENGINE = API;
})();
