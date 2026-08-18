/* Statutory norms: ONE file per installation, not per client (§5.1).
   The law is the same for everyone; a per-client copy would give five
   clients five readings of it. */
/* Norms are the law, not a setting: nothing here needs filling in before the
   program works. The screen is therefore a reference the accountant reads,
   with exactly one thing to do -- record that the law has changed from some
   future year. A bare "qüvvədə 2001" used to sit here and answer nothing; the
   article number is the fact that can actually be checked, and the year only
   appears once there are two rows to tell apart. */
let NORMS = null;

async function loadNorms(){
  NORMS = await (await fetch(`/api/rates?year=${REPORT.year}`)).json();
  const src = s => s === 'user'
    ? '<span class="tag w">əl ilə yazılıb</span>'
    : '<span class="tag d">proqramdan</span>';
  // A null rate means the category derives it from the useful life (FİM),
  // not that the value is missing. Round before testing for a fractional
  // part: 0.07*100 is 7.000000000000001 in binary floating point, which
  // printed the statutory 7% as "7.00%" next to a plain "20%".
  const pc = v => {
    if (v == null) return '<span class="zero">FİM-dən</span>';
    const n = Math.round(parseFloat(v) * 10000) / 100;
    return (Number.isInteger(n) ? n : n.toFixed(2)) + '%';
  };
  const span = (since, until) => until == null
    ? `${since}-dən indiyədək` : `${since}–${until}`;

  let rows = '';
  const methodAz = r => r.method === 'duz'
    ? '<span title="ilkin dəyər müddət üzrə bərabər bölünür">düz xətt</span>'
    : '<span class="h">azalan qalıq</span>';

  for (const r of NORMS.rates){
    // One row = the rate has never changed, so a year would be noise.
    const basis = r.changes > 1
      ? `${span(r.effective_year, r.until)} <span class="h">${esc(r.law_ref)}</span>`
      : esc(r.law_ref);
    rows += `<tr>
      <td>${esc(r.code)}</td><td>${esc(r.name_az)}</td>
      <td class="num">${r.max_rate ? pc(r.max_rate) : 'FİM üzrə'}</td>
      <td class="num">${methodAz(r)}</td>
      <td class="num">${pc(r.repair_limit)}</td>
      <td>${basis}</td><td>${src(r.source)}</td></tr>`;
    if (r.changes > 1) for (const h of r.history){
      const now = h.since === r.effective_year;
      rows += `<tr class="hist${now ? ' on' : ''}">
        <td></td><td class="h">${now ? '▸ ' : ''}${span(h.since, h.until)}
          ${h.note ? '· ' + esc(h.note) : ''}</td>
        <td class="num h">${h.max_rate ? pc(h.max_rate) : 'FİM üzrə'}</td>
        <td class="num h">${methodAz(h)}</td>
        <td class="num h">${pc(h.repair_limit)}</td>
        <td colspan="2">${h.source === 'user' ? src(h.source) : ''}</td></tr>`;
    }
  }

  let coef = NORMS.coefficients.map(c => `<tr>
      <td>${esc(c.status)}</td><td>${esc(c.name)}</td>
      <td class="num">× ${c.coefficient}</td>
      <td>${c.changes > 1 ? span(c.effective_year, null) + ' ' : ''}
          <span class="h">${esc(c.law_ref)}</span></td>
      <td>${src(c.source)}</td></tr>`).join('');

  // Figures of the law that are not per-category rates -- the write-off
  // threshold today, whatever an amendment adds tomorrow. Same append-only
  // rule, so the screen does not need to explain a second concept.
  const param = NORMS.parameters.map(p => `<tr>
      <td>${esc(p.label)}</td>
      <td class="num">${p.kind === 'pct'
          ? (parseFloat(p.value)*100).toFixed(0) + '%'
          : fmt.format(parseFloat(p.value)) + ' AZN'}</td>
      <td>${p.changes > 1 ? span(p.effective_year, p.until) + ' ' : ''}
          <span class="h">${esc(p.law_ref)}</span></td>
      <td>${src(p.source)}</td>
      <td><button class="tagbtn"
        onclick='formParam(${JSON.stringify(p)})'>dəyiş</button></td></tr>`).join('');

  // How old is this table? The number nobody can answer from the rates
  // themselves, and the one that matters most if the program outlives its
  // author: a stale figure looks exactly like a current one.
  const age = REPORT.year - parseInt(NORMS.law_reviewed.slice(0, 4), 10);

  document.getElementById('view').innerHTML = `
    <div class="note">Bu cədvəl <strong>qanunun özüdür</strong> — proqramla
      birlikdə gəlir və işə başlamaq üçün heç nə doldurmaq lazım deyil.
      ${REPORT.year} ili bu normalarla hesablanır.</div>
    <div class="note ${age >= 2 ? 'q' : ''}">Normalar Vergi Məcəlləsinin
      <strong>${esc(NORMS.law_reviewed)}</strong> tarixinə redaksiyası ilə
      tutuşdurulub.${age >= 2 ? ` <strong>O vaxtdan ${age} il keçib</strong> —
      qanun dəyişibsə, aşağıdakı düymələrlə yeni sətir əlavə edin.` : ''}</div>
    <div class="card"><div class="scroll"><table><thead><tr>
      <th>Kod</th><th>Kateqoriya</th><th class="num">Norma (maks)</th>
      <th class="num">Metod</th>
      <th class="num">Təmir limiti (m.115)</th><th>Əsas</th>
      <th>Mənbə</th></tr></thead><tbody>${rows}</tbody></table></div></div>
    <h3>Sahibkarlıq əmsalları</h3>
    <div class="card"><div class="scroll"><table><thead><tr>
      <th>Kod</th><th>Status</th><th class="num">Əmsal</th>
      <th>Əsas</th><th>Mənbə</th></tr></thead>
      <tbody>${coef}</tbody></table></div></div>
    <h3>Qanunun digər rəqəmləri</h3>
    <div class="card"><div class="scroll"><table><thead><tr>
      <th>Göstərici</th><th class="num">Dəyər</th><th>Əsas</th>
      <th>Mənbə</th><th></th></tr></thead>
      <tbody>${param}</tbody></table></div></div>
    <div style="margin:14px 0">
      <button class="btn" onclick="formNewNorm()">Qanun dəyişdi — yeni norma</button>
      <button class="btn" onclick="formNewCoef()">Yeni əmsal</button></div>
    <div class="note q">Dəyişiklik <strong>bütün müştərilərə təsir edir</strong> —
      qanun hamı üçün eynidir. Yeni norma yalnız <strong>gələcək ildən</strong>
      qüvvəyə minir: keçmiş illər təqdim edilmiş bəyannamələrdir.<br>
      Proqramın özündə norma səhv yazılıbsa, bu, proqramın yeni buraxılışı ilə
      düzəldilir — burada deyil.</div>`;
}

/* Only one direction is offered: forward. The year field starts at the first
   year that is not already spoken for, so the past is not reachable by
   mis-typing, and the engine refuses it as well (mutate.set_rate_row). */
function formNewNorm(){
  const first = NORMS.rates[0];
  const floorOf = r => Math.max(r.effective_year + 1, REPORT.year);
  openModal('Yeni norma — qanun dəyişib',
    fld('category','Kateqoriya',{type:'select',req:true,options:catOptions(first.code)}) +
    fld('effective_year','Hansı ildən qüvvəyə minir',
        {type:'number',value:floorOf(first),min:floorOf(first),req:true,
         hint:'Keçmiş illər dəyişmir — yalnız bu ildən sonrakı hesablamalar.'}) +
    `<div class="row2">
      ${fld('max_rate','Amortizasiya norması (maks)',{placeholder:'məs. 7',
            hint:'Faizlə. Boş = dəyişmir.'})}
      ${fld('repair_limit','Təmir limiti (m.115)',{placeholder:'məs. 2',
            hint:'Faizlə. Boş = dəyişmir.'})}</div>` +
    fld('note','Əsas',{placeholder:'məs. VM m.114.3.1 dəyişikliyi',
        hint:'Sonradan bu sətrin niyə yarandığını izah edəcək.'}),
    d => post('rate.set', d));
}

function formParam(p){
  const floor = Math.max(p.effective_year + 1, REPORT.year);
  openModal(p.label,
    `<input type="hidden" name="key" value="${p.key}">` +
    `<div class="row2">
      ${fld('value', p.kind === 'pct' ? 'Yeni dəyər (%)' : 'Yeni dəyər (AZN)',
            {req:true, value: p.kind === 'pct'
              ? (parseFloat(p.value)*100).toFixed(0) : parseFloat(p.value)})}
      ${fld('effective_year','Hansı ildən',{type:'number',value:floor,min:floor,req:true})}
     </div>` +
    fld('note','Əsas',{placeholder:'məs. VM m.114.8 dəyişikliyi'}),
    d => post('parameter.set', d));
}

function formNewCoef(){
  const opts = NORMS.coefficients.map(c =>
    `<option value="${c.status}">${esc(c.name)}</option>`).join('');
  const floor = Math.max(...NORMS.coefficients.map(c => c.effective_year)) + 1;
  openModal('Yeni sahibkarlıq əmsalı',
    fld('status','Status',{type:'select',req:true,options:opts}) +
    `<div class="row2">
      ${fld('coefficient','Əmsal',{req:true,placeholder:'məs. 2 və ya 1.5'})}
      ${fld('effective_year','Hansı ildən',{type:'number',
            value:Math.max(floor, REPORT.year),min:floor,req:true})}
     </div>` + fld('note','Əsas',{placeholder:'məs. VM m.114.3-1'}),
    d => post('coefficient.set', d));
}

/* ---------- rates across years ----------
   Every other report answers for one year, and a wrong rate almost never
   looks wrong inside one year -- it looks wrong beside the years around it.
   20, 20, 20, 18 is the whole point: nothing on the 18% screen is illegal,
   the norm was 20% throughout, and only the row shows that a decision was
   taken in one year and not the others.

   The range is the user's: pick 2023-2026 and read four columns. */
let MX = null, MXFROM = 0, MXTO = 0;

async function loadRateMatrix(){
  const q = `client=${encodeURIComponent(REPORT.slug)}`
    + (MXFROM ? `&from=${MXFROM}` : '') + (MXTO ? `&to=${MXTO}` : '');
  const r = await fetch(`/api/rate-matrix?${q}`);
  const data = await r.json();
  if (!r.ok) return fail(data.error || 'dərəcə cədvəli alınmadı');
  MX = data;
  document.getElementById('view').innerHTML = viewRateMatrix(data);
}

function mxRange(from, to){ MXFROM = +from; MXTO = +to; loadRateMatrix(); }

function mxCell(c){
  // A year that would not compute is the loudest thing this table can say:
  // it is shown in place, not swallowed, and not left looking like a blank.
  if (!c.computed) return `<td class="y bad" title="${esc(c.note)}">
      <div class="r">hesablanmadı</div></td>`;
  if (!c.on_books) return `<td class="y off">—</td>`;
  // A straight-line cell states a term. Printing 1/term as a percentage
  // beside the others would read as a rate on a residual, and the year the
  // METHOD moved -- 10% declining in 2025, ten years straight from 2026 --
  // would be the one break this table failed to show (§5.6-bis).
  if (c.method === 'duz')
    return `<td class="y${c.rate_changed ? ' chg' : ''}"
        title="düz xətt: ilkin dəyər müddət üzrə bölünür">
      <div class="r">${c.per_card ? 'FİM üzrə' : c.term_years + ' il'}</div>
      <div class="u">düz xətt${c.cards ? ' · ' + c.cards + ' kart' : ''}</div></td>`;
  const marks = [];
  if (c.source === 'asset') marks.push('obyekt üzrə');
  else if (c.source === 'category') marks.push('seçilib');
  if (c.below_statutory) marks.push('m.114.3-dən aşağı');
  if (c.coefficient_used) marks.push(`əmsal ×${c.coefficient}`);
  const under = c.applied === c.statutory
    ? (c.cards ? `${c.cards} kart` : '')
    : `norma ${pct(c.statutory)}`;
  return `<td class="y${c.rate_changed ? ' chg' : ''}"
      title="norma ${pct(c.statutory)} × ${c.coefficient} = hədd ${pct(c.ceiling)}">
    <div class="r">${pct(c.applied)}</div>
    <div class="u">${esc(under)}${marks.length ? '<br>' + esc(marks.join(' · ')) : ''}</div></td>`;
}

function viewRateMatrix(d){
  if (!d.rows.length) return `<div class="note">Bu illərdə hesablanmış
    kateqoriya yoxdur.</div>`;
  const opts = (sel) => d.all_years.map(y =>
    `<option value="${y}"${y === sel ? ' selected' : ''}>${y}</option>`).join('');
  const first = d.years[0], last = d.years[d.years.length - 1];

  let body = '';
  for (const s of d.rows){
    const flag = s.rate_changed
      ? '<span class="flag w">dərəcə dəyişib</span>'
      : (s.law_changed ? '<span class="flag">norma dəyişib</span>' : '');
    body += `<tr class="head"><td>${esc(s.name)}
        <span class="h">${esc(s.law_ref)}</span>${flag}</td>
      ${s.cells.map(mxCell).join('')}</tr>`;
    // Only assets that were ever pulled off their category rate get a line:
    // on 240 identical cards the one that differs is the answer, and the
    // other 239 would bury it.
    for (const a of s.assets){
      body += `<tr class="sub"><td>${esc(a.subtitle || a.name)}
          <span class="h">${esc(a.subtitle ? a.name : '')}</span>
          ${a.rate_changed ? '<span class="flag w">dəyişib</span>' : ''}</td>
        ${a.cells.map(mxCell).join('')}</tr>`;
    }
  }

  const failed = Object.keys(d.failed).length
    ? `<div class="note"><strong>Hesablanmayan illər:</strong> ` +
      Object.entries(d.failed).map(([y, e]) =>
        `${y} — ${esc(e)}`).join('<br>') + `</div>`
    : '';

  return `
    <div class="rng">
      <span class="hint">İllər:</span>
      <select onchange="mxRange(this.value, ${last})">${opts(first)}</select>
      <span class="hint">—</span>
      <select onchange="mxRange(${first}, this.value)">${opts(last)}</select>
      <span class="hint">Sətri soldan sağa oxuyun: rəng dəyişən ili göstərir.</span>
    </div>
    ${failed}
    <div class="card"><div class="scroll"><table class="mx"><thead><tr>
      <th>Kateqoriya / obyekt</th>
      ${d.years.map(y => `<th class="num" style="text-align:center">${y}${
        d.closed.includes(y) ? ' <span class="h">bağlı</span>' : ''}</th>`).join('')}
    </tr></thead><tbody>${body}</tbody></table></div></div>
    <div class="note q">Burada <strong>tətbiq edilmiş</strong> dərəcələr var —
      qanunun norması deyil. Norma dəyişməsə də dərəcə dəyişə bilər: m.114.3
      yuxarı həddir, ondan az hesablamaq olar (§5.2). Ona görə sətirdəki
      fərq çox vaxt qərardır, səhv deyil — amma hər ikisi burada görünür.</div>`;
}
