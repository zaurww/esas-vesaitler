let CARD = null, CAT = null;
function openCard(id){
  let card = null, cat = null;
  for (const k of REPORT.categories) for (const x of k.cards)
    if (x.asset_id === id){ card = x; cat = k; }
  if (!card) return;
  CARD = card; CAT = cat;
  document.getElementById('dtitle').textContent = (card.inv_no ? card.inv_no + ' · ' : '') + card.name;
  const step = (l, v, extra='') =>
    `<div class="step ${extra}"><span class="l">${l}</span><span class="num">${
      typeof v === 'string' && !isNaN(parseFloat(v)) ? fmt.format(parseFloat(v)) : v}</span></div>`;
  let h = '';
  if (!REPORT.is_closed){
    h += `<div class="acts">
      <button onclick="showHistory('${card.asset_id}')"><strong>Tam tarixçə</strong></button>
      <button onclick="formAsset(CARD)">Redaktə</button>
      <button onclick="formOpening(CARD)">Açılış qalığı</button>
      <button onclick="formDisposal(CARD)">Xaricetmə</button>
      <button onclick="formRepair(CARD)">Təmir xərci</button>
      <button onclick="formAddition(CARD)">Dəyər artımı</button>
      <button onclick="formElection(CAT, CARD)">Fərdi dərəcə</button>
      ${card.threshold_hit ? `<button onclick="toggleWriteoff(CARD, ${!card.written_off})">
        ${card.written_off ? 'Silinməni ləğv et' : '500/5% silinməsi'}</button>` : ''}
      <button class="danger" onclick="confirmDelete(CARD)">Sil</button>
    </div>`;
  } else {
    h += `<div class="acts">
      <button onclick="showHistory('${card.asset_id}')"><strong>Tam tarixçə</strong></button>
    </div>
    <div class="note">${REPORT.year} ili bağlıdır — dəyişiklik qəbul edilmir (§6).</div>`;
  }
  for (const [label, value] of [['Kontragent', card.counterparty],
                                ['E-qaimə №', card.e_qaime],
                                ['Seriya №', card.serial_no]])
    if (value)
      h += `<div class="step"><span class="l">${label}</span>
        <span>${esc(value)}</span></div>`;
  h += step('İlkin dəyər (alış)', card.cost);
  if (parseFloat(card.cost_effective) !== parseFloat(card.cost))
    h += step('İlkin dəyər (artımlarla)', card.cost_effective);
  h += `<div class="step"><span class="l">1 · Qalıq (il əvvəli)
      <em style="opacity:.7">${{explicit:'(daxil edilib)',
        carried:'(əvvəlki ildən köçürülüb)', none:''}[card.opening_source] || ''}</em>
    </span><span class="num">${money(card.opening)}</span></div>`;
  h += step('2 · Daxilolma', card.acquisition);
  h += step('2a · Dəyər artımı (komponent)', card.addition);
  h += step('3 · Kapitallaşan təmir (m.115)', card.repair_capitalized);
  h += step('4 · Xaricetmə', card.disposed);
  h += step('= Amortizasiya bazası', card.base);
  h += `<div class="step"><span class="l">5 · 500/5% həddi</span><span>${
    card.threshold_hit ? '⚠ düşür' : 'düşmür'}</span></div>`;
  if (card.threshold_hit)
    h += `<div class="note" style="margin:8px 0">${esc(card.threshold_reason)}<br>
      ${card.written_off ? 'writeoffs.tsv-də qərar var → tam silinmə'
                         : 'qərar yoxdur → silinmə tətbiq edilmədi'}</div>`;

  // Step 6 is the audit trail for the single most questionable number in the
  // whole return: a rate above the one printed in the tax code. Spelled out
  // factor by factor so it answers "why 50% when article 114.3 says 25%".
  const r6 = card.rate_info || cat.rate;
  const SRC = {asset: 'bu ƏV üçün fərdi seçim', category: 'kateqoriya üzrə seçim',
               norm: 'seçim yoxdur — m.114.3 norması'};
  h += `<div class="step"><span class="l"><strong>6 · Amortizasiya dərəcəsi</strong></span>
        <span><strong>${pct(r6.applied)}</strong></span></div>
    <div class="sub">
      <div class="step"><span class="l">VM m.114.3 norması (maksimum)</span>
        <span class="num">${pct(r6.statutory_max)}</span></div>
      <div class="step"><span class="l">Sahibkar əmsalı — ${esc(REPORT.status_name)}
        <em style="opacity:.75">${parseFloat(r6.coefficient) > 1
          ? (r6.coefficient_used ? '(istifadə olunur)' : '(haqdır, istifadə olunmayıb)')
          : ''}</em></span>
        <span class="num">× ${r6.coefficient}</span></div>
      <div class="step"><span class="l">Yuxarı hədd</span>
        <span class="num">= ${pct(r6.ceiling)}</span></div>
      <div class="step"><span class="l">Tətbiq olunan — ${SRC[r6.source]}</span>
        <span class="num">${pct(r6.applied)}</span></div>
    </div>
    ${r6.below_ceiling ? `<div class="note" style="margin:8px 0">Hədddən aşağı dərəcə
      seçilib — qanunidir, lakin məntiqli qərar olmalıdır.</div>` : ''}`;
  h += step('Amortizasiya', card.depreciation);
  if (parseFloat(card.writeoff)) h += step('Silinmə', card.writeoff);
  h += step('7 · Qalıq (il sonu)', card.closing, 'res');
  if (card.disposal_type){
    h += `<h3>Xaricetmə</h3>` + step('Tarix', card.disposal_date) +
         step('Növ', card.disposal_type) + step('Satış', card.proceeds) +
         step('Qalıq', card.disposed) + step('Fərq', card.gain_loss) +
         `<div class="note q" style="margin-top:8px">Satışdan gəlir/zərərin bəyannamədə
          əks etdirilməsi həll olunmayıb — CLAUDE.md §12.1</div>`;
  }
  if (parseFloat(card.depreciation)){
    h += '<h3>Aylıq bölgü</h3><div class="scroll"><table>' +
      card.monthly.map((v,i) =>
        `<tr><td>${REPORT.months[i]}</td><td class="num">${money(v)}</td></tr>`).join('') +
      '</table></div>';
  }
  document.getElementById('dbody').innerHTML = h;
  document.getElementById('drawer').classList.add('open');
}
const closeDrawer = () => document.getElementById('drawer').classList.remove('open');

/* ---- write-off decision & delete ---- */
function toggleWriteoff(card, on){
  openModal(on ? '500/5% silinməsi' : 'Silinmə qərarını ləğv et',
    `<input type="hidden" name="asset_id" value="${card.asset_id}">
     <input type="hidden" name="year" value="${REPORT.year}">
     <input type="hidden" name="enabled" value="${on ? '1' : ''}">
     <div class="h" style="margin-bottom:12px">${esc(card.threshold_reason)}</div>` +
    (on ? fld('reason','Əsas',{value:'VM m.114 — 500/5% həddi, birdəfəlik silinmə'})
        : '<div class="h">Silinmə qərarı silinəcək, ƏV adi qaydada amortizasiya olunacaq.</div>'),
    d => post('writeoff.set', {...d, enabled: on}), on ? 'Sil' : 'Ləğv et');
}

function confirmDelete(card){
  openModal(`ƏV silinsin? — ${card.inv_no || card.name}`,
    `<input type="hidden" name="asset_id" value="${card.asset_id}">
     <div class="h">Bu ƏV ilə birlikdə ona aid <strong>bütün</strong> sətirlər
     silinir: açılış qalığı, xaricetmə, təmir, silinmə qərarı, fərdi dərəcə.
     Əməliyyatdan əvvəl ehtiyat nüsxə götürülür.</div>`,
    d => post('asset.delete', d), 'Sil');
}
