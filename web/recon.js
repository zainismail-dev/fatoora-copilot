/* Bank reconciliation page. Uses the shared helpers app.js exposes as window.FC_APP. */
(function () {
"use strict";

const A = () => window.FC_APP;
const $ = (id) => document.getElementById(id);
const rs = { list: null, current: null, loading: false, busy: false, err: "", confirmDel: false, files: { bank: null, book: null } };

const L = () => A().t().r;
const esc = (s) => A().esc(s);
const money = (n) => A().money(n);
const acct = (v) => (v < 0 ? `(${money(-v)})` : money(v));      // accounting style: negatives in brackets
const pos = (v) => money(Math.abs(v));
const day = (iso) => A().fmtDate(iso);
const monthOf = (iso) => new Date(iso + "T12:00:00").toLocaleDateString(A().locale(), { month: "long", year: "numeric" });

/* ---------- server ---------- */
async function loadList(openId) {
  rs.loading = true;
  try {
    rs.list = (await A().api("/api/reconciliations")).reconciliations;
    const id = openId || (rs.current ? rs.current.id : rs.list[0] && rs.list[0].id);
    rs.current = id && rs.list.some((r) => r.id === id) ? (await A().api("/api/reconciliations/" + encodeURIComponent(id))).reconciliation : null;
  } catch (e) { rs.list = rs.list || []; rs.err = e.message; }
  rs.loading = false; render();
}
async function open(id) {
  try { rs.current = (await A().api("/api/reconciliations/" + encodeURIComponent(id))).reconciliation; rs.confirmDel = false; render(); scrollToResult(); }
  catch (e) { A().toast(e.message); }
}
async function run(files) {
  const f = files || rs.files;
  if (!f.bank || !f.book) { rs.err = L().codes.need_files; render(); return; }
  const fd = new FormData();
  fd.append("bank", f.bank, f.bank.name); fd.append("book", f.book, f.book.name);
  fd.append("bank_closing", ($("rc-bank-bal") || {}).value || ""); fd.append("book_closing", ($("rc-book-bal") || {}).value || "");
  rs.busy = true; rs.err = ""; render();
  try {
    const rec = (await A().api("/api/reconciliations", { method: "POST", body: fd })).reconciliation;
    rs.current = rec; rs.files = { bank: null, book: null }; rs.confirmDel = false;
    A().toast(L().done);
    await loadList(rec.id); scrollToResult();
  } catch (e) { rs.err = L().codes[e.code] || e.message; }
  rs.busy = false; render();
}
async function remove() {
  try { await A().api("/api/reconciliations/" + encodeURIComponent(rs.current.id), { method: "DELETE" }); rs.current = null; A().toast(L().deleted); await loadList(); }
  catch (e) { A().toast(e.message); }
}
const scrollToResult = () => { const el = $("rc-result"); if (el && el.getBoundingClientRect().top < 0) el.scrollIntoView({ behavior: "smooth", block: "start" }); };

/* ---------- views ---------- */
function form() {
  const T = L(), demo = !!window.FC_DEMO, f = rs.files;
  const pick = (side, label) => `<label class="drop rc-drop${f[side] ? " chosen" : ""}" for="rc-${side}">
      <b>${label}</b><span class="ltr">${f[side] ? esc(f[side].name) : esc(T.fileHint)}</span></label>
    <input type="file" id="rc-${side}" class="sr" accept=".csv,.txt,.xlsx${demo ? "" : ",.xlsm"}">`;
  return `<div class="ph"><h3>${T.newH}</h3></div>
    <div class="rc-form">
      <p class="fine">${esc(T.intro)}</p>
      ${pick("bank", T.bankF)}${pick("book", T.bookF)}
      <details class="rc-bal"><summary>${T.noBal}</summary>
        <label>${T.bankBal}<input id="rc-bank-bal" inputmode="decimal" autocomplete="off" class="ltr num"></label>
        <label>${T.bookBal}<input id="rc-book-bal" inputmode="decimal" autocomplete="off" class="ltr num"></label></details>
      ${rs.err ? `<p class="rc-err" role="alert">${esc(rs.err)}</p>` : ""}
      <button type="button" class="btn solid" id="rc-run"${rs.busy ? " disabled" : ""}>${rs.busy ? T.running : T.run}</button>
      ${demo ? `<button type="button" class="btn" id="rc-sample"${rs.busy ? " disabled" : ""}>${T.sample}</button><p class="fine">${esc(T.demoNote)}</p>` : ""}
    </div>`;
}

function history() {
  const T = L();
  const items = (rs.list || []).map((r) => {
    const ok = Math.abs(r.difference) < 0.005;
    return `<li><button type="button" class="rc-hist${rs.current && rs.current.id === r.id ? " on" : ""}" data-rc-open="${esc(r.id)}">
      <span>${esc(monthOf(r.period_end))}</span><span class="stamp ${ok ? "approved" : "rejected"} small">${ok ? "✓ " + T.ok : "! " + money(Math.abs(r.difference))}</span></button></li>`;
  }).join("");
  return `<div class="ph"><h3>${T.history}</h3></div>${items ? `<ul class="rc-list">${items}</ul>` : `<p class="empty">${rs.list ? T.none : A().t().modes.loading}</p>`}`;
}

function table(cols, rows) {
  return `<div class="scroll"><table class="rc-t"><thead><tr>${cols.map(([c, cls]) => `<th scope="col"${cls ? ` class="${cls}"` : ""}>${c}</th>`).join("")}</tr></thead>
    <tbody>${rows.join("")}</tbody></table></div>`;
}
function section(key, count, total, body, open) {
  const [h, sub] = L().sec[key];
  return `<details class="rc-sec" data-sec="${key}"${open ? " open" : ""}><summary><span class="rc-sh">${h}</span><span class="rc-count num">${count}</span>${total !== null ? `<span class="rc-total num ltr">${money(total)}</span>` : ""}</summary>
    <p class="fine">${esc(sub)}</p>${count ? body : `<p class="empty">${L().nothing}</p>`}</details>`;
}

function result() {
  const T = L(), c = rs.current, r = c.result, st = r.statement;
  const ok = Math.abs(st.difference) < 0.005, gap = Math.abs(st.bank_closing - st.book_closing);
  const C = T.cols;
  const tags = (e) => (e.previous ? ` <span class="rc-tag">${T.prevTag}</span>` : "") + (e.stale ? ` <span class="rc-tag bad">${T.staleTag}</span>` : "");
  const line = (e, last) => `<tr><td class="nw">${day(e.date)}</td><td class="nw num ltr">${esc(e.ref || "—")}</td><td><bdi>${esc(e.description)}</bdi>${tags(e)}</td><td class="amt nw num">${pos(e.amount)}</td>${last}</tr>`;

  const stRow = (k, strong) => `<tr${strong ? ' class="sub"' : ""}><th scope="row">${T.st[k]}</th><td class="amt num ltr">${acct(st[k])}</td></tr>`;
  const statement = `<table class="rc-st"><tbody>
      ${stRow("bank_closing")}${stRow("outstanding_cheques")}${stRow("deposits_in_transit")}${stRow("adjusted_bank", true)}
      <tr class="gap"><td colspan="2"></td></tr>
      ${stRow("book_closing")}${stRow("bank_debits")}${stRow("bank_credits")}${st.errors ? stRow("errors") : ""}${st.duplicates ? stRow("duplicates") : ""}${stRow("adjusted_book", true)}
      <tr class="diff ${ok ? "ok" : "bad"}"><th scope="row">${T.st.difference}</th><td class="amt num ltr">${acct(st.difference)}</td></tr></tbody></table>`;

  const review = [
    ...r.errors.map((e) => `<li>${esc(T.errLine(e.book.ref, money(Math.abs(e.book.amount)), money(Math.abs(e.bank.amount)), (e.difference > 0 ? "+" : "−") + money(Math.abs(e.difference))))}</li>`),
    ...r.duplicates.map((e) => `<li>${esc(T.dupLine(e.description, pos(e.amount), day(e.date)))}</li>`),
    ...r.outstanding.filter((e) => e.stale).map((e) => `<li>${esc(T.staleLine(e.ref || e.description, e.age))}</li>`),
    ...r.bank_only.filter((e) => e.repeat).map((e) => `<li>${esc(T.repeatLine(e.description))}</li>`),
  ];
  const bySum = (list) => list.reduce((a, e) => a + Math.abs(e.amount), 0);
  const actions = window.FC_DEMO ? `<button type="button" class="btn" id="rc-csv">${T.csv}</button>`
    : `<a class="btn" href="/api/reconciliations/${encodeURIComponent(c.id)}/xlsx" download>${T.excel}</a>`;
  const del = A().isManager() ? (rs.confirmDel
    ? `<span class="rc-confirm">${T.delAsk} <button type="button" class="btn danger" id="rc-del-yes">${T.yesDel}</button><button type="button" class="btn" id="rc-del-no">${T.cancel}</button></span>`
    : `<button type="button" class="link" id="rc-del">${T.del}</button>`) : "";

  return `<div class="rc-top">
      <div class="rc-title"><h2>${esc(T.head(monthOf(r.period.end)))}</h2>
        <span class="stamp ${ok ? "approved" : "rejected"}">${ok ? "✓ " + T.ok : "! " + T.off(money(Math.abs(st.difference)))}</span></div>
      <p class="rc-lead">${esc(ok ? T.lead(money(st.bank_closing), money(st.book_closing), money(gap))
        : T.leadOff(money(st.bank_closing), money(st.book_closing), money(gap), money(Math.abs(st.difference))))}</p>
      <p class="fine">${esc(T.ran(c.created_by, String(c.created_at).slice(0, 16), c.bank_file + " + " + c.book_file))}</p>
      <div class="rc-acts">${actions}${del}</div>
    </div>
    <div class="rc-body">
      <div class="rc-stwrap"><h3>${T.stH}</h3>${statement}<p class="fine">${esc(T.matched(r.counts.matched, r.counts.bank_rows))}</p></div>
      <div class="rc-secs">
        ${section("outstanding", r.outstanding.length, bySum(r.outstanding), table([[C.date], [C.ref], [C.desc], [C.amount, "amt"], [C.age, "amt"]],
          r.outstanding.map((e) => line(e, `<td class="amt num">${e.age}</td>`))), true)}
        ${section("in_transit", r.in_transit.length, bySum(r.in_transit), table([[C.date], [C.ref], [C.desc], [C.amount, "amt"], [C.age, "amt"]],
          r.in_transit.map((e) => line(e, `<td class="amt num">${e.age}</td>`))), true)}
        ${section("bank_only", r.bank_only.length, null, table([[C.date], [C.ref], [C.desc], [C.amount, "amt"], [C.type]],
          r.bank_only.map((e) => line(e, `<td class="nw">${T.kinds[e.kind]}${e.amount < 0 ? " ↓" : " ↑"}</td>`))), true)}
        ${section("review", review.length, null, `<ul class="rc-review">${review.join("")}</ul>`, review.length > 0)}
        ${section("cleared", r.cleared_from_previous.length, bySum(r.cleared_from_previous.map((p) => p.book)), table([[C.date], [C.ref], [C.desc], [C.amount, "amt"], [C.bankDate]],
          r.cleared_from_previous.map((p) => line(p.book, `<td class="nw">${day(p.bank.date)}</td>`))), false)}
        ${section("matched", r.matched.length, null, table([[C.date], [C.ref], [C.desc], [C.amount, "amt"], [C.how]],
          r.matched.map((p) => line(p.book, `<td class="nw">${T.how[p.how]}${p.days ? ` · ${p.days > 0 ? "+" : ""}${p.days}` : ""}</td>`))), false)}
      </div>
      <p class="notice">${esc(T.carry(r.outstanding.length, money(bySum(r.outstanding)), r.in_transit.length, money(bySum(r.in_transit))))}</p>
      <p class="fine">${esc(T.signoff)}</p>
    </div>`;
}

function render() {
  const sec = $("sec-recon");
  if (!sec || !A() || A().state.view !== "reconcile") return;
  if (rs.list === null && !rs.loading) { loadList(); }
  // keep sections the user opened or closed, unless a different month is now shown
  const same = rs.current && sec.dataset.shown === rs.current.id;
  const openSecs = same ? [...sec.querySelectorAll("details.rc-sec")].reduce((o, d) => { o[d.dataset.sec] = d.open; return o; }, {}) : {};
  sec.dataset.shown = rs.current ? rs.current.id : "";
  const balances = [$("rc-bank-bal"), $("rc-book-bal")].map((i) => (i ? i.value : ""));
  sec.innerHTML = `<div class="rc-grid">
      <div class="panel rc-main" id="rc-result">${rs.current ? result() : `<div class="rc-top"><h2>${L().nav}</h2><p class="rc-lead">${esc(L().intro)}</p></div>`}</div>
      <div class="rc-side"><div class="panel">${form()}</div><div class="panel">${history()}</div></div></div>`;
  sec.querySelectorAll("details.rc-sec").forEach((d) => { if (d.dataset.sec in openSecs) d.open = openSecs[d.dataset.sec]; });
  ["rc-bank-bal", "rc-book-bal"].forEach((id, i) => { if ($(id)) $(id).value = balances[i]; });
}

/* ---------- CSV export for the demo (the full app downloads Excel) ---------- */
function downloadCsv() {
  const T = L(), r = rs.current.result, st = r.statement, cell = (v) => { const s = String(v == null ? "" : v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const rows = [[T.stH, r.period.start + " – " + r.period.end], []];
  Object.keys(T.st).forEach((k) => rows.push([T.st[k], st[k].toFixed(2)]));
  const block = (title, list) => { rows.push([], [title], [T.cols.date, T.cols.ref, T.cols.desc, T.cols.amount]); list.forEach((e) => rows.push([e.date, e.ref, e.description, e.amount.toFixed(2)])); };
  block(T.sec.outstanding[0], r.outstanding); block(T.sec.in_transit[0], r.in_transit); block(T.sec.bank_only[0], r.bank_only);
  block(T.sec.matched[0], r.matched.map((p) => p.book));
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob(["﻿" + rows.map((x) => x.map(cell).join(",")).join("\r\n")], { type: "text/csv;charset=utf-8" }));
  a.download = `bank-reconciliation-${r.period.end.slice(0, 7)}.csv`;
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

/* ---------- events ---------- */
document.addEventListener("click", async (e) => {
  const el = e.target.closest("#sec-recon [data-rc-open], #rc-run, #rc-sample, #rc-del, #rc-del-yes, #rc-del-no, #rc-csv");
  if (!el) return;
  if (el.dataset.rcOpen) open(el.dataset.rcOpen);
  else if (el.id === "rc-run") run();
  else if (el.id === "rc-sample") { rs.busy = true; render(); try { const [bank, book] = await window.FC_DEMO.sampleFiles(); rs.busy = false; run({ bank, book }); } catch (err) { rs.busy = false; rs.err = err.message; render(); } }
  else if (el.id === "rc-del") { rs.confirmDel = true; render(); }
  else if (el.id === "rc-del-no") { rs.confirmDel = false; render(); }
  else if (el.id === "rc-del-yes") remove();
  else if (el.id === "rc-csv") downloadCsv();
});
document.addEventListener("change", (e) => {
  if (e.target.id === "rc-bank" || e.target.id === "rc-book") {
    rs.files[e.target.id === "rc-bank" ? "bank" : "book"] = e.target.files[0] || null; rs.err = ""; render();
  }
});

window.FC_RECON = { render, reset() { rs.list = null; rs.current = null; rs.files = { bank: null, book: null }; rs.err = ""; } };
})();
