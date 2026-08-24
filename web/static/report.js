/* Balances move between years ONLY by closing a year (§6). Nothing carries
   over on its own, so an empty year needs to say why and offer the act. */
function renderCarry(d){
  const box = document.getElementById('carry');
  if (d.closed_years.includes(d.year)){
    box.innerHTML = `<div class="note">${d.year} ili <strong>bağlıdır</strong> —
      bəyannamə təqdim edilmiş il kimi qorunur, faktlara dəyişiklik qəbul
      edilmir (§6).
      <div class="acts" style="margin:8px 0 0">
        <button onclick="confirmReopen(${d.year})">Bağlanışı ləğv et</button>
      </div></div>`;
    return;
  }
  const carried = d.carried_from_prev
    ? `<span class="tag">giriş qalıqları ${d.year - 1} ilindən avtomatik köçürülüb</span>`
    : '';
  box.innerHTML = `<div class="acts" style="margin:0 0 12px;align-items:center">
    <button onclick="confirmClose(${d.year})">${d.year} ilini bağla (kilidlə)</button>
    ${carried}</div>`;
}

function confirmClose(year){
  openModal(`${year} ilini bağla`,
    `<input type="hidden" name="year" value="${year}">
     <div class="h"><strong>Bağlanış qalıqları köçürmək üçün lazım deyil</strong> —
     onlar onsuz da növbəti ilə keçir. Bağlanış başqa şey edir:
     <br><br>
     · ${year} ilinin faktları <strong>kilidlənir</strong> — bəyannamə təqdim
       edilmiş il kimi qorunur (§6);<br>
     · son qalıqlar mühərrik versiyası və tarixlə <strong>möhürlənir</strong>,
       beləliklə gələcək mühərrik dəyişikliyi təqdim edilmiş rəqəmləri
       dəyişdirə bilməz.
     <br><br>
     Səhv olarsa, bağlanışı ləğv etmək olar.</div>`,
    d => post('year.close', d), 'Bağla');
}

function confirmReopen(year){
  openModal(`${year} ilinin bağlanışını ləğv et`,
    `<input type="hidden" name="year" value="${year}">
     <div class="note">${year + 1} ilinin saxlanmış giriş qalıqları
     <strong>silinəcək</strong>. Növbəti bağlanışda onlar yenidən hesablanacaq.
     Əməliyyat changelog-a yazılır.</div>`,
    d => post('year.reopen', d), 'Ləğv et');
}

function renderSide(d){
  const btn2 = (id, label, sub, on) =>
    `<button aria-current="${on}" onclick="pickGroup('${id}')">${esc(label)}
       <span class="n">${sub}</span></button>`;
  const btn = (code, label, sub, on) =>
    `<button aria-current="${on}" onclick="pickCat('${code}')">${esc(label)}
       <span class="n">${sub}</span></button>`;
  let h = btn('', 'Bütün kateqoriyalar',
              `${cardCount(d)} ƏV · ${fmt.format(parseFloat(d.totals.depreciation))}`,
              CATFILTER === '') + '<hr>';
  for (const cat of d.categories){
    // A category can now be all retired rows and no holdings. "0 ƏV" alone
    // reads like a bug; the archived count says why the line is there at all.
    const ret = cat.cards.length - liveCards(cat).length;
    h += btn(cat.code, cat.name_az,
             `${liveCards(cat).length} ƏV${ret ? ` · ${ret} arxiv` : ''}`
             + ` · ${fmt.format(parseFloat(cat.depreciation))}`,
             CATFILTER === cat.code);
  }
  // The client's own grouping, under the law's. Only when there is one --
  // a client who does not keep types should not be shown an empty apparatus.
  const groups = GROUPS();
  if (groups.length){
    h += '<hr><div class="sidehead">Növ</div>';
    h += btn2('', 'Hamısı', '', GRPFILTER === '');
    for (const g of groups)
      h += btn2(g.group_id, g.name, `${groupCount(g.group_id)} ƏV`,
                GRPFILTER === g.group_id);
    const none = groupCount(NOGROUP);
    if (none) h += btn2(NOGROUP, '— növsüz —', `${none} ƏV`,
                        GRPFILTER === NOGROUP);
  }
  h += `<hr><button class="sidelink" onclick="formGroups()">Növləri idarə et…</button>`;
  document.getElementById('side').innerHTML = h;
}

function pickGroup(id){ GRPFILTER = (GRPFILTER === id) ? '' : id; render(); }

function pickCat(code){ CATFILTER = (CATFILTER === code) ? '' : code; render(); }

// Article 115: the deductible limit is a percentage of the GROUP's opening
// residual, while the spend itself is recorded per asset. Anything over the
// limit is capitalised into that asset's depreciation base (step 3).
function viewRepair(d){
  const rc = cats(d).filter(c => parseFloat(c.repair_actual) !== 0);
  if (!rc.length) return `<div class="card" style="padding:16px">
    ${d.year}-ci il üçün təmir xərci qeyd olunmayıb.
    <div class="hint" style="margin-top:6px">repairs.tsv boşdur.</div></div>`;
  let rows = '';
  for (const cat of rc){
    // Spell the limit out: it is a group figure applied to per-asset spend,
    // which is the part accountants ask about.
    const lim = parseFloat(cat.repair_limit), act = parseFloat(cat.repair_actual);
    rows += `<tr class="cat"><td colspan="6">${esc(cat.name_az)}
      <span class="rate">qrupun il əvvəlinə qalığı ${money(cat.opening)}
      × ${pct(cat.repair_limit_pct)} = limit <strong>${money(cat.repair_limit)}</strong>
      · faktiki ${money(cat.repair_actual)}
      → gəlirdən çıxılan MIN = <strong>${money(cat.repair_deductible)}</strong>
      ${act > lim ? `· artıq qalan ${money(cat.repair_capitalized)} kapitallaşır`
                  : '· limit aşılmayıb, hamısı çıxılır'}</span></td></tr>`;
    for (const c of cat.cards){
      if (parseFloat(c.repair_actual) === 0) continue;
      const share = parseFloat(c.repair_actual) / parseFloat(cat.repair_actual);
      rows += `<tr><td>${esc(c.inv_no)}</td><td>${esc(c.name)}
        <span class="rate">pay ${money(c.repair_actual)} / ${money(cat.repair_actual)}
        = ${(share*100).toFixed(2)}% → ${money(cat.repair_deductible)} × ${(share*100).toFixed(2)}%
        = ${money(c.repair_deductible)}</span></td>
        <td class="num">${money(c.repair_actual)}</td>
        <td class="num">${money(c.repair_deductible)}</td>
        <td class="num">${money(c.repair_capitalized)}</td>
        <td class="num">${money(c.base)}</td></tr>`;
    }
    rows += `<tr class="total"><td colspan="2">${esc(cat.name_az)} — qrup limiti
      ${money(cat.repair_limit)} (qalıq ${money(cat.opening)})</td>
      <td class="num">${money(cat.repair_actual)}</td>
      <td class="num">${money(cat.repair_deductible)}</td>
      <td class="num">${money(cat.repair_capitalized)}</td><td></td></tr>`;
  }
  const t = d.totals;
  return `<div class="card"><div class="scroll"><table><thead><tr>
      <th>İnv.№</th><th>Adı</th><th class="num">Faktiki təmir</th>
      <th class="num">Gəlirdən çıxılan</th><th class="num">Kapitallaşan</th>
      <th class="num">Amortizasiya bazası</th></tr></thead>
    <tbody>${rows}<tr class="total"><td colspan="2">C Ə M İ</td>
      <td class="num">${money(t.repair_actual)}</td>
      <td class="num">${money(t.repair_deductible)}</td>
      <td class="num">${money(t.repair_capitalized)}</td><td></td></tr>
    </tbody></table></div></div>
    <div class="note q">Limit = qrupun il əvvəlinə qalıq dəyəri × kateqoriya faizi.
      Faktiki xərc limitdən çox olduqda, çıxılan hissə qrup daxilində təmir
      məbləğlərinə mütənasib bölünür, qalığı isə həmin ƏV-in amortizasiya
      bazasına əlavə olunur (CLAUDE.md §5.5).</div>`;
}

// Searchable by everything written ON the card, including the e-invoice and
// the serial: "which asset is JTNBE46K..." is exactly the question those
// fields exist to answer.
const inGroup = c => !GRPFILTER
  || (GRPFILTER === NOGROUP ? !c.group_id : c.group_id === GRPFILTER);
const match = c => inGroup(c) && (!FILTER ||
  [c.name, c.inv_no, c.category, c.counterparty, c.e_qaime, c.serial_no, c.group]
    .join(' ').toLowerCase().includes(FILTER));

/* Totals over an arbitrary set of cards -- a group, or whatever a filter has
   left on screen. The keys are the ones the annual table's total cells read,
   so a subtotal row is built exactly like the category row above it.

   It exists because a totals line that ignores the filter is the failure
   §11.2 warns about: pick «Serverlər», see three rows, and read a category
   total covering forty. Wrong and entirely plausible-looking. */
const SUM_KEYS = ['opening', 'acquisition', 'addition', 'repair_capitalized',
                  'disposed', 'depreciation', 'writeoff', 'closing'];
const sumCards = cards => Object.fromEntries(SUM_KEYS.map(k =>
  [k, cards.reduce((s, c) => s + parseFloat(c[k]), 0).toFixed(2)]));
// The sidebar narrows the whole report to one category; the text box narrows
// it further to matching cards. Both are view state, never engine state.
const cats = d => d.categories.filter(c => !CATFILTER || c.code === CATFILTER);

/* The company-wide totals, narrowed the same way the annual table's own
   grand-total row is (§13.1) -- shared so the top KPI tiles and that row
   can never show two different numbers for what the sidebar/search/group
   filters currently leave on screen. */
const visibleTotals = d => {
  const shown = cats(d);
  const narrowed = FILTER || GRPFILTER;
  return narrowed
    ? sumCards(shown.flatMap(c => c.cards).filter(match))
    : CATFILTER
      ? Object.fromEntries(SUM_KEYS.map(k =>
          [k, shown.reduce((s,c) => s + parseFloat(c[k]), 0).toFixed(2)]))
      : d.totals;
};
// Counts are about the year's live assets. A card kept on screen after its
// life ended is a record, not a holding, and must not inflate "how many ƏV".
const liveCards = cat => cat.cards.filter(c => !c.retired);
const cardCount = d => d.categories.reduce((n, c) => n + liveCards(c).length, 0);

/* How a card's life ended, in the language of the report. */
const RETIRED_AZ = {writeoff:'500/5% silinib', realizasiya:'satılıb',
                    leqv:'ləğv edilib', amortizasiya:'tam amortizasiya olunub'};

/* Retired rows are shown by DEFAULT -- an asset that leaves the balance sheet
   does not leave the office, and "it disappeared from the report" is not an
   answer to what happened to it. The switch exists because after ten years
   the tail gets long, and the year's own work should not be read past it. */
let HIDERETIRED = false;

/* The applied rate taken apart: the article 114.3 norm on one side, what that
   norm was multiplied by on the other, so that norm × factor = rate exactly.

   One column reading "37.5%" cannot say WHY it is 37.5%, and with the
   entrepreneur coefficient the question worth answering is which assets carry
   it and which do not -- that should be visible by running an eye down a
   column, not by opening cards one at a time. The factor is computed from the
   two rates rather than read off the status, because it has to stay honest
   for an asset whose rate was picked by hand: there it shows what was really
   applied instead of the coefficient the status would have allowed.

   `available` is the coefficient the status offers. A row sitting at ×1 while
   the status offers 1.5 is not an error -- the coefficient is a right, not a
   duty (§5.2) -- but it IS the row someone may have meant to raise, so it
   says so quietly rather than looking identical to a row with no right at
   all. */
function rateSplit(applied, statutory, available){
  const s = parseFloat(statutory), a = parseFloat(applied);
  if (!s) return ['<span class="zero">—</span>', '<span class="zero">—</span>'];
  const f = a / s, av = parseFloat(available || 1);
  const shown = '×' + String(Math.round(f * 1e4) / 1e4);
  let cell;
  if (f > 1 + 1e-9)         cell = `<span class="tag c">${shown}</span>`;
  else if (Math.abs(f - 1) < 1e-9)
    cell = av > 1
      ? `<span class="zero" title="${pct(s)} × ${av} = ${pct(Math.min(s * av, 1))} mümkün idi">×1
         <span class="tag">${av} mümkün</span></span>`
      : '×1';
  else                      cell = `<span title="normadan aşağı">${shown}</span>`;
  return [pct(s), cell];
}

/* Everything the 114.8 test caught, in one place, decidable in one go.

   The engine has always produced this list (§5.6.3) but it was only ever
   shown as a ⚠ scattered down the annual table and a line each in the notes:
   fine for the one trailer in the demo, useless when a workshop's worth of
   tooling crosses the threshold in the same year and each one has to be
   opened, decided and closed by hand.

   Two sections, because they are two different years and only one of them is
   actionable: ⚠ is this year's decision, ◐ is a forecast for next year and
   deliberately has no buttons -- the test binds to the closing residual, so
   the write-off belongs to the year after it trips (§5.3-bis). */
function thresholdCards(d){
  const all = d.categories.flatMap(c => c.cards);
  return {now: all.filter(c => c.threshold_hit),
          next: all.filter(c => c.threshold_next)};
}

function viewThreshold(d){
  const {now, next} = thresholdCards(d);
  const pending = now.filter(c => !c.written_off);
  const name = c => `${c.inv_no ? esc(c.inv_no) + ' · ' : ''}${esc(c.name)}`;

  const row = (c, pick) => `<tr>
    <td>${pick ? `<input type="checkbox" class="thrpick" value="${c.asset_id}"
            ${c.written_off ? 'checked' : ''} style="width:auto">` : ''}</td>
    <td><a href="#" onclick="openCard('${c.asset_id}');return false">${name(c)}</a>
      ${c.written_off ? '<span class="tag w">qərar var</span>' : ''}</td>
    <td>${esc(CTX.categories.find(x => x.code === c.category)?.name_az || c.category)}</td>
    <td class="num">${money(c.cost)}</td>
    <td class="num">${money(pick ? c.opening : c.closing)}</td>
    <td class="h">${esc(pick ? c.threshold_reason : c.threshold_next_reason)}</td></tr>`;

  const table = (cards, pick, head) => `<div class="card"><div class="scroll">
    <table><thead><tr>
      <th style="width:28px">${pick && !d.is_closed
        ? `<input type="checkbox" onclick="thrAll(this.checked)" style="width:auto"
             title="hamısını seç">` : ''}</th>
      <th>${head}</th><th>Kateqoriya</th><th class="num">İlkin dəyər</th>
      <th class="num">${pick ? 'Qalıq (il əvvəli)' : 'Qalıq (il sonu)'}</th>
      <th>Səbəb</th>
    </tr></thead><tbody>${cards.map(c => row(c, pick)).join('')}</tbody></table>
  </div></div>`;

  let h = '';
  if (!now.length && !next.length)
    return `<div class="card" style="padding:16px">${d.year} ilində
      500/5% həddinə düşən ƏV yoxdur.</div>`;

  if (now.length){
    h += `<h3>${d.year} — həddə düşür (${now.length})</h3>`;
    h += table(now, true, 'ƏV');
    if (!d.is_closed)
      h += `<div class="acts" style="margin:10px 0 18px">
        <button onclick="bulkWriteoff(true)">Seçilmişləri sil (m.114.8)</button>
        <button class="ghost" onclick="bulkWriteoff(false)">Seçilmişlərin qərarını ləğv et</button>
        <span class="h" style="align-self:center">Qərarı olmayan: <strong>${pending.length}</strong>.
          Qərar verilməzsə, ƏV adi qaydada amortizasiya olunmağa davam edir.</span></div>`;
  }
  if (next.length){
    h += `<h3>${d.year + 1} — həddə düşəcək (${next.length})</h3>`;
    h += table(next, false, 'ƏV');
    h += `<div class="note" style="margin:10px 0">Bu il üçün qərar tələb
      olunmur: test ilin sonuna qalığa bağlıdır, ona görə silinmə növbəti ildə
      olur (§5.3-bis). Siyahı ona görə var ki, gələn il gözlənilməz olmasın.</div>`;
  }
  return h;
}

function thrAll(on){
  document.querySelectorAll('.thrpick').forEach(x => { x.checked = on; });
}

function bulkWriteoff(on){
  const ids = [...document.querySelectorAll('.thrpick:checked')].map(x => x.value);
  if (!ids.length) return fail('Heç bir ƏV seçilməyib.');
  const {now} = thresholdCards(REPORT);
  const picked = now.filter(c => ids.includes(c.asset_id));
  const total = picked.reduce((s, c) => s + parseFloat(c.opening), 0);
  openModal(on ? `500/5% silinməsi — ${ids.length} ƏV`
               : `Silinmə qərarı ləğv edilsin — ${ids.length} ƏV`,
    `<input type="hidden" name="year" value="${REPORT.year}">
     <div class="h" style="margin-bottom:10px">${picked.map(c =>
        esc((c.inv_no ? c.inv_no + ' · ' : '') + c.name)).join('<br>')}</div>` +
    (on ? `<div class="note" style="margin-bottom:12px">Gəlirdən çıxılacaq qalıq
             cəmi: <strong>${fmt.format(total)}</strong> AZN. Bu ƏV-lər üzrə
             ${REPORT.year} ili amortizasiyası hesablanmayacaq.</div>` +
          fld('reason','Əsas',{value:'VM m.114 — 500/5% həddi, birdəfəlik silinmə'})
        : '<div class="h">Seçilmiş ƏV-lər adi qaydada amortizasiya olunacaq.</div>'),
    d => post('writeoff.set', {...d, asset_ids: ids, enabled: on}),
    on ? 'Sil' : 'Ləğv et');
}
