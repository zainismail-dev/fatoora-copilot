/* Fatoora Copilot web app: talks to the FastAPI backend (same origin). */
(function () {
"use strict";

/* ---------- state ---------- */
const T = window.T;
const VIEWS = ["overview", "invoices", "approvals", "spend", "intake", "reconcile"];
const state = { view: "overview", invoices: [], me: null, mode: "loading", filter: "all", query: "", deleting: false, asTable: false, viewing: null, rejecting: false, editing: false, landed: null, busy: false };
let lang = "ar";
try { const saved = localStorage.getItem("fc-lang"); if (saved === "ar" || saved === "en") lang = saved; } catch (e) {}

/* ---------- helpers ---------- */
const $ = (id) => document.getElementById(id);
const t = () => T[lang];
const money = (n, d = 2) => (Number(n) || 0).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const isoOk = (s) => /^\d{4}-\d{2}-\d{2}/.test(s || "");
const locale = () => (lang === "ar" ? "ar-SA-u-nu-latn-ca-gregory" : "en-GB");
const asDate = (iso) => new Date(iso.slice(0, 10) + "T12:00:00");
const fmtDate = (iso) => (isoOk(iso) ? asDate(iso).toLocaleDateString(locale(), { day: "numeric", month: "short" }) : iso || "—");
const fullDate = (iso) => (isoOk(iso) ? asDate(iso).toLocaleDateString(locale(), { day: "numeric", month: "long", year: "numeric" }) : iso || "—");
function hijri(iso) {
  if (!isoOk(iso)) return "";
  try { return asDate(iso).toLocaleDateString((lang === "ar" ? "ar" : "en") + "-SA-u-ca-islamic-umalqura-nu-latn", { day: "numeric", month: "long", year: "numeric" }); } catch (e) { return ""; }
}
const name = (x) => (lang === "ar" ? x.supplier.ar || x.supplier.en : x.supplier.en || x.supplier.ar) || x.file_name || "—";
const statusOf = (x) => (x.checking ? "checking" : x.status);
const isManager = () => state.me && state.me.user.role === "manager";
const byId = (id) => state.invoices.find((x) => x.id === id);
const replace = (inv) => { const i = state.invoices.findIndex((x) => x.id === inv.id); if (i >= 0) state.invoices[i] = inv; else state.invoices.push(inv); };

let toastTimer;
function toast(msg, ms) { const el = $("toast"); el.textContent = msg; el.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.hidden = true; }, ms || 2800); }

/* ---------- server ---------- */
async function api(path, options) {
  const r = window.FC_DEMO
    ? await window.FC_DEMO.fetch(path, options || {})
    : await fetch(path, Object.assign({ credentials: "same-origin", cache: "no-store" }, options));
  if (r.status === 401) { location.href = "/login"; throw new Error("signed out"); }
  const body = await r.json().catch(() => ({}));
  if (!r.ok || body.ok === false) {
    const err = new Error((body.code && t().codes[body.code]) || body.message || body.detail || "HTTP " + r.status);
    err.code = body.code; throw err;
  }
  return body;
}
async function load(quiet) {
  try {
    if (!state.me) state.me = await api("/api/me");
    const data = await api("/api/invoices");
    const inFlight = state.invoices.filter((x) => x.checking);
    state.invoices = data.invoices.concat(inFlight);
    state.mode = "ok";
  } catch (e) {
    if (e.message === "signed out") return;
    state.mode = "offline"; if (!quiet) toast(t().offline, 6000);
  }
  renderAll();
}
async function upload(file) {
  if (!file || state.busy) return;
  state.busy = true;
  const temp = { id: "tmp-" + Date.now(), checking: true, status: "checking", supplier: { ar: file.name, en: file.name }, number: "…", date: "", vat: 0, total: 0, currency: "SAR", checks: [], lines: [], file_name: file.name };
  state.invoices.push(temp); state.filter = "all"; render(); toast(t().reading, 20000);
  try {
    const fd = new FormData(); fd.append("file", file, file.name);
    const res = await api("/api/invoices/upload", { method: "POST", body: fd });
    state.invoices = state.invoices.filter((x) => x !== temp); replace(res.invoice);
    if (state.view !== "invoices") showView("invoices", { filter: "all" }); else render();
    toast(t().received[res.invoice.status] || t().received.review, 4500);
    if (res.invoice.status === "manual") openViewer(res.invoice.id);
  } catch (e) {
    state.invoices = state.invoices.filter((x) => x !== temp); render(); toast(t().uploadFail(e.message), 6000);
  }
  state.busy = false;
}
async function decide(id, action, reason) {
  try {
    const res = await api(`/api/invoices/${encodeURIComponent(id)}/decide`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, reason: reason || "" }) });
    replace(res.invoice); state.rejecting = false; state.landed = id; render();
    toast(action === "approve" ? t().approvedToast : t().rejectedToast);
    setTimeout(() => { state.landed = null; }, 600);
  } catch (e) { toast(t().decideFail(e.message), 6000); }
}
async function removeInvoice(id) {
  try {
    await api(`/api/invoices/${encodeURIComponent(id)}`, { method: "DELETE" });
    state.invoices = state.invoices.filter((x) => x.id !== id); closeViewer(); render(); toast(t().deletedToast);
  } catch (e) { toast(t().deleteFail(e.message), 6000); }
}
function exportCsv() {
  if (window.FC_DEMO) { window.FC_DEMO.downloadCsv(state.invoices); return; }
  location.href = "/api/invoices.csv";
}
async function saveDetails(id, form) {
  const f = Object.fromEntries(new FormData(form).entries());
  if (!String(f.supplier_name_ar || "").trim() && !String(f.supplier_name_en || "").trim()) { toast(t().codes.incomplete, 5000); $("f-supplier_name_ar").focus(); return; }
  ["subtotal", "vat_amount", "total"].forEach((k) => { f[k] = Number(String(f[k] || 0).replace(/,/g, "")) || 0; });
  try {
    const res = await api(`/api/invoices/${encodeURIComponent(id)}/details`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(f) });
    replace(res.invoice); state.editing = false; render(); toast(t().savedToast);
  } catch (e) { toast(t().saveFail(e.message), 6000); }
}

async function retryAI(id, btn) {
  if (btn) { btn.disabled = true; btn.textContent = t().v.retrying; }
  try {
    const res = await api(`/api/invoices/${encodeURIComponent(id)}/retry`, { method: "POST" });
    replace(res.invoice); state.editing = false; render(); toast(t().retriedToast);
  } catch (e) { await load(true); toast(t().retryFail(e.message), 7000); }
}

/* ---------- numbers ---------- */
function metrics() {
  const s = (x) => statusOf(x);
  const list = state.invoices.filter((x) => !x.checking);
  const appr = list.filter((x) => s(x) === "approved");
  const pend = list.filter((x) => s(x) === "pending");
  const counted = list.filter((x) => !["rejected", "manual"].includes(s(x)) && x.currency === "SAR");
  return {
    count: list.length, sups: new Set(list.filter((x) => x.status !== "manual").map((x) => (x.supplier.en || x.supplier.ar).toLowerCase())).size,
    spend: money(counted.reduce((a, x) => a + x.total, 0), 0),
    vatApproved: appr.reduce((a, x) => a + x.vat, 0), approvedN: appr.length,
    vatPending: pend.reduce((a, x) => a + x.vat, 0), pendTotal: pend.reduce((a, x) => a + x.total, 0),
    pending: pend.length, review: list.filter((x) => s(x) === "review").length, manual: list.filter((x) => s(x) === "manual").length,
    read: list.filter((x) => s(x) !== "manual").length,
    passed: list.filter((x) => ["pending", "approved", "rejected"].includes(s(x))).length,
  };
}

/* ---------- rendering ---------- */
const ICONS = {
  home: '<path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/>',
  doc: '<path d="M6 3h9l3 3v15H6z"/><path d="M9 9h6M9 13h6M9 17h4"/>',
  check: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="m8.5 12.5 2.5 2.5 4.5-5"/>',
  chart: '<path d="M4 20h16"/><path d="M7 16V9M12 16V5M17 16v-4"/>',
  inbox: '<path d="M3 13h5l1.5 3h5L16 13h5"/><path d="M5 5h14l2 8v6H3v-6z"/>',
  bank: '<path d="M3 9.5 12 4l9 5.5"/><path d="M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 20h18"/>',
};
function renderStatic() {
  const L = t(), set = (id, v) => { $(id).textContent = v; };
  document.documentElement.lang = lang; document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  $("lang-ar").setAttribute("aria-pressed", String(lang === "ar")); $("lang-en").setAttribute("aria-pressed", String(lang === "en"));
  set("t-brand", L.brand); set("t-tag", L.tag); set("logout", window.FC_DEMO ? L.resetDemo : L.logout);
  set("t-date", new Date().toLocaleDateString(locale(), { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "Asia/Riyadh" }));
  set("open-agent", L.agent); set("go-desk", L.goDesk); set("upload-btn", L.upload);
  set("denom-label", L.denomL); set("denom-unit", L.denomU); set("denom-corner", L.denomC);
  $("ledger-search").placeholder = L.search; set("search-label", L.searchLabel); set("export-csv", L.exportCsv);
  set("ledger-h", L.ledger); set("desk-h", L.desk); set("spend-h", L.spend); set("intake-h", L.intake);
  set("t-drop", L.drop); set("t-drop2", L.drop2); set("t-dropnote", window.FC_DEMO ? L.demoDrop : L.dropNote); set("t-foot", L.foot);
  set("agent-h", L.agentT); set("close-agent", L.close); set("ask-send", L.send); set("ask-label", L.askLabel); $("ask-input").placeholder = L.askPh;
  set("v-close", L.v.close);
  $("sugg").innerHTML = L.sugg.map((s) => `<button type="button" class="chip" data-q="${esc(s)}">${esc(s)}</button>`).join("");
  $("thead").innerHTML = L.cols.map((c, i) => `<th scope="col"${i === 3 || i === 4 ? ' class="amt"' : ""}>${c}</th>`).join("");
}
function renderChrome() {
  const L = t(), me = state.me;
  $("t-co").textContent = me ? me.company : "";
  $("t-user").textContent = me ? `${me.user.name} · ${L.roles[me.user.role]}` : "";
  const mode = $("t-mode");
  if (state.mode === "offline") { mode.textContent = L.modes.offline; mode.className = "demo off"; }
  else if (!me) { mode.textContent = L.modes.loading; mode.className = "demo"; }
  else if (me.demo) { mode.textContent = L.modes.demo; mode.className = "demo"; }
  else if (me.ai.length) { mode.textContent = L.modes.ai(me.ai.map((p) => L.by[p] || p)); mode.className = "demo live"; }
  else { mode.textContent = L.modes.noai; mode.className = "demo"; }
  $("inbox-box").innerHTML = me && me.email_enabled
    ? `<div class="fine">${esc(L.fwd)}</div><div class="addr" style="margin-top:6px"><code id="addr">${esc(me.inbox)}</code><button type="button" class="btn" id="copy-addr">${L.copy}</button></div>`
    : `<p class="notice">${esc(L.emailOff)}</p>`;
}
function renderNav(m) {
  $("nav").innerHTML = t().nav.map(([id, label, ic]) => `<a href="#${id}" data-view="${id}"${id === state.view ? ' aria-current="page"' : ""}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[ic]}</svg>${label}${id === "approvals" && m.pending ? `<span class="count">${m.pending}</span>` : ""}</a>`).join("");
  const item = t().nav.find((n) => n[0] === state.view);
  $("t-page").textContent = state.view === "overview" || !item ? t().page : item[1];
}
function showView(view, opts) {
  state.view = VIEWS.includes(view) ? view : "overview";
  document.body.dataset.view = state.view;
  document.querySelectorAll("[data-in]").forEach((el) => { el.hidden = !el.dataset.in.split(" ").includes(state.view); });
  if (opts && opts.filter) state.filter = opts.filter;
  if (location.hash.slice(1) !== state.view) history.replaceState(null, "", "#" + state.view);
  render();
  window.scrollTo({ top: 0, behavior: "auto" });
}
function renderHero(m) {
  $("hero-h").textContent = t().hero(m, state.me ? state.me.user.role : "manager");
  $("hero-p").innerHTML = t().heroP(m);
  $("denom-big").textContent = money(m.vatApproved, 0);
  $("denom-under").textContent = t().denomUnder(m.approvedN);
}
function renderPipe(m) {
  const L = t(), n = [m.count, m.read, m.passed, m.pending, m.approvedN];
  $("pipe").innerHTML = L.stages.map(([a, b], i) => {
    let extra = "";
    if (i === 1 && m.manual) extra = `<button type="button" class="branch" data-filter-go="manual">${L.branchManual(m.manual)}</button>`;
    if (i === 2 && m.review) extra = `<button type="button" class="branch" data-filter-go="review">${L.branch(m.review)}</button>`;
    return `<div class="stage${i === 3 ? " focus" : ""}"><span class="step">${i + 1}</span><span class="n num">${n[i]}</span><div>${a}</div><div class="lbl">${b}</div>${extra}</div>`;
  }).join("");
}
const stamp = (x) => { const s = statusOf(x); return `<span class="stamp ${s}${state.landed === x.id ? " land" : ""}">${t().st[s]}</span>`; };
const who = (x, small) => `<div class="who"><div><span>${esc(name(x))}</span>${small ? `<small>${small}</small>` : ""}</div></div>`;
const isLarge = (x) => (x.checks || []).some((c) => c.k === "large");
function renderFilters() {
  $("filters").innerHTML = Object.entries(t().f).map(([k, v]) => `<button type="button" class="chip" data-filter="${k}" aria-pressed="${state.filter === k}">${v}</button>`).join("");
}
function renderLedger() {
  const L = t();
  const q = state.query.trim().toLowerCase();
  const matches = (x) => !q || [x.supplier.ar, x.supplier.en, x.number, x.vat_no, x.file_name].some((v) => String(v || "").toLowerCase().includes(q));
  const byStatus = state.invoices.filter((x) => state.filter === "all" || statusOf(x) === state.filter);
  const rows = byStatus.filter(matches).slice().reverse();
  $("ledger-count").textContent = state.me ? L.shown(rows.length, byStatus.length) : "";
  if (!rows.length) { $("ledger").innerHTML = `<tr><td colspan="6" class="empty">${!state.me ? L.modes.loading : q ? L.noMatch : L.noRows}</td></tr>`; return; }
  $("ledger").innerHTML = rows.map((x) => `<tr class="row"${x.checking ? "" : ` data-open="${esc(x.id)}" tabindex="0"`} aria-label="${esc(L.open + ": " + name(x) + " " + x.number)}">
    <td>${who(x, isLarge(x) ? L.large : "")}</td>
    <td class="nw num ltr">${esc(x.number || "—")}</td>
    <td class="nw" title="${esc(hijri(x.date))}">${fmtDate(x.date)}</td>
    <td class="amt nw num">${money(x.vat)}</td>
    <td class="amt nw num"><b>${money(x.total)}</b> <small>${esc(x.currency)}</small></td>
    <td>${stamp(x)}</td></tr>`).join("");
}
function renderDesk(m) {
  const L = t(), pend = state.invoices.filter((x) => statusOf(x) === "pending");
  $("desk-sub").textContent = pend.length ? L.deskSub(money(m.pendTotal, 0)) : "";
  $("desk").innerHTML = !pend.length ? `<li class="empty">${L.deskEmpty}</li>` : pend.map((x) => {
    const flags = (x.checks || []).filter((c) => c.note).map((c) => `<div class="dflag">! ${esc(L.chk[c.k][0])}</div>`).join("");
    const acts = isManager() ? `<button type="button" class="btn solid" data-approve="${esc(x.id)}">${L.approve}</button>` : "";
    return `<li><div class="dtop">${who(x, `<span class="num ltr">${esc(x.number)}</span> · ${fmtDate(x.date)}`)}<span class="amt num">${money(x.total, 0)}</span></div>${flags}
      <div class="dacts">${acts}<button type="button" class="btn" data-open="${esc(x.id)}">${L.open}</button></div></li>`;
  }).join("") + (!isManager() && pend.length ? `<li class="empty">${L.clerkNote}</li>` : "");
  const stuck = m.review + m.manual;
  $("desk-foot").innerHTML = esc(L.deskFoot(m.review, m.manual)) + (stuck ? ` <button type="button" class="link" data-filter-go="${m.manual ? "manual" : "review"}">${L.showReview}</button>` : "");
}
function renderSpend(m) {
  const L = t(), by = new Map();
  state.invoices.filter((x) => !["rejected", "checking", "manual"].includes(statusOf(x)) && x.currency === "SAR").forEach((x) => {
    const key = (x.supplier.en || x.supplier.ar).toLowerCase(); const e = by.get(key) || { x, v: 0 }; e.v += x.total; by.set(key, e);
  });
  let list = [...by.values()].sort((a, b) => b.v - a.v).map((e) => [name(e.x), e.v]);
  if (list.length > 6) { const rest = list.slice(6).reduce((a, e) => a + e[1], 0); list = list.slice(0, 6).concat([[L.other, rest]]); }
  $("spend-toggle").textContent = state.asTable ? L.asBars : L.asTable; $("spend-toggle").setAttribute("aria-pressed", String(state.asTable));
  $("vatline").innerHTML = L.vatline(money(m.vatApproved, 0), money(m.vatPending, 0));
  if (!list.length) { $("spend").innerHTML = `<div class="empty">${L.noSpend}</div>`; return; }
  if (state.asTable) {
    $("spend").innerHTML = `<div class="scroll"><table style="min-width:0"><thead><tr><th scope="col">${L.supplier}</th><th scope="col" class="amt">${L.amount}</th></tr></thead><tbody>${list.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="amt num">${money(v)}</td></tr>`).join("")}</tbody></table></div>`;
    return;
  }
  const max = Math.max(...list.map((e) => e[1]));
  $("spend").innerHTML = `<div class="bars" role="img" aria-label="${esc(L.spend)}">${list.map(([k, v]) => {
    const p = (v / max) * 74;
    return `<div class="br" title="${esc(k)}: SAR ${money(v)}"><span>${esc(k)}</span><div class="track"><div class="fill" style="width:${p}%"></div><div class="val" style="inset-inline-start:calc(${p}% + 8px)">${money(v, 0)}</div></div></div>`;
  }).join("")}</div>`;
}
function render() {
  const m = metrics();
  renderChrome(); renderNav(m); renderHero(m); renderPipe(m); renderFilters(); renderLedger(); renderDesk(m); renderSpend(m);
  if (window.FC_RECON) window.FC_RECON.render();
  if (state.viewing) renderViewer();
}
function renderAll() { renderStatic(); render(); drawGuilloche(); }

/* ---------- invoice viewer ---------- */
function checksList(x) {
  const L = t();
  if (!(x.checks || []).length) return `<p class="notice">${L.v.noChecks}</p>`;
  return `<ul class="checks">${x.checks.map((c) => {
    let txt = c.note ? L.chk[c.k][0] : L.chk[c.k][c.pass ? 0 : 1];
    if (!c.pass && c.k === "rate" && c.expected != null) txt += L.expected(money(c.expected));
    if (!c.pass && c.k === "total" && c.diff != null) txt += L.diff(money(c.diff));
    if (!c.pass && c.k === "dup" && c.dupDate) txt += L.dupOf(fmtDate(c.dupDate));
    const ic = c.note ? '<span class="ic note" aria-hidden="true">!</span>' : c.pass ? '<span class="ic ok" aria-hidden="true">✓</span>' : '<span class="ic bad" aria-hidden="true">✕</span>';
    return `<li>${ic}<span>${esc(txt)}</span></li>`;
  }).join("")}</ul>`;
}
function detailsForm(x) {
  const F = t().v.fields;
  const val = { supplier_name_ar: x.supplier.ar, supplier_name_en: x.supplier.en, supplier_vat_number: x.vat_no, invoice_number: x.number, invoice_date: isoOk(x.date) ? x.date.slice(0, 10) : "", currency: x.currency || "SAR", subtotal: x.subtotal || "", vat_amount: x.vat || "", total: x.total || "" };
  const input = (k, type, wide) => `<label${wide ? ' class="wide"' : ""}>${F[k]}<input name="${k}" id="f-${k}" type="${type}" value="${esc(val[k])}"${type === "number" ? ' step="0.01" inputmode="decimal"' : ""}${["invoice_number", "invoice_date", "total"].includes(k) ? " required" : ""}${k === "supplier_vat_number" ? ' inputmode="numeric" dir="ltr"' : ""}></label>`;
  const cur = ["SAR", "USD", "EUR", "AED"].map((c) => `<option${c === val.currency ? " selected" : ""}>${c}</option>`).join("");
  return `<form class="form" id="details-form" data-id="${esc(x.id)}">
    ${input("supplier_name_ar", "text", true)}${input("supplier_name_en", "text", true)}${input("supplier_vat_number", "text", true)}
    ${input("invoice_number", "text")}${input("invoice_date", "date")}
    <label>${F.currency}<select name="currency" id="f-currency">${cur}</select></label>${input("subtotal", "number")}
    ${input("vat_amount", "number")}${input("total", "number")}
    <div class="row"><button type="submit" class="btn solid">${t().v.save}</button>${x.status === "manual" ? "" : `<button type="button" class="btn" data-cancel-edit="1">${t().cancel}</button>`}</div>
  </form>`;
}
function decisionBox(x) {
  const L = t(), V = L.v, s = statusOf(x);
  if (s === "manual" || state.editing) return detailsForm(x);
  if (s === "pending") {
    if (!isManager()) return `<p>${V.pendingClerk}</p>`;
    return state.rejecting
      ? `<label for="reason-in">${L.reasonLabel}</label><input id="reason-in"><div class="row"><button type="button" class="btn danger" data-confirm="${esc(x.id)}">${L.confirmReject}</button><button type="button" class="btn" data-cancel="1">${L.cancel}</button></div>`
      : `<p>${V.pendingP}</p><div class="row"><button type="button" class="btn solid" data-approve="${esc(x.id)}">${L.approve}</button><button type="button" class="btn danger" data-reject="${esc(x.id)}">${L.reject}</button></div>`;
  }
  if (s === "review") return `<p>${V.reviewP}</p><div class="row"><button type="button" class="btn" data-edit="1">${V.edit}</button></div>`;
  return `<p>${V.doneP(s)}${x.reason ? ` ${V.reason}: ${esc(x.reason)}` : ""}</p>`;
}
function deleteZone(x) {
  const L = t();
  if (!isManager() || x.status === "approved" || x.checking) return "";
  return state.deleting
    ? `<div class="danger-zone"><p>${L.deleteP}</p><div class="row"><button type="button" class="btn danger" data-confirm-delete="${esc(x.id)}">${L.confirmDelete}</button><button type="button" class="btn" data-cancel-delete="1">${L.cancel}</button></div></div>`
    : `<div class="danger-zone"><button type="button" class="link danger" data-delete="1">${L.deleteInv}</button></div>`;
}
function aiNotice(x) {
  const V = t().v, canRetry = ["manual", "review"].includes(x.status) && String(x.extracted_by || "").startsWith("manual");
  if (!canRetry) return "";
  const why = x.note && !/^Edited by/.test(x.note) ? `<br><span class="num ltr" style="font-size:12px">${esc(x.note.slice(0, 220))}</span>` : "";
  return `<p class="notice">${V.aiFailed}${why}</p><button type="button" class="btn" data-retry="${esc(x.id)}">${V.retry}</button>`;
}
function renderViewer() {
  const x = byId(state.viewing); if (!x) { closeViewer(); return; }
  const L = t(), V = L.v, s = statusOf(x), idx = lang === "ar" ? 0 : 1;
  const failed = (k) => (x.checks || []).some((c) => c.k === k && !c.pass);
  const rate = x.subtotal ? Math.round((x.vat / x.subtotal) * 1000) / 10 : 0;
  const by = String(x.extracted_by || "").replace("cache:", "");
  const big = ["approved", "rejected", "review", "manual"].includes(s) ? `<div class="bigstamp ${s}${state.landed === x.id ? " land" : ""}">${V.stamp[s][0]}<small>${V.stamp[s][1]}</small></div>` : "";
  $("v-title").textContent = `${name(x)} · ${x.number || x.file_name}`;
  $("vbody").innerHTML = `
    <article class="doc" aria-label="${esc(V.title)}">
      <div class="dt"><div><h4>${V.title}</h4><small>${V.sub}</small></div></div>
      <div class="parties">
        <div><b>${V.seller}</b>${esc(name(x))}<br>${V.vatNo}: <span class="num ltr${failed("vatno") ? " bad" : ""}">${esc(x.vat_no || "—")}</span></div>
        <div><b>${V.recv}</b>${V.via[x.source === "email" ? "email" : "upload"]}<br><span class="num ltr">${esc(x.received_at || "")}</span><br>${esc(x.sender || "")}</div>
      </div>
      <div class="meta"><div><b>${V.no}</b><span class="num ltr">${esc(x.number || "—")}</span></div><div><b>${V.date}</b>${fullDate(x.date)}</div><div><b>${V.hijri}</b>${esc(hijri(x.date))}</div></div>
      <table><thead><tr><th>${V.item}</th><th class="amt">${V.qty}</th><th class="amt">${V.price}</th><th class="amt">${V.line}</th></tr></thead>
        <tbody>${(x.lines || []).map((l) => `<tr><td>${esc(l.description)}</td><td class="amt num">${l.quantity || 1}</td><td class="amt num">${money(l.unit_price || l.amount)}</td><td class="amt num">${money(l.amount || (l.unit_price || 0) * (l.quantity || 1))}</td></tr>`).join("")}</tbody></table>
      <div class="tot"><div></div><dl><dt>${V.subtotal}</dt><dd class="num">${money(x.subtotal)}</dd><dt>${V.vat} <span class="num">${rate}%</span></dt><dd class="num${failed("rate") ? " bad" : ""}">${money(x.vat)}</dd><dt class="grand">${V.total}</dt><dd class="grand num${failed("total") ? " bad" : ""}">${money(x.total)} ${esc(x.currency)}</dd></dl></div>
      ${big}
    </article>
    <div class="side">
      <a class="filelink" href="${window.FC_DEMO ? window.FC_DEMO.fileUrl(x) : `/api/invoices/${encodeURIComponent(x.id)}/file`}" target="_blank" rel="noopener">${V.original} (${esc(x.file_name)})</a>
      ${aiNotice(x)}
      <h4>${V.checks}</h4>${checksList(x)}
      <p class="fine">${esc(V.readBy(L.by[by] || by || "—"))}</p>
      <h4>${s === "manual" ? V.enter : state.editing ? V.edit : V.decision}</h4><div class="decision">${decisionBox(x)}</div>
      ${deleteZone(x)}
    </div>`;
  if (state.rejecting) { const i = $("reason-in"); if (i) i.focus(); }
}
function openViewer(id) { state.viewing = id; state.rejecting = false; state.editing = false; state.deleting = false; $("scrim").hidden = false; $("viewer").hidden = false; renderViewer(); $("v-close").focus(); }
function closeViewer() { state.viewing = null; state.editing = false; $("scrim").hidden = true; $("viewer").hidden = true; }

/* ---------- guilloché (banknote security lines) ---------- */
function drawGuilloche() {
  const c = $("guilloche"), r = c.getBoundingClientRect(), dpr = Math.min(window.devicePixelRatio || 1, 2);
  c.width = Math.max(1, r.width * dpr); c.height = Math.max(1, r.height * dpr);
  const g = c.getContext("2d"); g.scale(dpr, dpr); g.clearRect(0, 0, r.width, r.height);
  g.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--note-line").trim() || "rgba(232,241,236,.16)"; g.lineWidth = 0.8;
  const cx = document.documentElement.dir === "rtl" ? r.width * 0.16 : r.width * 0.84, cy = r.height * 0.5;
  const rose = (R, rr, d, s, turns) => { g.beginPath(); for (let i = 0; i <= turns * 360; i++) { const a = (i * Math.PI) / 180, x = (R - rr) * Math.cos(a) + d * Math.cos(((R - rr) / rr) * a), y = (R - rr) * Math.sin(a) - d * Math.sin(((R - rr) / rr) * a); i ? g.lineTo(cx + x * s, cy + y * s) : g.moveTo(cx + x * s, cy + y * s); } g.stroke(); };
  rose(96, 36, 58, 1.25, 9); rose(80, 28, 44, 1.25, 7); rose(60, 22, 30, 1.25, 11);
  g.beginPath();
  for (let k = 0; k < 7; k++) { const yb = r.height - 18 - k * 7; for (let x = 0; x <= r.width; x += 4) { const y = yb + Math.sin(x / 22 + k) * 4; x ? g.lineTo(x, y) : g.moveTo(x, y); } }
  g.stroke();
}

/* ---------- finance assistant ----------
   Full app with an AI key: the question goes to /api/ask (Gemini/Mistral, with the ledger facts).
   Demo, no key, or AI busy: the built-in engine in assistant.js answers from the ledger. */
function addMsg(text, who, by) {
  const m = document.createElement("div"); m.className = "msg " + who; m.dir = "auto"; m.textContent = text;
  if (by) { const s = document.createElement("span"); s.className = "msg-by"; s.textContent = by; m.appendChild(s); }
  $("msgs").appendChild(m); $("msgs").scrollTop = $("msgs").scrollHeight; return m;
}
const localAnswer = (q) => window.FC_ASSIST.answer(q, state.invoices, state.lang);
async function ask(q) {
  if (!q || !q.trim() || state.asking) return;
  addMsg(q, "me");
  const useAI = !window.FC_DEMO && state.me && state.me.ai && state.me.ai.length;
  if (!useAI) { setTimeout(() => addMsg(localAnswer(q), "bot"), 150); return; }
  state.asking = true;
  const wait = addMsg(t().thinking, "bot wait");
  try {
    const r = await api("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q }) });
    wait.remove(); addMsg(r.answer, "bot", t().by[r.by] || r.by);
  } catch (e) {
    wait.remove(); addMsg(localAnswer(q), "bot");
  } finally { state.asking = false; }
}

/* ---------- shared with recon.js (the bank reconciliation page) ---------- */
window.FC_APP = { api, t, esc, money, toast, fmtDate, isManager, state, locale };

/* ---------- events ---------- */
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-filter],[data-filter-go],[data-open],[data-approve],[data-reject],[data-confirm],[data-cancel],[data-edit],[data-cancel-edit],[data-retry],[data-delete],[data-confirm-delete],[data-cancel-delete],[data-q],a[data-view],#copy-addr");
  if (!el) return;
  const d = el.dataset;
  if (el.id === "copy-addr") {
    const v = $("addr").textContent;
    const select = () => { const r = document.createRange(); r.selectNodeContents($("addr")); const s = getSelection(); s.removeAllRanges(); s.addRange(r); };
    try { navigator.clipboard.writeText(v).then(() => toast(t().copied), () => { select(); toast(t().copyFail); }); } catch (err) { select(); toast(t().copyFail); }
    return;
  }
  if (d.view) { e.preventDefault(); showView(d.view); return; }
  if (d.filter) { state.filter = d.filter; render(); return; }
  if (d.filterGo) { closeViewer(); showView("invoices", { filter: d.filterGo }); return; }
  if (d.approve) { decide(d.approve, "approve"); return; }
  if (d.reject) { state.rejecting = true; renderViewer(); return; }
  if (d.cancel) { state.rejecting = false; renderViewer(); return; }
  if (d.confirm) { const i = $("reason-in"); decide(d.confirm, "reject", i && i.value.trim()); return; }
  if (d.retry) { retryAI(d.retry, el); return; }
  if (d.delete) { state.deleting = true; renderViewer(); return; }
  if (d.cancelDelete) { state.deleting = false; renderViewer(); return; }
  if (d.confirmDelete) { removeInvoice(d.confirmDelete); return; }
  if (d.edit) { state.editing = true; renderViewer(); return; }
  if (d.cancelEdit) { state.editing = false; renderViewer(); return; }
  if (d.open) { openViewer(d.open); return; }
  if (d.q) { ask(d.q); }
});
document.addEventListener("submit", (e) => {
  if (e.target.id === "details-form") { e.preventDefault(); saveDetails(e.target.dataset.id, e.target); }
  if (e.target.id === "ask-form") { e.preventDefault(); const i = $("ask-input"); ask(i.value); i.value = ""; }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.matches && e.target.matches("tr.row[data-open]")) openViewer(e.target.dataset.open);
  if (e.key === "Escape") { if (!$("viewer").hidden) closeViewer(); else if (!$("drawer").hidden) { $("drawer").hidden = true; $("open-agent").focus(); } }
});
$("v-close").onclick = closeViewer;
$("scrim").onclick = closeViewer;
const setLang = (l) => { lang = l; try { localStorage.setItem("fc-lang", l); } catch (e) {} renderAll(); };
$("lang-ar").onclick = () => setLang("ar");
$("lang-en").onclick = () => setLang("en");
$("go-desk").onclick = () => showView("approvals");
$("export-csv").onclick = exportCsv;
$("ledger-search").addEventListener("input", (e) => { state.query = e.target.value; renderLedger(); });
window.addEventListener("hashchange", () => { const v = location.hash.slice(1); if (v !== state.view) showView(v); });
$("upload-btn").onclick = () => $("file-in").click();
$("spend-toggle").onclick = () => { state.asTable = !state.asTable; renderSpend(metrics()); };
$("logout").onclick = async () => {
  if (window.FC_DEMO) { window.FC_DEMO.reset(); if (window.FC_RECON) window.FC_RECON.reset(); closeViewer(); state.filter = "all"; state.query = ""; $("ledger-search").value = ""; await load(true); showView("overview"); toast(t().demoReset); return; }
  try { await fetch("/api/logout", { method: "POST" }); } finally { location.href = "/login"; }
};
$("open-agent").onclick = () => { $("drawer").hidden = false; if (!$("msgs").children.length) addMsg(t().hello, "bot"); $("ask-input").focus(); };
$("close-agent").onclick = () => { $("drawer").hidden = true; $("open-agent").focus(); };
$("file-in").addEventListener("change", (e) => { upload(e.target.files[0]); e.target.value = ""; });
const drop = $("drop");
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => upload(e.dataTransfer && e.dataTransfer.files[0]));
let resizeTimer; window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(drawGuilloche, 120); });

/* ---------- start ---------- */
renderStatic();
showView(location.hash.slice(1));
drawGuilloche();
load(false);
setInterval(() => { if (!document.hidden && !state.busy) load(true); }, 30000);
if (document.fonts && document.fonts.ready) document.fonts.ready.then(drawGuilloche);
})();
