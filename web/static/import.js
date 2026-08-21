/* ---- bulk import ----------------------------------------------------
   Designed around what a bookkeeper sees, not around the schema.

   The first version asked "which column is the name?" with a grid of field
   dropdowns -- that is the developer's model. A bookkeeper looks at the
   sheet and says "this column here is the name", so the mapping step now
   shows THEIR rows with a dropdown sitting on top of each column.

   And when every required column is recognised, the step is skipped
   entirely: a decision nobody needs to make should not be shown. --------- */
let IMP = null;

const IMP_LABELS = {
  inv_no:'İnv.№', name:'Adı', category:'Kateqoriya', in_date:'Alış tarixi',
  cost:'İlkin dəyər', opening_residual:'Qalıq dəyər',
  counterparty:'Kontragent', e_qaime:'E-qaimə №', serial_no:'Seriya №',
  group:'Növ', note:'Qeyd'};
const IMP_REQUIRED = ['name','category'];

function formImport(){
  IMP = {step:1, header:[], rows:[], map:{}, catmap:{}, year:REPORT.year,
         fields:[], grid:null, back:null};
  impRender();
}

function impBox(step, body, foot, back, sheet){
  const steps = ['Cədvəli gətirin','Sütunları yoxlayın','Baxış və idxal'];
  document.getElementById('mtitle').textContent =
    `ƏV idxalı · ${step}/3 · ${steps[step-1]}`;
  document.getElementById('mbody').innerHTML = body;
  document.getElementById('ferr').style.display = 'none';
  document.getElementById('msubmit').textContent = foot;
  const cancel = document.querySelector('#mform .foot .ghost');
  cancel.textContent = back ? '← Geri' : 'İmtina';
  cancel.onclick = back ? back : closeModal;
  const box = document.querySelector('#modal .box');
  box.classList.toggle('wide', step > 1);
  box.classList.toggle('sheet', !!sheet);      // the paste grid: ten columns
  document.getElementById('modal').classList.add('open');
}

const STAY = '__stay__';
const impCats = () => cardCats();

/* ---- step 1: get the sheet in ---- */
function impRender(){
  impBox(1, `
    <p style="margin:0 0 14px">Müştərinin cədvəlini olduğu kimi gətirin —
      sütunların adı və sırası vacib deyil, proqram özü tanıyacaq.</p>
    <div class="fld"><label>Excel-də sahəni seçin → <kbd>Ctrl+C</kbd> →
      burada <kbd>Ctrl+V</kbd></label>
      <textarea class="paste" id="pastebox"
        placeholder="Buraya yapışdırın…"></textarea></div>
    <div class="fld"><label>və ya faylı seçin</label>
      <input type="file" id="impfile" accept=".xlsx,.csv,.tsv,.txt"></div>
    <div class="h">Birinci sətir sütun adları olmalıdır.
      Müştəridə cədvəl yoxdursa —
      <a href="/api/import-template">hazır şablonu yükləyib</a> ona göndərin.</div>
    <hr style="border:0;border-top:1px solid var(--line);margin:16px 0">
    <div class="fld"><label>Sütunlar tanınmırsa</label>
      <div class="h" style="margin:0 0 8px">Cədvəli bütöv gətirmək əvəzinə
        hazır sütunları <strong>bir-bir doldurun</strong>: Excel-də bir sütunu
        seçib köçürün və buradakı müvafiq sütuna yapışdırın. Uyğunlaşdırma
        addımı olmur — hara yapışdırdınız, ora düşür.</div>
      <button type="button" class="btn" onclick="impGrid()"
        >⌗ Sütun-sütun doldurun</button></div>`,
    'Davam et');
  MSUBMIT = async () => {
    const f = document.getElementById('impfile').files[0];
    let payload;
    if (f){
      const b64 = await new Promise(res => {
        const fr = new FileReader();
        fr.onload = () => res(fr.result.split(',')[1]);
        fr.readAsDataURL(f);
      });
      payload = {name:f.name, b64};
    } else {
      const text = document.getElementById('pastebox').value;
      if (text.split(/\r?\n/).filter(l => l.trim()).length < 2)
        throw new Error('Ən azı başlıq sətri və bir ƏV sətri lazımdır');
      payload = {name:'paste.tsv', b64: btoa(unescape(encodeURIComponent(text)))};
    }
    const r = await fetch('/api/parse-file', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error);
    IMP.header = j.header; IMP.rows = j.rows; IMP.map = j.guess; IMP.fields = j.fields;
    impAfterParse();
    throw new Error(STAY);
  };
}

/* Skip the mapping step when there is nothing to decide. */
function impAfterParse(){
  const ok = IMP_REQUIRED.every(f => IMP.map[f] != null);
  IMP.catmap = {};
  const unknown = impUnknownCats();
  if (ok && !unknown.length){ impPreview(); } else { impColumns(); }
}

function impUnknownCats(){
  const ci = IMP.map.category;
  if (ci == null) return [];
  const known = new Set(impCats().map(c => c.code));
  const seen = new Map();
  for (const r of IMP.rows){
    const v = (r[ci] || '').trim();
    if (!v || known.has(v)) continue;
    seen.set(v, (seen.get(v) || 0) + 1);
  }
  return [...seen.entries()];
}

/* ---- step 2: their rows, with a dropdown over each column ---- */
function impColumns(){
  IMP.step = 2;
  const opts = i => `<select onchange="impSetCol(${i}, this.value)">
      <option value="">— istifadə olunmur —</option>
      ${IMP.fields.map(f => `<option value="${f}" ${IMP.map[f] === i ? 'selected' : ''}
        >${IMP_LABELS[f]}${IMP_REQUIRED.includes(f) ? ' *' : ''}</option>`).join('')}
    </select>`;
  const missing = IMP_REQUIRED.filter(f => IMP.map[f] == null);
  const sample = IMP.rows.slice(0, 5);
  const table = `<div class="scroll imp" style="max-height:34vh"><table>
    <thead>
      <tr>${IMP.header.map((h,i) => `<th style="min-width:150px">${opts(i)}</th>`).join('')}</tr>
      <tr>${IMP.header.map(h => `<th style="font-weight:400;text-transform:none;
        color:var(--muted)">${esc(h) || '(adsız sütun)'}</th>`).join('')}</tr>
    </thead>
    <tbody>${sample.map(r => `<tr>${IMP.header.map((_,i) =>
      `<td>${esc(r[i] ?? '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;

  const unknown = impUnknownCats();
  const cats = unknown.length ? `<h3>Kateqoriyalar tanınmadı</h3>
    <p class="h" style="margin:0 0 8px">Cədvəldəki bu dəyərlərin hansı
      kateqoriyaya uyğun gəldiyini göstərin.</p>
    <div class="imp-grid">${unknown.map(([v,n]) => `<div class="fld">
      <label>«${esc(v)}» — ${n} sətir</label>
      <select data-cat="${esc(v)}" required>
        <option value="">— seçin —</option>
        ${impCats().map(c =>
          `<option value="${c.code}">${esc(c.name_az)}</option>`).join('')}</select>
      </div>`).join('')}</div>` : '';

  impBox(2, `
    <p style="margin:0 0 12px">${IMP.rows.length} sətir oxundu.
      ${missing.length
        ? `<strong style="color:var(--neg)">Hər sütunun üstündə onun nə olduğunu
           seçin.</strong> Tanınmayan sütunları «istifadə olunmur» kimi buraxın.`
        : 'Proqram sütunları özü tanıdı — yoxlayın və davam edin.'}
      <br><span class="h">* — mütləq lazımdır</span></p>
    ${table}${cats}
    <div class="fld" style="max-width:260px;margin-top:14px">
      <label>«Qalıq dəyər» hansı ilin əvvəlinə aiddir</label>
      <input type="number" id="impyear" value="${IMP.year}"></div>`,
    'Baxış', () => { IMP.step = 1; impRender(); });

  MSUBMIT = async () => {
    const unset = [];
    document.querySelectorAll('#mbody select[data-cat]').forEach(el => {
      if (!el.value) unset.push(el.dataset.cat);
      IMP.catmap[el.dataset.cat] = el.value;
    });
    if (unset.length)
      throw new Error('Kateqoriya seçilməyib: ' + unset.join(', '));
    IMP.year = +document.getElementById('impyear').value;
    const miss = IMP_REQUIRED.filter(f => IMP.map[f] == null);
    if (miss.length)
      throw new Error('Seçilməyib: ' + miss.map(f => IMP_LABELS[f]).join(', '));
    await impPreview();
    throw new Error(STAY);
  };
}

/* One field belongs to one column: assigning it elsewhere frees the old one. */
function impSetCol(index, field){
  for (const f of Object.keys(IMP.map)) if (IMP.map[f] === index) delete IMP.map[f];
  if (field) IMP.map[field] = index;
  impColumns();
}

const impPayload = () => IMP.rows.map(r => {
  const o = {};
  for (const f of Object.keys(IMP.map)) o[f] = (r[IMP.map[f]] ?? '').toString().trim();
  o.category = IMP.catmap[o.category] || o.category;
  return o;
});

/* ---- step 3: plain-language check ---- */
/* ---- alternative to step 2: fixed columns, filled one paste at a time ----

   The mapping step exists because a client's sheet has whatever columns it
   has. When that guessing goes wrong it is genuinely hard to recover from --
   so this offers the other direction: the columns are ours and fixed, and the
   user says where a column of values belongs by pasting it there. Nothing to
   map, nothing to guess.

   Excel puts TSV on the clipboard, so a rectangular selection pastes as a
   rectangle here. The whole grid is just a way of building the same `rows`
   payload the file import already sends, which is why it can jump straight
   to the shared preview. */
/* Declared once -- field, heading, width -- and the header, the cells and
   the totals row are all drawn from this list. Position was already lying
   here: the headings were hand-written and stopped at seven while the payload
   had nine, so `table-layout:fixed`, which takes its columns from the first
   row, laid `e_qaime` and `serial_no` out at zero width. They were in the
   data and invisible on screen. Same fix as the annual table (§11.3).

   The list must offer everything «+ Yeni ƏV» offers, minus `say`: a count is
   a field of that form, not a column of data (§4), and a row here IS one
   card. A test compares the two and fails when they drift (§11.2). */
const GRID_COLS = [
  {f:'category',         t:'Kat.',              w: 84},
  {f:'inv_no',           t:'İnv.№',             w:100},
  {f:'name',             t:'Adı *',             w:180},
  {f:'in_date',          t:'Alış tarixi',       w:100, ph:'GG.AA.YYYY'},
  // The two money columns sit TOGETHER, and that adjacency is load-bearing.
  // «FİM (il)» used to stand between them, which quietly broke the ordinary
  // way people paste: an Excel selection of cost+residual is one rectangle,
  // and pasting it at «İlkin dəyər» dropped the residual into FİM while
  // «Qalıq» stayed empty. The row still imported -- with a past purchase date
  // it is a valid "new" row -- and came out reading «tam amortizasiya
  // olunub», the one silent wrong answer §2.1 rules out.
  {f:'cost',             t:'İlkin dəyər',       w:118, num:true},
  // The heading is uppercased by the stylesheet, so it needs the room its
  // own lower-case text does not suggest.
  {f:'opening_residual', t:() => `Qalıq (${IMP.year} əvv.)`,
                                                w:158, num:true},
  // Only a QMA with a known term uses it (m.114.3.6), and for everything else
  // it stays empty -- but it must be HERE, because the grid and the form are
  // one and the same act of creating a card (§11.2).
  {f:'useful_life',      t:'FİM (il)',          w: 84},
  {f:'counterparty',     t:'Kontragent',        w:140},
  {f:'e_qaime',          t:'E-qaimə №',         w:120},
  {f:'serial_no',        t:'Seriya № / VIN',    w:140},
  // A NAME here, not an id: this column is pasted out of the client's own
  // sheet. The import matches it against groups.tsv case-insensitively and
  // creates the ones that are new (§13.1).
  {f:'group',            t:'Növ',               w:130},
  {f:'note',             t:'Qeyd',              w:130},
];
const GRID_DEL = 36;                     // the row-delete column, no field
const gcol = f => GRID_COLS.findIndex(c => c.f === f);
const gridRow = () => GRID_COLS.map(() => '');
const GRID_WIDTH = GRID_COLS.reduce((w, c) => w + c.w, GRID_DEL);

function impGrid(rows){
  IMP.step = 2; IMP.back = impGrid;
  const data = rows || IMP.grid || [];
  while (data.length < 15) data.push(gridRow());
  IMP.grid = data;
  // Every edit rebuilds the grid, and deleting a row is now an ordinary edit.
  // Without keeping the scroll, clearing four bad rows would send the sheet
  // back to line one four times.
  const open = document.getElementById('gridwrap');
  const scroll = open ? open.scrollTop : 0;

  // The category <select> used to have no blank option, so an untouched cell
  // silently held whatever category impCats() lists first -- a paste that
  // never touched this column (or forgot the "Bütün sətirlərin kateqoriyası"
  // dropdown above) landed real rows on that category with nothing on screen
  // to say so. A blank first option makes "not chosen yet" a visible state
  // instead of an invisible default (§2.1), and impGridTotals() below flags
  // any filled row that is still sitting on it.
  const cell = (r, c) => GRID_COLS[c].f === 'category'
    ? `<select data-r="${r}" data-c="${c}">
        <option value="" ${!data[r][c] ? 'selected' : ''}>— seçin —</option>${
        impCats().map(k => `<option value="${k.code}"
          ${data[r][c] === k.code ? 'selected' : ''}>${esc(k.code)}</option>`).join('')
      }</select>`
    : `<input data-r="${r}" data-c="${c}" value="${val(data[r][c])}"
        ${GRID_COLS[c].ph ? `placeholder="${GRID_COLS[c].ph}"` : ''}>`;

  impBox(2, `
    <div class="note">Excel-də <strong>bir sütunu</strong> seçin →
      <kbd>Ctrl+C</kbd> → burada həmin sütunun birinci xanasına
      <kbd>Ctrl+V</kbd>. Bir neçə sütunu birdən də yapışdıra bilərsiniz.
      Boş sətirlər nəzərə alınmır; artıq düşən sətri sağdakı
      <strong>×</strong> ilə silin.</div>
    <div style="display:flex;gap:10px;align-items:flex-end;margin-bottom:10px">
      <div class="fld" style="margin:0">
        <label>Bütün sətirlərin kateqoriyası</label>
        <select onchange="impGridAllCats(this.value)">
          <option value="">— dəyişmə —</option>
          ${impCats().map(k => `<option value="${k.code}">${esc(k.code)} · ${esc(k.name_az)}</option>`).join('')}
        </select></div>
      <div class="fld" style="margin:0;max-width:150px">
        <label>Qalıq hansı ilin əvvəlinə</label>
        <input id="gridyear" type="number" value="${IMP.year}"
          onchange="IMP.year = parseInt(this.value,10) || IMP.year"></div>
      <button type="button" class="ghost" style="padding:9px 14px"
        onclick="impGridAdd(20)">+ 20 sətir</button>
    </div>
    <div class="scroll imp grid" style="max-height:40vh" id="gridwrap"
      onpaste="return impGridPaste(event)" oninput="impGridTotals()">
      <table style="min-width:${GRID_WIDTH}px"><thead><tr>${
        GRID_COLS.map(c => `<th style="width:${c.w}px"${c.num ? ' class="num"' : ''}
          >${typeof c.t === 'function' ? c.t() : c.t}</th>`).join('')
      }<th style="width:${GRID_DEL}px"></th></tr></thead>
      <tbody id="gridbody">${data.map((row, r) => `<tr>${
        GRID_COLS.map((_, c) => `<td>${cell(r, c)}</td>`).join('')
      }<td class="del"><button type="button" class="rowdel" title="Sətri sil"
          onclick="impGridDel(${r})">×</button></td></tr>`).join('')}</tbody>
      ${impGridFoot()}</table></div>
    <div class="h">«Adı» məcburidir. «İlkin dəyər» olmadan 500/5% testinin
      yalnız məbləğ hissəsi işləyəcək — bilirsinizsə, yazın.<br>
      Cəmi sətri Excel-dəki cəmi ilə tutuşdurun — sütun düz düşübsə,
      rəqəmlər üst-üstə düşməlidir.</div>`,
    'Baxış', () => impRender(), true);
  const wrap = document.getElementById('gridwrap');
  if (wrap) wrap.scrollTop = scroll;
  impGridTotals();

  MSUBMIT = async () => {
    impGridRead();
    if (!IMP.grid.some(impGridFilled))
      throw new Error('Heç bir sətir doldurulmayıb');
    IMP.rows = IMP.grid.filter(impGridFilled);
    // Refused here, not just flagged in the totals row: a category can be a
    // legal-looking value (the first real option) sitting there because
    // nobody chose it, and letting that reach the preview is the same silent
    // wrong answer §2.1 rules out elsewhere in this file.
    const noCat = IMP.rows.filter(r => !String(r[gcol('category')] || '').trim()).length;
    if (noCat) throw new Error(`${noCat} sətirdə kateqoriya seçilməyib — `
      + `qırmızı işarəli xanalarda seçin, ya da yuxarıda "Bütün sətirlərin `
      + `kateqoriyası" ilə hamısına tətbiq edin.`);
    IMP.map = {}; GRID_COLS.forEach((c, i) => { IMP.map[c.f] = i; });
    IMP.catmap = {};
    await impPreview();
    throw new Error(STAY);
  };
}

/* A pasted block routinely brings a few lines too many -- an Excel selection
   is a rectangle, and the rectangle is easy to draw one row too tall. Nothing
   has been written yet, so the row goes out at once: no confirmation, no
   undo, and no need for either. */
function impGridDel(r){
  impGridRead();
  IMP.grid.splice(r, 1);
  impGrid(IMP.grid);
}

/* The totals row follows the same column list as the header: a total under
   every money column, the rest merged into the gaps. A hand-counted colspan
   is how the headings went out of step with the data in the first place. */
function impGridFoot(){
  const parts = [];
  for (const c of GRID_COLS.concat([{f:'del'}])){
    if (c.num) parts.push({f: c.f});
    else if (parts.length && parts[parts.length - 1].span) parts[parts.length - 1].span++;
    else parts.push({span: 1});
  }
  const gaps = parts.filter(p => p.span);
  if (gaps.length) gaps[0].id = 'gridcount';
  if (gaps.length > 1) gaps[gaps.length - 1].id = 'gridbad';
  return `<tfoot><tr>${parts.map(p => p.span
    ? `<td colspan="${p.span}"${p.id ? ` id="${p.id}"` : ''}></td>`
    : `<td class="num" id="gridsum-${p.f}"></td>`).join('')}</tr></tfoot>`;
}

/* The point of pasting a whole column is that you already know its total from
   Excel. Showing ours under the column turns "did it land right?" into a
   glance instead of a scroll.

   These rules mirror mutate._normalise_number deliberately, including its
   refusal to guess at "1,234". The engine stays the authority -- the preview
   step re-parses everything server-side before anything is written -- so if
   the two ever disagree, the cell is marked here rather than quietly dropped
   from the sum, which is the only way a wrong total could look right. */
function impGridNum(raw){
  let s = String(raw == null ? '' : raw)
    .replace(/[\s  '`]/g, '').replace(/AZN|azn|₼/g, '');
  if (!s) return null;                       // empty is not an error
  const neg = s.startsWith('-');
  s = s.replace(/^[+-]/, '');
  const commas = (s.match(/,/g) || []).length;
  const dots = (s.match(/\./g) || []).length;
  if (commas && dots){
    s = s.lastIndexOf(',') > s.lastIndexOf('.')
      ? s.replace(/\./g, '').replace(',', '.')
      : s.replace(/,/g, '');
  } else if (commas > 1){
    s = s.replace(/,/g, '');
  } else if (commas === 1){
    const head = s.slice(0, s.indexOf(','));
    const tail = s.slice(s.indexOf(',') + 1);
    if (tail.length === 3 && /\d$/.test(head)) return NaN;     // ambiguous
    s = s.replace(',', '.');
  } else if (dots > 1){
    s = s.replace(/\./g, '');
  }
  if (!/^\d+(\.\d+)?$/.test(s)) return NaN;
  // A negative cost or residual is refused by the engine, so it must not be
  // quietly folded into a total the user is about to trust.
  if (neg) return NaN;
  return parseFloat(s);
}

/* A row counts as filled only on its own content. The category column never
   qualifies: it is a dropdown, so it always holds a value, and "apply to all
   rows" would otherwise turn every blank line into a row. The engine draws
   the same line -- it skips a line with neither name nor inv_no. */
const GRID_SELF = GRID_COLS.map((c, i) => i).filter(i => GRID_COLS[i].f !== 'category');
const impGridFilled = row => GRID_SELF.some(i => String(row[i] ?? '').trim());

function impGridTotals(){
  if (!document.getElementById('gridcount')) return;
  impGridRead();
  const money = GRID_COLS.map((c, i) => [c, i]).filter(([c]) => c.num);
  const ni = gcol('name');
  const ci = gcol('category');
  const sum = {}, bad = {};
  money.forEach(([, i]) => { sum[i] = 0; bad[i] = 0; });
  let rows = 0, noName = 0, noCat = 0;
  IMP.grid.forEach((row, r) => {
    if (!impGridFilled(row)) return;
    rows++;
    if (!String(row[ni] ?? '').trim()) noName++;
    // Marked the same way a bad number is -- a category left on "— seçin —"
    // is exactly as silent a wrong answer as one nobody chose on purpose.
    const catMissing = !String(row[ci] ?? '').trim();
    if (catMissing) noCat++;
    const catEl = document.querySelector(`#gridbody [data-r="${r}"][data-c="${ci}"]`);
    if (catEl) catEl.classList.toggle('badnum', catMissing);
    for (const [, i] of money){
      const v = impGridNum(row[i]);
      const el = document.querySelector(`#gridbody [data-r="${r}"][data-c="${i}"]`);
      // Marked rather than dropped -- and the mark has to come off again once
      // the cell is fixed, or the row goes on accusing itself.
      if (el) el.classList.toggle('badnum', Number.isNaN(v));
      if (v === null) continue;
      if (Number.isNaN(v)) bad[i]++; else sum[i] += v;
    }
  });
  money.forEach(([c, i]) => {
    document.getElementById(`gridsum-${c.f}`).innerHTML = rows
      ? fmt.format(sum[i]) + (bad[i] ? ` <span class="badtag">+${bad[i]}?</span>` : '')
      : '';
  });
  document.getElementById('gridcount').textContent =
    rows ? `Cəmi: ${rows} sətir` : '';
  const badnum = money.reduce((n, [, i]) => n + bad[i], 0);
  const problems = [];
  if (noName) problems.push(`${noName} sətirdə ad yoxdur`);
  if (noCat) problems.push(`${noCat} sətirdə kateqoriya seçilməyib`);
  if (badnum) problems.push(`${badnum} rəqəm oxunmur`);
  document.getElementById('gridbad').innerHTML = problems.length
    ? `<span class="badtag">${esc(problems.join('; '))}</span>` : '';
}

/* Read the DOM back into IMP.grid so edits survive a re-render or a trip to
   the preview and back. */
function impGridRead(){
  for (const el of document.querySelectorAll('#gridbody [data-r]'))
    IMP.grid[+el.dataset.r][+el.dataset.c] = el.value;
}

function impGridAdd(n){
  impGridRead();
  for (let i = 0; i < n; i++) IMP.grid.push(gridRow());
  impGrid(IMP.grid);
}

function impGridAllCats(code){
  if (!code) return;
  impGridRead();
  const c = gcol('category');
  IMP.grid.forEach(r => { r[c] = code; });
  impGrid(IMP.grid);
}

function impGridPaste(e){
  const el = e.target;
  if (!el.dataset || el.dataset.r == null) return true;
  const text = (e.clipboardData || window.clipboardData).getData('text');
  if (!text) return true;
  const block = text.replace(/\r\n?/g, '\n').replace(/\n+$/, '')
                    .split('\n').map(l => l.split('\t'));
  // A single value is an ordinary paste -- let the browser do it.
  if (block.length === 1 && block[0].length === 1) return true;
  e.preventDefault();

  impGridRead();
  const r0 = +el.dataset.r, c0 = +el.dataset.c;
  while (IMP.grid.length < r0 + block.length)
    IMP.grid.push(gridRow());
  block.forEach((line, i) => line.forEach((v, j) => {
    const c = c0 + j;
    if (c >= GRID_COLS.length) return;          // wider than the grid: ignore
    IMP.grid[r0 + i][c] = GRID_COLS[c].f === 'category'
      ? impGridCat(v) : v.trim();
  }));
  impGrid(IMP.grid);
  return false;
}

/* A pasted category may be our code, or the Azerbaijani name from their
   sheet. Anything else is left for the preview to reject by name. */
function impGridCat(v){
  const s = String(v).trim().toLowerCase();
  const hit = impCats().find(k => k.code.toLowerCase() === s
                              || k.name_az.toLowerCase() === s);
  return hit ? hit.code : s;
}

async function impPreview(){
  IMP.step = 3;
  const rep = (await post('asset.import',
    {rows: impPayload(), opening_year: IMP.year, dry_run: true})).result;
  const bad = rep.errors.length;
  const carried = rep.rows.filter(r => r.mode === 'carried').length;
  const fresh = rep.rows.filter(r => r.mode === 'new').length;
  const auto = rep.rows.filter(r => r.auto_inv).length;

  // Import appends. With inventory numbers filled in, a second run of the
  // same sheet is refused row by row; with them blank there is nothing to
  // collide and the duplicates simply arrive under fresh numbers. Say so
  // before the button, not after (§2.1).
  const already = rep.existing ? `<div class="note">Bu müştəridə artıq
      <strong>${rep.existing} ƏV</strong> var. İdxal onları <strong>silmir</strong>,
      üstünə əlavə edir.${auto ? ` Bu cədvəldə inventar nömrələri boşdur —
      təkrar idxal ${auto} kartı ikinci dəfə yaradacaq, proqram bunu
      tuta bilməyəcək.` : ''}
      <br>Sıfırdan başlamaq üçün: ⚙ → «Bütün ƏV-ləri sil».</div>` : '';

  // A row bought in an EARLIER year with no opening residual is accepted by
  // every rule -- name, category and date are all there -- and then computes
  // to nothing: no acquisition this year, no balance carried in, so the card
  // arrives already reading «tam amortizasiya olunub». That is a legitimate
  // state (a genuinely spent asset) and also exactly what a mis-landed
  // residual column looks like, so it is called out BEFORE the button
  // rather than discovered afterwards one card at a time (§2.1).
  const spent = rep.rows.filter(r => r.ok && r.mode === 'new' && r.in_date
                                  && +r.in_date.slice(0, 4) < IMP.year);
  const spentNote = spent.length ? `<div class="note"><strong>${spent.length}
      ƏV ${IMP.year} ilindən əvvəl alınıb, lakin «Qalıq (${IMP.year} əvv.)»
      sütunu boşdur.</strong> Belə kartlar «tam amortizasiya olunub» kimi
      hesablanacaq — amortizasiya 0. Doğrudan da tam amortizasiya
      olunubsa, bu düzgündür; əks halda geri qayıdıb qalıq sütununu
      doldurun.<br>${spent.slice(0, 5).map(r => esc(r.name)).join(', ')}${
      spent.length > 5 ? ` … və daha ${spent.length - 5}` : ''}</div>` : '';

  const summary = bad
    ? `<div class="note"><strong>${bad} sətirdə problem var.</strong>
        İdxal ya bütövlükdə keçir, ya da heç keçmir — belə ki, yarımçıq
        müştəri yaranmasın. Aşağıda qırmızı sətirləri düzəldib yenidən cəhd edin.</div>`
    : `<div class="note q"><strong>${rep.created} ƏV əlavə olunacaq.</strong><br>
        ${carried ? `${carried}-i əvvəlki illərdən gəlir — ${IMP.year} ilin
          əvvəlinə qalıq dəyəri ilə.<br>` : ''}
        ${fresh ? `${fresh}-i bu il alınıb — ilkin dəyəri ilə.<br>` : ''}
        ${auto ? `${auto} ƏV üçün inventar nömrəsi avtomatik veriləcək.<br>` : ''}
        ${rep.groups_created ? `${rep.groups_created} yeni növ yaradılacaq.` : ''}</div>`;

  impBox(3, already + summary + spentNote + `
    <div class="scroll imp" style="max-height:42vh"><table><thead><tr>
      <th>#</th><th>İnv.№</th><th>Adı</th><th>Kateqoriya</th>
      <th class="num">İlkin dəyər</th><th class="num">Qalıq dəyər</th>
      <th>Nəticə</th></tr></thead><tbody>${
      rep.rows.map(r => `<tr class="${r.ok?'good':'bad'}">
        <td>${r.line}</td>
        <td>${esc(r.inv_no)}${r.auto_inv ? '<span class="tag">avto</span>' : ''}</td>
        <td>${esc(r.name)}</td><td>${esc(r.category||'')}</td>
        <td class="num">${r.cost ? money(r.cost) : ''}</td>
        <td class="num">${r.residual ? money(r.residual) : ''}</td>
        <td>${r.ok ? '✓' : esc(r.message)}</td></tr>`).join('')}</tbody></table></div>`,
    bad ? (IMP.back === impGrid ? 'Cədvələ qayıt' : 'Sütunlara qayıt')
        : `Bəli, ${rep.created} ƏV idxal et`,
    () => (IMP.back || impColumns)());

  MSUBMIT = async () => {
    if (bad){ (IMP.back || impColumns)(); throw new Error(STAY); }
    await post('asset.import', {rows: impPayload(), opening_year: IMP.year});
  };
}
