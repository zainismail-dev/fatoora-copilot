// Generates fictional bilingual tax-invoice PDFs for testing Fatoora Copilot.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const OUT = path.join(__dirname, '..', 'samples');
fs.mkdirSync(OUT, { recursive: true });

const BUYER = { ar: 'شركة الريادة التجارية', en: 'Al Riyada Trading Co.', vat: '300400500600003', city: 'Riyadh / الرياض' };
const r2 = n => Math.round(n * 100) / 100;
const fmt = n => n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const invoices = [
  { file: '01-sahab-clean.pdf', note: 'Clean invoice', sup: { ar: 'شركة سحاب للحلول التقنية', en: 'Sahab Tech Solutions', vat: '300512398700003', city: 'Riyadh / الرياض' }, no: 'INV-2701', date: '2026-11-12',
    lines: [['رخص برمجيات سنوية', 'Annual software licences', 10, 1800], ['خدمات دعم فني', 'Technical support', 12, 450]] },
  { file: '02-nada-clean.pdf', note: 'Clean invoice', sup: { ar: 'مؤسسة الندى للقرطاسية', en: 'Al Nada Stationery', vat: '310228745600003', city: 'Riyadh / الرياض' }, no: 'ND-5602', date: '2026-11-12',
    lines: [['ورق طباعة A4', 'A4 printing paper', 40, 28], ['أحبار طابعات', 'Printer toner', 6, 310]] },
  { file: '03-rawasi-clean.pdf', note: 'Clean invoice', sup: { ar: 'شركة رواسي للخدمات اللوجستية', en: 'Rawasi Logistics', vat: '300987654300003', city: 'Dammam / الدمام' }, no: 'RW-1004', date: '2026-11-11',
    lines: [['شحن بضائع الرياض–جدة', 'Freight, Riyadh to Jeddah', 4, 3200], ['تخزين شهري', 'Monthly warehousing', 1, 5400]] },
  { file: '04-madar-large-amount.pdf', note: 'Large amount (over SAR 50,000)', sup: { ar: 'شركة المدار للصيانة', en: 'Al Madar Maintenance', vat: '300765432100003', city: 'Riyadh / الرياض' }, no: 'MD-1201', date: '2026-11-12',
    lines: [['عقد صيانة سنوي للتكييف', 'Annual AC maintenance contract', 1, 48000], ['قطع غيار', 'Spare parts', 1, 10500]] },
  { file: '05-waha-wrong-vat-rate.pdf', note: 'VAT charged at 14% instead of 15%', sup: { ar: 'مطابع الواحة', en: 'Al Waha Printing', vat: '302345678900003', city: 'Jeddah / جدة' }, no: 'WP-3401', date: '2026-11-11', vatRate: 0.14,
    lines: [['طباعة كتيبات', 'Brochure printing', 500, 6.4], ['بطاقات عمل', 'Business cards', 10, 160]] },
  { file: '06-lamsa-invalid-vat-number.pdf', note: 'Supplier VAT number has 14 digits', sup: { ar: 'مؤسسة لمسة للديكور', en: 'Lamsa Decor', vat: '31045678901234', city: 'Khobar / الخبر' }, no: 'LD-0051', date: '2026-11-10',
    lines: [['أعمال ديكور داخلي', 'Interior fit-out', 1, 7200], ['أثاث مكتبي', 'Office furniture', 4, 650]] },
  { file: '07-ufuq-total-mismatch.pdf', note: 'Total is SAR 100 higher than subtotal + VAT', sup: { ar: 'شركة أفق للاتصالات', en: 'Ufuq Telecom', vat: '310987123400003', city: 'Riyadh / الرياض' }, no: 'UF-78010', date: '2026-11-12', totalAdj: 100,
    lines: [['باقة إنترنت أعمال', 'Business internet plan', 1, 4200], ['خطوط جوال الموظفين', 'Staff mobile lines', 25, 115]] },
  { file: '08-cloudline-foreign-currency.pdf', note: 'Invoice in USD with no VAT', sup: { ar: 'كلاود لاين للبرمجيات', en: 'Cloudline Software', vat: '300111222300003', city: 'Dubai / دبي' }, no: 'CL-1210', date: '2026-11-12', cur: 'USD', vatRate: 0,
    lines: [['استضافة سحابية', 'Cloud hosting', 1, 950], ['خطة دعم', 'Support plan', 1, 250]] }
];

function html(x) {
  const cur = x.cur || 'SAR';
  const rate = x.vatRate === undefined ? 0.15 : x.vatRate;
  const sub = r2(x.lines.reduce((a, l) => a + l[2] * l[3], 0));
  const vat = r2(sub * rate);
  const total = r2(sub + vat + (x.totalAdj || 0));
  const rows = x.lines.map(l => `<tr><td>${l[0]}<br><small>${l[1]}</small></td><td class="n">${l[2]}</td><td class="n">${fmt(l[3])}</td><td class="n">${fmt(r2(l[2] * l[3]))}</td></tr>`).join('');
  return `<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>
  @page{size:A4;margin:18mm}
  body{font-family:"DejaVu Sans",sans-serif;color:#1b2b27;font-size:11pt}
  .top{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:3px solid #1b2b27;padding-bottom:10px}
  h1{margin:0;font-size:22pt} h1 small{display:block;font-size:11pt;color:#5e6f69;font-weight:normal}
  .seller{text-align:left;direction:ltr;font-size:10pt}
  .seller b{font-size:12pt}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:16px 0;font-size:10pt}
  .box{border:1px solid #c9d3cc;padding:10px}
  .box b{display:block;color:#5e6f69;font-weight:normal;font-size:9pt}
  table{width:100%;border-collapse:collapse;margin-top:8px}
  th{border-bottom:2px solid #1b2b27;text-align:right;padding:6px;font-size:9.5pt;color:#5e6f69}
  td{border-bottom:1px solid #dce3de;padding:7px 6px;vertical-align:top}
  td small{color:#5e6f69}
  .n{text-align:left;direction:ltr;white-space:nowrap}
  .tot{margin-top:14px;width:55%;margin-inline-start:auto}
  .tot td{border:0;padding:4px 6px}
  .tot .g td{border-top:2px solid #1b2b27;font-weight:bold;font-size:13pt;padding-top:8px}
  .foot{margin-top:28px;font-size:8.5pt;color:#5e6f69;border-top:1px solid #dce3de;padding-top:8px}
  </style></head><body>
  <div class="top"><h1>فاتورة ضريبية<small>Tax Invoice</small></h1>
    <div class="seller"><b>${x.sup.en}</b><br>${x.sup.ar}<br>${x.sup.city}<br>VAT No. / الرقم الضريبي: ${x.sup.vat}</div></div>
  <div class="grid">
    <div class="box"><b>رقم الفاتورة / Invoice No.</b>${x.no}<br><b style="margin-top:6px">تاريخ الإصدار / Issue date</b>${x.date}<br><b style="margin-top:6px">العملة / Currency</b>${cur}</div>
    <div class="box"><b>المشتري / Buyer</b>${BUYER.ar}<br>${BUYER.en}<br>${BUYER.city}<br>VAT No. / الرقم الضريبي: ${BUYER.vat}</div>
  </div>
  <table><thead><tr><th>البند / Item</th><th class="n">الكمية / Qty</th><th class="n">سعر الوحدة / Unit price</th><th class="n">المبلغ / Amount</th></tr></thead><tbody>${rows}</tbody></table>
  <table class="tot">
    <tr><td>المجموع قبل الضريبة / Subtotal</td><td class="n">${fmt(sub)} ${cur}</td></tr>
    <tr><td>ضريبة القيمة المضافة / VAT ${Math.round(rate * 100)}%</td><td class="n">${fmt(vat)} ${cur}</td></tr>
    <tr class="g"><td>الإجمالي المستحق / Total due</td><td class="n">${fmt(total)} ${cur}</td></tr>
  </table>
  <div class="foot">بيانات تجريبية لأغراض الاختبار فقط · Fictional test invoice for Fatoora Copilot demos. Not a real company or a valid ZATCA e-invoice.</div>
  </body></html>`;
}

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage();
  const manifest = [];
  for (const x of invoices) {
    await p.setContent(html(x), { waitUntil: 'load' });
    await p.pdf({ path: path.join(OUT, x.file), format: 'A4', printBackground: true });
    manifest.push(`${x.file}  ${x.note}`);
  }
  fs.writeFileSync(path.join(OUT, 'README.txt'), 'Fictional test invoices for Fatoora Copilot\n\n' + manifest.join('\n') + '\n\nDuplicate test: send 01-sahab-clean.pdf a second time.\n');
  await b.close();
  console.log(manifest.join('\n'));
})();
