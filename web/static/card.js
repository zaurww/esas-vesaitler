let CARD = null, CAT = null;
function openCard(id){
  let card = null, cat = null;
  for (const k of REPORT.categories) for (const x of k.cards)
    if (x.asset_id === id){ card = x; cat = k; }
  if (!card) return;
  CARD = card; CAT = cat;
  // Two exclusions, and they do not coincide. Art. 115 sets no repair limit
  // for an intangible at all; a rate election is refused only where a
  // schedule replaced the rate -- a `qma-n` in 2025 is still a norm on a
  // residual and may still be accrued below it.
  const rinf = card.rate_info || cat.rate;
  const qma = isQma(card.category);
  const straight = rinf.method === 'duz';
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
      ${qma ? '' : `<button onclick="formRepair(CARD)">Təmir xərci</button>`}
      <button onclick="formAddition(CARD)">Dəyər artımı</button>
      ${straight ? '' : `<button onclick="formElection(CAT, CARD)">Fərdi dərəcə</button>`}
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
    qma ? 'tətbiq olunmur (m.114.8 — əsas vəsait)'
        : card.threshold_hit ? '⚠ düşür' : 'düşmür'}</span></div>`;
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
  // A straight line has no "norm x factor = ceiling" to walk through: the
  // amount comes from a length. The two questions this block owes the reader
  // are therefore different ones -- how many years are left, and why the
  // entrepreneur coefficient is not among the factors.
  if (straight){
    h += `<div class="step"><span class="l"><strong>6 · Amortizasiya cədvəli</strong>
        — düz xətt (m.114.3.6)</span>
        <span><strong>${money(card.depreciation)}</strong></span></div>
      <div class="sub">
        <div class="step"><span class="l">İstifadə müddəti${
          card.category === 'qma-n' ? ' — qanunla (m.114.3-1.10)'
                                    : ' — FİM, kartda göstərilib'}</span>
          <span class="num">${r6.term_years} il</span></div>
        <div class="step"><span class="l">Bu ilin əvvəlinə qalan müddət</span>
          <span class="num">${r6.remaining_years} il</span></div>
        <div class="step"><span class="l">Baza ÷ qalan müddət</span>
          <span class="num">${money(card.base)} ÷ ${r6.remaining_years}</span></div>
        <div class="step"><span class="l">Sahibkar əmsalı — ${esc(REPORT.status_name)}</span>
          <span>tətbiq olunmur</span></div>
      </div>
      <div class="note" style="margin:8px 0">m.114.3-2 və m.114.3-3 əmsalı
        <strong>əsas vəsaitlərə</strong> verir, qeyri-maddi aktiv isə m.118-ə
        görə əsas vəsait deyil. m.114.8 (500/5%) də bu kartda yoxlanılmır.</div>`;
  } else {
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
  }
  h += step('Amortizasiya', card.depreciation);
  if (parseFloat(card.writeoff)) h += step('Silinmə', card.writeoff);
  h += step('7 · Qalıq (il sonu)', card.closing, 'res');
  if (card.disposal_type){
    h += `<h3>Xaricetmə</h3>` + step('Tarix', card.disposal_date) +
         step('Növ', card.disposal_type) + step('Satış', card.proceeds) +
         step('Qalıq', card.disposed) + step('Fərq', card.gain_loss) +
         `<div class="note" style="margin-top:8px">Fərq bəyannamədə ayrıca sətirdir:
          gəlir üçün m.114.7, zərər üçün m.114.9 — «Bəyannamə» bölməsinə baxın.</div>`;
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
