/* The annual table describes its own columns.

   Sixteen columns is the honest width of the calculation, and most days the
   accountant is looking at three of them. So the value columns are declared
   once -- header, card cell and total cell together -- and drawn only if the
   user left them on. Written positionally it would have been shorter, and
   wrong the first time a column moved: the totals row spans four columns with
   one cell, so "the ninth <td>" is not the ninth column there.

   The first four (flag, number, name, date) are what a row is IDENTIFIED by
   and are never hidden -- a table you cannot tell the rows apart in is not
   more compact, it is unreadable. */
const ANN_COLS = [
  {k:'cost',     h:'İlkin dəyər',
   cell:c => money(c.cost),                    tot:() => ''},
  {k:'opening',  h:'Qalıq (il əvvəli)',
   cell:c => money(c.opening),                 tot:x => money(x.opening)},
  {k:'acquisition', h:'Daxilolma',
   cell:c => money(c.acquisition),             tot:x => money(x.acquisition)},
  {k:'addition', h:'Dəyər artımı',
   cell:c => money(c.addition),                tot:x => money(x.addition)},
  {k:'repair',   h:'Kapital. təmir',
   cell:c => money(c.repair_capitalized),      tot:x => money(x.repair_capitalized)},
  {k:'disposed', h:'Xaricetmə',
   cell:c => money(c.disposed),                tot:x => money(x.disposed)},
  // Norm and factor are shown apart so that "which assets carry the
  // coefficient" is something you read down a column (§5.2).
  {k:'norm',     h:'Norma (m.114.3)',
   cell:(c,cat) => annRate(c,cat)[0],          tot:() => null},
  {k:'factor',   h:'Əmsal',
   cell:(c,cat) => annRate(c,cat)[1],          tot:() => null},
  {k:'rate',     h:'Dərəcə',
   cell:c => rateCell(c),
   tot:() => null},
  {k:'depreciation', h:'Amortizasiya',
   cell:c => `<strong>${money(c.depreciation)}</strong>`,
   tot:x => money(x.depreciation)},
  {k:'writeoff', h:'Silinmə',
   cell:c => money(c.writeoff),                tot:x => money(x.writeoff)},
  {k:'closing',  h:'Qalıq (il sonu)',
   cell:c => money(c.closing),                 tot:x => money(x.closing)},
];

// Hidden columns survive a reload: making the table fit is a setting about
// how this person works, not a click to be repeated every morning.
let HIDECOLS = new Set(JSON.parse(localStorage.getItem('ev.hidecols') || '[]'));

// Multi-select for bulk delete. NOT persisted like HIDECOLS -- a set of
// asset_ids is only meaningful for the report currently on screen, and
// carrying it across a client/year switch would delete the wrong cards.
let SELMODE = false;
let SELECTED = new Set();

function toggleSelMode(){
  SELMODE = !SELMODE;
  if (!SELMODE) SELECTED.clear();
  render();
}
function selRefreshBar(){
  const btn = document.getElementById('seldelbtn');
  if (!btn) return;
  btn.textContent = SELECTED.size ? `Seçilmişləri sil (${SELECTED.size})` : 'Seçilmişləri sil';
  btn.disabled = !SELECTED.size;
}
function selToggle(id, on){
  if (on) SELECTED.add(id); else SELECTED.delete(id);
  selRefreshBar();
}
function selAllVisible(on){
  document.querySelectorAll('.selpick').forEach(el => {
    el.checked = on;
    if (on) SELECTED.add(el.value); else SELECTED.delete(el.value);
  });
  selRefreshBar();
}

/* Same shape as clients.js's formClearAssets() and report.js's bulkWriteoff():
   name the cards, warn what goes with them, ask once. asset.delete_many
   backs the folder up before touching anything (§8.1), same as a single
   delete. */
function bulkDeleteAssets(){
  const ids = [...SELECTED];
  if (!ids.length) return fail('Heç bir ƏV seçilməyib.');
  const cards = REPORT.categories.flatMap(c => c.cards)
    .filter(c => ids.includes(c.asset_id));
  openModal(`${ids.length} ƏV silinsin?`,
    `<div class="h">Seçilmiş ƏV-lərlə birlikdə onlara aid <strong>bütün</strong>
     sətirlər silinir: açılış qalığı, xaricetmə, təmir, dəyər artımı, silinmə
     qərarı, fərdi dərəcə. Əməliyyatdan əvvəl ehtiyat nüsxə götürülür.</div>
     <div class="h" style="margin-top:10px;max-height:160px;overflow:auto">${
       cards.map(c => esc((c.inv_no ? c.inv_no + ' · ' : '') + c.name)).join('<br>')
     }</div>`,
    // Cleared only on success -- a failed post leaves the modal open (§base.js
    // submitModal) and the same ids selected, so a retry does not have to be
    // re-picked from the table.
    async () => {
      const r = await post('asset.delete_many', {asset_ids: ids});
      SELECTED.clear();
      return r;
    }, 'Sil');
}

/* A straight-line card states a TERM, never a bare percentage.

   The charge is base / years remaining, so a cell reading "20%" beside a base
   of 800 invites the reader to arrive at 160 when the row says 200. Printing
   what it actually is -- five years, three of them left -- makes the amount
   reproducible from the columns next to it, which is the whole point of
   showing a rate at all (§5.2). */
function rateCell(c){
  const ri = c.rate_info;
  if (ri && ri.method === 'duz' && ri.remaining_years)
    return `<span title="düz xətt: baza ÷ qalan il">${ri.term_years} il
      <span class="tag">qalan ${ri.remaining_years}</span></span>`;
  return parseFloat(c.rate) ? pct(c.rate) : '<span class="zero">—</span>';
}

function annRate(c, cat){
  const ri = c.rate_info || cat.rate;
  // Straight line: the norm is a fraction of the term and no coefficient can
  // reach it (114.3-2 and 114.3-3 speak of fixed assets), so the factor
  // column has nothing to say rather than a misleading x1.
  if (ri && ri.method === 'duz')
    return [ri.term_years ? `1/${ri.term_years}` : 'FİM üzrə',
            '<span class="zero">—</span>'];
  if (!parseFloat(c.rate))
    return ['<span class="zero">—</span>', '<span class="zero">—</span>'];
  const [norm, factor] = rateSplit(c.rate, ri.statutory_max, ri.coefficient);
  return [norm, factor + (ri.source === 'asset'
    ? '<span class="tag" title="bu ƏV üçün fərdi seçim">f</span>' : '')];
}

function toggleCol(k, on){
  if (on) HIDECOLS.delete(k); else HIDECOLS.add(k);
  localStorage.setItem('ev.hidecols', JSON.stringify([...HIDECOLS]));
  render();
}

/* Subtotals per «Növ» inside each category (§13.1). A setting, not a click
   to repeat every morning -- same reasoning as the hidden columns above.

   Note what it does NOT do: it changes no figure. The group rows are a
   partition of the cards already on screen, printed between them and the
   category line the engine computed. */
let GROUPBY = localStorage.getItem('ev.groupby') === '1';

function toggleGroupBy(on){
  GROUPBY = on;
  localStorage.setItem('ev.groupby', on ? '1' : '0');
  render();
}

// Open/closed is state, not a DOM detail: each checkbox re-renders the table,
// and a panel that lived only in the DOM shut itself after every single tick.
let COLPICK = false;

function colPicker(){ COLPICK = !COLPICK; render(); }

/* The cards of one category in printing order.

   With the switch off that is simply the cards. With it on they are laid out
   group by group -- dictionary order, the ungrouped last -- and two kinds of
   marker are slipped into the same array: a header before each run and a
   subtotal after it. One array means the table body stays a single pass, and
   the subtotal is built by the very function that builds the category line,
   so the two can never disagree about what a column means. */
function cardOrder(cards){
  if (!GROUPBY || !GROUPS().length) return cards;
  const present = new Set(cards.map(c => c.group_id || ''));
  const order = GROUPS().map(g => g.group_id).filter(id => present.has(id));
  if (present.has('')) order.push('');
  const out = [];
  for (const id of order){
    const part = cards.filter(c => (c.group_id || '') === id)
                      .filter(c => !(c.retired && HIDERETIRED));
    if (!part.length) continue;
    const name = id ? groupName(id) : '— növsüz —';
    out.push({__group_head: name, __group_n: part.length});
    out.push(...part);
    out.push({__group_total: sumCards(part), __group_name: name});
  }
  return out;
}

function viewAnnual(d){
  const cols = ANN_COLS.filter(c => !HIDECOLS.has(c.k));
  // One extra leading column while picking cards for bulk delete -- it has to
  // count into every colspan below it (category banner, group subtotal,
  // category and grand total), the same trap §11.3 already names: a colspan
  // written as a literal goes stale the moment a column is added in front.
  const lead = 4 + (SELMODE ? 1 : 0);
  const head = [
    ...(SELMODE ? [`<input type="checkbox" style="width:auto"
        onclick="selAllVisible(this.checked)" title="hamısını seç">`] : []),
    '', 'İnv.№', 'Adı', 'Alış tarixi', ...cols.map(c => c.h)];
  const span = lead + cols.length;
  let rows = '';
  for (const cat of cats(d)){
    const cards = cat.cards.filter(match);
    if (!cards.length) continue;
    const r = cat.rate;
    // A straight-line category has no ceiling to state and no rate to change:
    // the schedule comes from a term, per card where the card carries it. The
    // old header would have printed "0% x 1 = 0% hədd" for `qma-m` -- true of
    // nothing, and it invites the reader to look for the missing rate.
    const isItCat = cat.code === 'it';
    const headRate = r.method === 'duz'
      ? `<span class="rate">düz xətt (${isItCat ? 'm.115.6-1' : 'm.114.3.6'}) · ${r.per_card
          ? (isItCat ? 'müddət hər kartda — müqavilə' : 'müddət hər kartda — FİM')
          : r.term_years + ' il'} · sahibkar əmsalı tətbiq olunmur</span>`
      : `<span class="rate">${pct(r.statutory_max)} × ${r.coefficient} (${esc(d.status)})
      = ${pct(r.ceiling)} hədd · tətbiq <strong>${pct(r.applied)}</strong>
      ${cat.mixed_rates ? '<span class="tag">fərdi dərəcələr var</span>'
        : r.below_ceiling ? '<span class="tag w">həddən aşağı</span>' : ''}
      ${d.is_closed ? '' : `<button class="tagbtn"
        onclick="event.stopPropagation();formElection(REPORT.categories.find(x=>x.code==='${cat.code}'))"
        >dərəcəni dəyiş</button>`}</span>`;
    rows += `<tr class="cat"><td colspan="${span}">${esc(cat.name_az)}
      ${headRate}</td></tr>`;
    for (const c of cardOrder(cards)){
      // A group header, printed when the run of cards changes group. The rows
      // are already ordered by group, so this is a fold, not a second pass.
      if (c.__group_head != null){
        rows += `<tr class="grp"><td colspan="${span}">${esc(c.__group_head)}
          <span class="rate">${c.__group_n} ƏV</span></td></tr>`;
        continue;
      }
      if (c.__group_total){
        rows += `<tr class="subtotal"><td colspan="${lead}">${esc(c.__group_name)}
          — aralıq yekun</td>${totCells(cols, c.__group_total)}</tr>`;
        continue;
      }
      if (c.retired && HIDERETIRED) continue;
      const cls = c.retired ? 'asset retired'
                : c.threshold_hit ? 'asset warn'
                : c.threshold_next ? 'asset next' : 'asset';
      rows += `<tr class="${cls}" onclick="openCard('${c.asset_id}')"
        title="${c.retired ? esc(RETIRED_AZ[c.retired_kind] || '') + ' · ' + c.retired_year
                : c.threshold_next ? esc(c.threshold_next_reason) : ''}">
        ${SELMODE ? `<td onclick="event.stopPropagation()"><input type="checkbox"
              class="selpick" value="${c.asset_id}" style="width:auto"
              ${SELECTED.has(c.asset_id) ? 'checked' : ''}
              onchange="selToggle('${c.asset_id}',this.checked)"></td>` : ''}
        <td>${c.retired ? '·' : c.threshold_hit ? '⚠' : c.threshold_next ? '◐'
             : (c.disposal_type ? '→' : '')}</td>
        <td>${esc(c.inv_no)}</td>
        <td>${esc(c.name)}${c.is_legacy_pool ? '<span class="tag">qrup qalığı</span>' : ''}
            ${c.written_off ? '<span class="tag w">silindi</span>' : ''}
            ${c.retired ? `<span class="tag d">${esc(RETIRED_AZ[c.retired_kind]
                || 'balansdan çıxıb')}${c.retired_year ? ' ' + c.retired_year : ''}</span>` : ''}
            ${c.disposal_type ? `<span class="tag d">${esc(c.disposal_type)}</span>` : ''}</td>
        <td class="d">${esc(c.in_date)}</td>
        ${cols.map(col => `<td class="num">${col.cell(c, cat)}</td>`).join('')}</tr>`;
    }
    // Under a filter the category line has to cover what is on screen, not
    // what the category holds -- otherwise three visible rows sit under a
    // total of forty, which is wrong and looks entirely plausible.
    const narrowed = FILTER || GRPFILTER;
    rows += `<tr class="total"><td colspan="${lead}">${esc(cat.name_az)} — yekun${
      narrowed ? ' <span class="rate">süzgəcə görə</span>' : ''}</td>
      ${totCells(cols, narrowed ? sumCards(cards) : cat)}</tr>`;
  }
  // With a category picked, the grand total must cover only what is shown.
  const shown = cats(d);
  const narrowed = FILTER || GRPFILTER;
  const t = narrowed
    ? sumCards(shown.flatMap(c => c.cards).filter(match))
    : CATFILTER
      ? Object.fromEntries(SUM_KEYS.map(k =>
          [k, shown.reduce((s,c) => s + parseFloat(c[k]), 0).toFixed(2)]))
      : d.totals;
  rows += `<tr class="total"><td colspan="${lead}">C Ə M İ${
    narrowed ? ' (süzgəcə görə)' : CATFILTER ? ' (seçilmiş kateqoriya)' : ''}</td>
    ${totCells(cols, t)}</tr>`;
  const retired = d.categories.flatMap(c => c.cards).filter(c => c.retired).length;
  const toggle = retired ? `<label style="display:inline-flex;gap:6px;
        align-items:center;cursor:pointer" class="h">
        <input type="checkbox" style="width:auto" ${HIDERETIRED ? 'checked' : ''}
          onchange="HIDERETIRED=this.checked;render()">
        Balansdan çıxmış ƏV-ləri gizlət (${retired})</label>` : '';
  const picker = `<div id="colpick" class="colpick"
      style="display:${COLPICK ? 'flex' : 'none'}">${
    ANN_COLS.map(c => `<label><input type="checkbox"
        ${HIDECOLS.has(c.k) ? '' : 'checked'}
        onchange="toggleCol('${c.k}', this.checked)"> ${esc(c.h)}</label>`).join('')
    }<button class="tagbtn" onclick="HIDECOLS=new Set();
        localStorage.removeItem('ev.hidecols');render()">hamısını göstər</button></div>`;
  const groupSwitch = GROUPS().length ? `<label style="display:inline-flex;
        gap:6px;align-items:center;cursor:pointer" class="h">
        <input type="checkbox" style="width:auto" ${GROUPBY ? 'checked' : ''}
          onchange="toggleGroupBy(this.checked)"> Növ üzrə aralıq yekunlar</label>`
    : '';
  // Hidden on a closed year for the same reason card.js hides "Redaktə" and
  // "Sil" there (§6.2): the year's facts are sealed, and offering an action
  // that only ever ends in a write invites clicking it to find out.
  const selBar = d.is_closed ? '' : (SELMODE
    ? `<button class="tagbtn" onclick="toggleSelMode()">Seçimi bağla</button>
       <button id="seldelbtn" class="tagbtn" style="color:var(--neg)"
         ${SELECTED.size ? '' : 'disabled'} onclick="bulkDeleteAssets()">${
         SELECTED.size ? `Seçilmişləri sil (${SELECTED.size})` : 'Seçilmişləri sil'}</button>`
    : `<button class="tagbtn" onclick="toggleSelMode()">Bir neçəsini seç…</button>`);
  const bar = `<div class="tbar">${toggle}${groupSwitch}${selBar}
    <button class="tagbtn" onclick="colPicker()">Sütunlar${
      HIDECOLS.size ? ` (${ANN_COLS.length - cols.length} gizli)` : ''}</button>
    </div>${picker}`;
  return bar + `<div class="card"><div class="scroll"><table><thead><tr>${
    head.map((h,i) => `<th class="${i>=lead?'num':''}">${h}</th>`).join('')
  }</tr></thead><tbody>${rows}</tbody></table></div></div>`;
}

/* Totals line up under the value columns, and only under those: the first
   four columns are one spanning cell, which is exactly why the cells are
   generated from the same list as the headers rather than counted out. */
function totCells(cols, src){
  return cols.map(col => {
    const v = col.tot(src);
    return v === null ? '<td></td>' : `<td class="num">${v}</td>`;
  }).join('');
}

function viewMonthly(d){
  let rows = '';
  for (const cat of cats(d)){
    const cards = cat.cards.filter(c => match(c) && parseFloat(c.depreciation) !== 0);
    if (!cards.length) continue;
    rows += `<tr class="cat"><td colspan="15">${esc(cat.name_az)}</td></tr>`;
    for (const c of cards){
      rows += `<tr><td>${esc(c.inv_no)}</td><td>${esc(c.name)}</td>` +
        c.monthly.map(v => `<td class="num">${money(v)}</td>`).join('') +
        `<td class="num"><strong>${money(c.depreciation)}</strong></td></tr>`;
    }
    rows += `<tr class="total"><td colspan="2">${esc(cat.name_az)} — yekun</td>` +
      cat.monthly.map(v => `<td class="num">${money(v)}</td>`).join('') +
      `<td class="num">${money(cat.depreciation)}</td></tr>`;
  }
  rows += `<tr class="total"><td colspan="2">C Ə M İ</td>` +
    d.monthly.map(v => `<td class="num">${money(v)}</td>`).join('') +
    `<td class="num">${money(d.totals.depreciation)}</td></tr>`;
  return `<div class="card"><div class="scroll"><table><thead><tr>
    <th>İnv.№</th><th>Adı</th>${d.months.map(m => `<th class="num">${m}</th>`).join('')}
    <th class="num">C Ə M İ</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
}

/* Every figure that leaves this program for the profit return, in one place.
   They all existed before -- depreciation in the headline tiles, the repair
   deduction on its own tab, the 114.8 write-off in a tile named after the test
   instead of after what it does, and 114.7/114.9 down among the warnings. The
   accountant still had to assemble the answer to "what do I put in the return"
   out of four screens, which is what §12.1 meant by "computed but not filed".

   The list comes from the engine, not from here: the console and the workbook
   print the same one (§5.1 -- named once, or it drifts). */
const DECL_TAB = {'m.114':'annual', 'm.115.1':'repair', 'm.114.8':'threshold'};

function viewDeclaration(d){
  const net = parseFloat(d.declaration_net);
  const rows = d.declaration.map(ln => {
    const to = DECL_TAB[ln.article];
    // The working behind a figure is one click away: a number in a return is
    // worth exactly as much as the ability to show where it came from (§2).
    return `<tr${to ? ` class="asset" onclick="TAB='${to}';syncTabs();render()"` : ''}>
      <td><span class="tag d">${esc(ln.article)}</span></td>
      <td>${esc(ln.label_az)}${to ? ' <span class="hint">→ hesablanması</span>' : ''}</td>
      <td class="num"><strong>${money(ln.amount)}</strong></td>
      <td style="color:${ln.effect === 'income' ? 'var(--neg)' : 'var(--pos)'}">
        ${ln.effect === 'income' ? 'gəlirə əlavə edilir' : 'gəlirdən çıxılır'}</td></tr>`;
  }).join('');

  let h = `<div class="kpis">
      <div class="kpi hi"><div class="k">Gəlirdən çıxılır</div>
        <div class="v">${fmt.format(parseFloat(d.declaration_deducted))}</div></div>
      <div class="kpi"><div class="k">Gəlirə əlavə edilir</div>
        <div class="v">${fmt.format(parseFloat(d.declaration_income))}</div></div>
      <div class="kpi"><div class="k">Vergi tutulan gəlirə təsir</div>
        <div class="v" style="color:${net > 0 ? 'var(--neg)' : 'var(--pos)'}">
          ${net > 0 ? '+' : ''}${fmt.format(net)}</div></div>
    </div>
    <div class="card" style="margin-top:12px"><div class="scroll"><table><thead><tr>
      <th>Maddə</th><th>Nə</th><th class="num">Məbləğ</th><th>Təsir</th>
      </tr></thead><tbody>${rows}</tbody></table></div></div>`;

  if (d.disposals.length){
    h += `<h3>Təqdim edilmə — m.114.7 / m.114.9 üzrə fərq</h3>
      <div class="card"><div class="scroll"><table><thead><tr>
        <th>İnv.№</th><th>Adı</th><th>Tarix</th><th>Növ</th>
        <th class="num">Satış məbləği</th><th class="num">Qalıq dəyər</th>
        <th class="num">Fərq</th></tr></thead><tbody>${
        d.disposals.map(c => {
          const g = parseFloat(c.gain_loss);
          return `<tr><td>${esc(c.inv_no)}</td><td>${esc(c.name)}</td>
            <td class="d">${esc(c.date)}</td><td>${esc(c.type)}</td>
            <td class="num">${money(c.proceeds)}</td>
            <td class="num">${money(c.residual)}</td>
            <td class="num" style="color:${g>0?'var(--neg)':g<0?'var(--pos)':'inherit'}">
              ${g>0?'+':''}${money(c.gain_loss)}</td></tr>`;
        }).join('')}</tbody></table></div></div>
      <div class="note q">Fərq amortizasiyaya <strong>daxil deyil</strong> —
        bəyannamədə ayrıca sətirlərdir. Qalıq dəyərin özü m.114.6-ya görə onsuz da
        kateqoriyanın amortizasiya bazasından çıxılıb, ona görə burada ikinci dəfə
        sayılmır.</div>`;
  }
  h += `<div class="note">Bu siyahı proqramın verdiyi hər şeydir. Yuxarıdakı
      cədvəllər — həmin rəqəmlərin necə alındığıdır, bəyannaməyə isə bunlar köçürülür.
      <br>engine ${esc(d.engine_version)} · format v${d.format_version}${
      d.is_closed ? ' · <strong>il bağlıdır</strong>' : ''}</div>`;
  return h;
}

function viewNotes(d){
  let h = '';
  if (d.warnings.length){
    h += '<h3>Xəbərdarlıqlar</h3>' +
      d.warnings.map(w => `<div class="note">${esc(w)}</div>`).join('');
  }
  if (d.open_questions.length){
    h += '<h3>Həll olunmamış suallar (CLAUDE.md §12)</h3>' +
      d.open_questions.map(w => `<div class="note q">${esc(w)}</div>`).join('');
  }
  // The disposal difference used to be printed here, among the warnings. It is
  // not a note about the calculation, it is one of its results, so it moved to
  // the «Bəyannamə» tab with the rest of them.
  const n = k => fmt.format(parseFloat(d.totals[k]));
  h += `<h3>Yoxlama</h3><div class="card" style="padding:14px">
    Balans eyniliyi: qalıq(əvvəl) + daxilolma + dəyər artımı + kapitallaşan təmir
    − xaricetmə − amortizasiya − silinmə = qalıq(son)
    <br><strong>${n('opening')} + ${n('acquisition')} + ${n('addition')}
    + ${n('repair_capitalized')} − ${n('disposed')} − ${n('depreciation')}
    − ${n('writeoff')} = ${n('closing')}</strong> ✔
    <div class="hint" style="margin-top:8px">Hər kateqoriya üzrə də yoxlanılır;
      uyğunsuzluq halında hesablama dayanır (§2.1).</div></div>
    <h3>Versiya</h3><div class="card" style="padding:14px">
      engine ${esc(d.engine_version)} · format v${d.format_version}</div>`;
  return h || '<div class="card" style="padding:16px">Qeyd yoxdur.</div>';
}
