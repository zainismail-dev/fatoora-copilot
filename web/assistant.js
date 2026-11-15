/* Ask finance: built-in answers computed from the ledger, in Arabic and English.
   Used in the GitHub Pages demo, and in the full app whenever no AI model is available.
   answer(question, invoices, lang) → string */
(function () {
"use strict";

/* ---------- text matching ---------- */
const norm = (s) => String(s || "").toLowerCase()
  .replace(/[ً-ْـ]/g, "")                // Arabic diacritics and tatweel
  .replace(/[أإآ]/g, "ا").replace(/ى/g, "ي").replace(/ة/g, "ه").replace(/ؤ/g, "و").replace(/ئ/g, "ي")
  .replace(/[٠-٩]/g, (d) => "٠١٢٣٤٥٦٧٨٩".indexOf(d))
  .replace(/[؟?!.,،:;()"'«»]/g, " ").replace(/\s+/g, " ").trim();
const has = (q, words) => words.some((w) => q.includes(norm(w)));
const isArabic = (s) => /[؀-ۿ]/.test(s);

const W = {
  greet: ["hello", "hi", "hey", "salam", "good morning", "good evening", "السلام", "مرحبا", "هلا", "اهلا", "صباح", "مساء", "hala"],
  thanks: ["thank", "thanks", "شكرا", "يعطيك العافيه", "مشكور"],
  help: ["help", "what can you", "what do you", "how to use", "مساعده", "وش تقدر", "ماذا تستطيع", "ايش تقدر", "كيف استخدم"],
  count: ["how many", "count", "number of", "total invoices", "كم فاتوره", "كم عدد", "عدد", "كم وصل"],
  received: ["received", "came", "arrived", "all invoices", "وصلت", "وصلنا", "استلمنا", "المستلمه", "كل الفواتير"],
  pending: ["waiting", "pending", "approval", "to approve", "need approv", "بانتظار", "معلق", "تحتاج اعتماد", "للاعتماد"],
  review: ["review", "flag", "problem", "issue", "error", "wrong", "stopped", "failed", "مراجعه", "مشكله", "خطا", "موقوف", "اوقف", "غلط"],
  manual: ["manual", "entry", "not read", "couldn't read", "ادخال", "يدوي", "ما انقرت"],
  approved: ["approved", "معتمده", "اعتمدت", "المعتمده"],
  rejected: ["rejected", "مرفوض", "رفضت", "المرفوضه"],
  vat: ["vat", "tax", "reclaim", "input tax", "ضريب", "استرداد", "القيمه المضافه"],
  spend: ["spend", "spent", "cost", "paid", "pay", "expense", "how much", "total amount", "صرف", "انفاق", "مصروف", "اجمالي", "كم دفعنا", "قيمه الفواتير"],
  top: ["top supplier", "biggest supplier", "largest supplier", "most", "main supplier", "اكبر مورد", "اعلى مورد", "اكثر مورد", "اكثر"],
  largest: ["largest invoice", "biggest invoice", "highest invoice", "largest amount", "most expensive", "اكبر فاتوره", "اعلى فاتوره", "اغلى"],
  dup: ["duplicate", "twice", "double", "repeated", "مكرر", "تكرار", "مرتين"],
  foreign: ["usd", "dollar", "foreign", "currency", "عمله", "دولار", "اجنبي"],
  suppliers: ["suppliers", "vendors", "supplier list", "الموردين", "موردين", "قائمه الموردين"],
  list: ["list", "show", "which", "what are", "اعرض", "وش", "ايش", "ما هي", "اي"],
};
const STOP = new Set(["شركه", "موسسه", "مطابع", "للحلول", "التقنيه", "للخدمات", "اللوجستيه", "للقرطاسيه", "للضيافه", "للصيانه",
  "للاتصالات", "للديكور", "للبرمجيات", "company", "co", "ltd", "llc", "trading", "solutions", "services", "the", "and", "est", "al"]);
const nameWords = (s) => norm(s).split(" ").filter((w) => w.length >= 3 && !STOP.has(w))
  .flatMap((w) => [w, w.replace(/^(ال|لل)/, "")]).filter((w) => w.length >= 3);

/* ---------- words for the answers ---------- */
const fw = (n) => (n === 1 || n > 10 ? "فاتورة" : "فواتير"); // Arabic plural for invoices
const money = (n) => (Number(n) || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const A = {
  en: {
    st: { pending: "waiting for approval", review: "need review", manual: "need manual entry", approved: "approved", rejected: "rejected" },
    stOne: { pending: "Waiting for approval", review: "Needs review", manual: "Needs manual entry", approved: "Approved", rejected: "Rejected" },
    chk: { vatno: "invalid VAT number", rate: "VAT is not 15%", total: "total doesn't add up", fields: "missing fields", dup: "duplicate", cur: "foreign currency" },
    greet: "Hi! Ask me about your invoices: what's waiting, what needs review, VAT to reclaim, spend by supplier, or a specific invoice number.",
    thanks: "You're welcome.",
    help: "Try:\n• How many invoices did we receive?\n• Which invoices need review?\n• How much VAT can we reclaim?\n• Who is our top supplier?\n• How much did we spend with Sahab?\n• Show invoice WP-3401",
    empty: "The ledger is empty. Upload an invoice and ask again.",
    count: (n, parts) => `You have ${n} invoice${n === 1 ? "" : "s"}: ${parts}.`,
    statusList: (n, label, total, lines) => n ? `${n} invoice${n === 1 ? "" : "s"} ${label} (SAR ${money(total)}):\n${lines}` : `No invoices ${label} right now.`,
    spend: (total, n, pend) => `Total spend: SAR ${money(total)} across ${n} invoices (rejected and unread ones excluded). SAR ${money(pend)} of it is still waiting for approval.`,
    vat: (a, p) => `VAT to reclaim on approved invoices: SAR ${money(a)}. Another SAR ${money(p)} is on invoices waiting for approval.`,
    top: (lines) => `Top suppliers by spend:\n${lines}`,
    largest: (x, nm) => `Largest invoice: ${nm}, ${x.number}, SAR ${money(x.total)} (${A.en.stOne[x.status] || x.status}).`,
    dup: (lines, n) => n ? `${n} duplicate invoice${n === 1 ? "" : "s"} caught:\n${lines}` : "No duplicates found.",
    foreign: (lines, n) => n ? `${n} invoice${n === 1 ? "" : "s"} in a foreign currency:\n${lines}` : "All invoices are in SAR.",
    suppliers: (n, lines) => `${n} supplier${n === 1 ? "" : "s"}:\n${lines}`,
    supplier: (nm, n, total, parts, lines) => `${nm}: ${n} invoice${n === 1 ? "" : "s"}, SAR ${money(total)} spent (rejected excluded). ${parts}.\n${lines}`,
    invoice: (x, nm, failed) => `${nm} · ${x.number} · ${x.date || "no date"}\nTotal ${money(x.total)} ${x.currency} (VAT ${money(x.vat)}). Status: ${A.en.stOne[x.status] || x.status}.${failed ? `\nProblems: ${failed}.` : ""}`,
    notFound: (no) => `I couldn't find invoice ${no} in the ledger.`,
    fallback: "I didn't catch that. I can answer how many invoices you have, what's waiting or needs review, VAT to reclaim, total spend, top or specific suppliers, duplicates, and details of an invoice number.",
    more: (n) => `…and ${n} more.`,
  },
  ar: {
    st: { pending: "بانتظار الاعتماد", review: "تحتاج مراجعة", manual: "تحتاج إدخال يدوي", approved: "معتمدة", rejected: "مرفوضة" },
    stOne: { pending: "بانتظار الاعتماد", review: "تحتاج مراجعة", manual: "تحتاج إدخال يدوي", approved: "معتمدة", rejected: "مرفوضة" },
    chk: { vatno: "رقم ضريبي غير صحيح", rate: "الضريبة ليست 15%", total: "الإجمالي لا يطابق", fields: "حقول ناقصة", dup: "مكررة", cur: "عملة أجنبية" },
    greet: "هلا وغلا! اسألني عن فواتيرك: وش بانتظار الاعتماد، وش يحتاج مراجعة، الضريبة القابلة للاسترداد، الإنفاق مع مورد، أو تفاصيل رقم فاتورة.",
    thanks: "العفو، بالخدمة.",
    help: "جرّب:\n• كم فاتورة وصلتنا؟\n• وش الفواتير اللي تحتاج مراجعة؟\n• كم الضريبة القابلة للاسترداد؟\n• مين أكبر مورد؟\n• كم صرفنا مع سحاب؟\n• اعرض الفاتورة WP-3401",
    empty: "دفتر الفواتير فاضي. ارفع فاتورة واسألني مرة ثانية.",
    count: (n, parts) => `عندك ${n} ${fw(n)}: ${parts}.`,
    statusList: (n, label, total, lines) => n ? `${n} ${fw(n)} ${label} (${money(total)} ريال):\n${lines}` : `ما فيه فواتير ${label} حالياً.`,
    spend: (total, n, pend) => `إجمالي الإنفاق: ${money(total)} ريال على ${n} ${fw(n)} (بدون المرفوضة وغير المقروءة). منها ${money(pend)} ريال بانتظار الاعتماد.`,
    vat: (a, p) => `الضريبة القابلة للاسترداد على الفواتير المعتمدة: ${money(a)} ريال. وفيه ${money(p)} ريال على فواتير بانتظار الاعتماد.`,
    top: (lines) => `أكبر الموردين إنفاقاً:\n${lines}`,
    largest: (x, nm) => `أكبر فاتورة: ${nm}، رقم ${x.number}، بقيمة ${money(x.total)} ريال (${A.ar.stOne[x.status] || x.status}).`,
    dup: (lines, n) => n ? `اكتشفنا ${n} ${fw(n)} مكررة:\n${lines}` : "ما فيه فواتير مكررة.",
    foreign: (lines, n) => n ? `${n} ${fw(n)} بعملة أجنبية:\n${lines}` : "كل الفواتير بالريال السعودي.",
    suppliers: (n, lines) => `عندك ${n} موردين:\n${lines}`,
    supplier: (nm, n, total, parts, lines) => `${nm}: ${n} ${fw(n)}، صرفنا ${money(total)} ريال (بدون المرفوضة). ${parts}.\n${lines}`,
    invoice: (x, nm, failed) => `${nm} · ${x.number} · ${x.date || "بدون تاريخ"}\nالإجمالي ${money(x.total)} ${x.currency === "SAR" ? "ريال" : x.currency} (الضريبة ${money(x.vat)}). الحالة: ${A.ar.stOne[x.status] || x.status}.${failed ? `\nالمشاكل: ${failed}.` : ""}`,
    notFound: (no) => `ما لقيت الفاتورة ${no} في الدفتر.`,
    fallback: "ما فهمت سؤالك تماماً. أقدر أجاوب عن: عدد الفواتير، وش بانتظار الاعتماد أو يحتاج مراجعة، الضريبة القابلة للاسترداد، إجمالي الإنفاق، أكبر الموردين أو مورد معيّن، الفواتير المكررة، وتفاصيل أي رقم فاتورة.",
    more: (n) => `…و${n} غيرها.`,
  },
};

/* ---------- the engine ---------- */
function answer(question, allInvoices, uiLang) {
  const lang = isArabic(question) ? "ar" : (uiLang === "ar" && !/[a-z]{3,}/i.test(question) ? "ar" : "en");
  const L = A[lang], q = norm(question);
  const inv = (allInvoices || []).filter((x) => !x.checking);
  const nm = (x) => (lang === "ar" ? x.supplier.ar || x.supplier.en : x.supplier.en || x.supplier.ar) || x.file_name || "—";
  const sep = lang === "ar" ? "، " : ", ";
  const cur = (c) => (lang === "ar" && c === "SAR" ? "ريال" : c);
  const failedOf = (x) => (x.checks || []).filter((c) => !c.pass).map((c) => L.chk[c.k] || c.k).join(sep);
  const line = (x, extra) => `• ${nm(x)} · ${x.number || x.file_name} · ${money(x.total)} ${cur(x.currency)}${extra ? ` · ${extra}` : ""}`;
  const lines = (list, extra) => list.slice(0, 5).map((x) => line(x, extra && extra(x))).join("\n") + (list.length > 5 ? `\n${L.more(list.length - 5)}` : "");
  const sar = (x) => (x.currency === "SAR" ? x.total : 0);
  const sum = (list, f) => list.reduce((a, x) => a + f(x), 0);
  const by = (s) => inv.filter((x) => x.status === s);
  const countParts = () => ["approved", "pending", "review", "manual", "rejected"].filter((s) => by(s).length).map((s) => `${by(s).length} ${L.st[s]}`).join(sep);

  if (has(q, W.thanks) && q.split(" ").length <= 5) return L.thanks;
  if (!inv.length) return has(q, W.greet) ? L.greet : L.empty;

  // a specific invoice number, e.g. WP-3401 or INV-2701
  const tokens = question.toUpperCase().match(/[A-Z]{1,6}-?\d{2,}/g) || [];
  if (tokens.length) {
    const t = tokens[0].replace("-", "");
    const found = inv.filter((x) => String(x.number || "").toUpperCase().replace("-", "") === t);
    if (!found.length) return L.notFound(tokens[0]);
    return found.map((x) => L.invoice(x, nm(x), failedOf(x))).join("\n\n");
  }

  // a specific supplier
  const suppliers = new Map();
  inv.forEach((x) => { if (x.status !== "manual") { const k = (x.supplier.en || x.supplier.ar).toLowerCase(); if (!suppliers.has(k)) suppliers.set(k, []); suppliers.get(k).push(x); } });
  const hit = [...suppliers.values()].find((list) => nameWords(list[0].supplier.ar + " " + list[0].supplier.en).some((w) => q.includes(w)));
  if (hit) {
    const kept = hit.filter((x) => x.status !== "rejected");
    const parts = ["approved", "pending", "review", "rejected"].filter((s) => hit.some((x) => x.status === s)).map((s) => `${hit.filter((x) => x.status === s).length} ${L.st[s]}`).join(sep);
    return L.supplier(nm(hit[0]), hit.length, sum(kept, sar), parts, lines(hit, (x) => L.stOne[x.status]));
  }

  if (has(q, W.dup)) { const d = inv.filter((x) => (x.checks || []).some((c) => c.k === "dup" && !c.pass)); return L.dup(lines(d), d.length); }
  if (has(q, W.foreign)) { const f = inv.filter((x) => x.currency && x.currency !== "SAR"); return L.foreign(lines(f), f.length); }
  if (has(q, W.vat)) return L.vat(sum(by("approved"), (x) => x.vat), sum(by("pending"), (x) => x.vat));
  if (has(q, W.largest)) { const top = inv.filter((x) => x.status !== "manual").sort((a, b) => sar(b) - sar(a))[0]; if (top) return L.largest(top, nm(top)); }
  if (has(q, W.top)) {
    const ranked = [...suppliers.values()].map((list) => ({ x: list[0], v: sum(list.filter((x) => x.status !== "rejected"), sar) })).sort((a, b) => b.v - a.v).slice(0, 3);
    return L.top(ranked.map((r, i) => `${i + 1}. ${nm(r.x)} · ${money(r.v)} ${cur("SAR")}`).join("\n"));
  }

  // a status: approved / rejected first, because "approval" also appears in "waiting for approval"
  const status = has(q, W.approved) ? "approved" : has(q, W.rejected) ? "rejected" : has(q, W.manual) ? "manual"
    : has(q, W.review) ? "review" : has(q, W.pending) ? "pending" : null;
  if (status) {
    const list = by(status);
    const why = status === "review" ? (x) => failedOf(x) : status === "rejected" ? (x) => x.reason || "" : null;
    return L.statusList(list.length, L.st[status], sum(list, sar), lines(list, why));
  }

  if (has(q, W.count) || has(q, W.received)) return L.count(inv.length, countParts());
  if (has(q, W.spend)) { const kept = inv.filter((x) => !["rejected", "manual"].includes(x.status)); return L.spend(sum(kept, sar), kept.length, sum(by("pending"), sar)); }
  if (has(q, W.suppliers)) {
    const list = [...suppliers.values()].map((l) => `• ${nm(l[0])} · ${l.length}`);
    return L.suppliers(list.length, list.slice(0, 8).join("\n"));
  }
  if (has(q, W.help)) return L.help;
  if (has(q, W.greet)) return L.greet;
  return L.fallback;
}

const FC_ASSIST = { answer, _norm: norm };
if (typeof module !== "undefined" && module.exports) module.exports = FC_ASSIST;
else window.FC_ASSIST = FC_ASSIST;
})();
