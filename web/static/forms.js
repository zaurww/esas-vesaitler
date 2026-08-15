/* What the batch actually costs, under the field where the count is typed.
   The accountant knows the invoice total already; showing ours next to it
   turns "did I type the unit price or the total?" into a glance -- the same
   reasoning as the totals row under the paste grid (§11.2). */
function batchTotal(){
  const box = document.getElementById('batchsum');
  if (!box) return;
  const f = document.getElementById('mform');
  const say = parseInt(f.say && f.say.value, 10);
  const cost = parseFloat(f.cost && f.cost.value);
  box.innerHTML = (say > 1 && cost > 0)
    ? `<strong>${say} × ${fmt.format(cost)} = ${fmt.format(say * cost)}</strong> AZN`
    : '—';
}

/* ---- asset: new / carried over / group pool ---- */
function formAsset(card){
  const edit = !!card;
  let mode = 'new';
  const year = REPORT.year;

  const render = () => {
    const modes = edit ? '' : `<div class="modes">
      ${[['new','Bu il alınıb','tarix və ilkin dəyər məlumdur'],
         ['carried','Əvvəlki illərdən','qalıq dəyər son bəyannamədən'],
         ['pool','Qrup qalığı (kartsız)','yalnız kateqoriya üzrə cəm məlumdur']]
        .map(([m,t,s]) => `<button type="button" aria-pressed="${mode===m}"
          onclick="ASSETMODE('${m}')">${t}<small>${s}</small></button>`).join('')}
    </div>`;
    const pool = mode === 'pool';
    let h = modes + `<input type="hidden" name="mode" value="${mode}">`;
    if (edit) h += `<input type="hidden" name="asset_id" value="${card.asset_id}">`;
    h += fld('category','Kateqoriya',{type:'select',req:true,
             options:catOptions(card ? card.category : 'nv')});
    if (!pool){
      h += `<div class="row2">
        <div class="fld"><label>İnv.№</label>
          <div style="display:flex;gap:6px">
            <input name="inv_no" value="${val(card && card.inv_no)}"
              placeholder="məs. NV-0006">
            <button type="button" class="ghost" style="padding:8px 12px;white-space:nowrap"
              onclick="suggestInv()">növbəti</button>
          </div>
          <div class="h">Boş buraxsanız, mövcud nömrələməyə uyğun olaraq
            <strong>avtomatik verilir</strong>.</div></div>
        ${fld('in_date','Alış tarixi',{type:'date',value:card&&card.in_date,
              req:mode==='new'})}</div>`;
      h += fld('name','Adı',{value:card&&card.name,req:true,placeholder:'Toyota Camry 2.5'});
      h += fld('cost','İlkin dəyər (AZN)',{type:'number',step:'0.01',
              value:card&&card.cost,req:mode==='new',
              hint: mode==='carried'
                ? 'Məlum deyilsə boş buraxın — onda 500/5% testinin yalnız 500 AZN hissəsi işləyəcək.'
                : ''});
      // Neither figure enters the calculation; both are here because the card
      // is also where an accountant comes to answer "which invoice was this
      // on" and "which of the forty units is it". Optional on purpose --
      // plenty of clients keep neither.
      h += `<div class="row2">
        ${fld('counterparty','Kontragent',{value:card&&card.counterparty})}
        ${fld('e_qaime','E-qaimə №',{value:card&&card.e_qaime,
              placeholder:'ixtiyari'})}</div>`;
      // A batch shares its e-invoice but not its serials: the serial is what
      // tells the units apart, so offering one box for forty cards would
      // record something untrue about thirty-nine of them.
      h += fld('serial_no','Seriya № / VIN',{value:card&&card.serial_no,
            placeholder:'ixtiyari',
            hint: edit ? '' : 'Say 1-dən çoxdursa boş qalır — seriya nömrəsi '
               + 'hər ədəd üçün fərqlidir, sonra kartlarda ayrıca yazılır.'});
      // Buying the same thing many times over. One card per object is not
      // tidiness: m.114.8 tests each object separately, so 240 refrigerators
      // at 400 AZN fall under the threshold one by one, while a single
      // 96 000 AZN line never would.
      if (!edit){
        h += `<div class="row2">
          <div class="fld"><label>Say</label>
            <input name="say" type="number" min="1" step="1" value="1">
            <div class="h">Eyni əşyadan neçə ədəd alınıb. Hər ədəd üçün
              <strong>ayrıca kart</strong> yaradılır — m.114.8 həddi hər obyekt
              üzrə ayrıca yoxlanılır.</div></div>
          <div class="fld"><label>Cəmi</label>
            <div id="batchsum" class="h" style="font-size:14px;padding-top:9px">—</div>
            <div class="h">«İlkin dəyər» və «Qalıq dəyər» — bir ədəd üçündür.
              İnv.№-lər ardıcıl verilir.</div></div></div>`;
      }
    } else {
      h += fld('name','Adı',{placeholder:'avtomatik: «kateqoriya — qrup qalığı»',
              hint:'Kartsız qrup qalığı: inventar nömrəsi, tarix və ilkin dəyər olmur. '
                 + '5% testi tətbiq edilmir, yalnız 500 AZN.'});
    }
    if (!edit && mode !== 'new'){
      h += `<div class="row2">
        ${fld('opening_residual',`Qalıq dəyər — ${year} ilin əvvəlinə (AZN)`,
              {type:'number',step:'0.01',req:true})}
        ${fld('opening_year','İl',{type:'number',value:year,req:true})}</div>`;
    }
    // The opening residual is editable from here too -- a figure typed wrong
    // during import is corrected where it is read. Only when it IS a stored
    // fact: a residual carried from last year is computed (§2), and putting a
    // computed number in a form would turn it into stored data the moment
    // someone pressed save. For that case, point at the deliberate act.
    if (edit && card.opening_source === 'explicit'){
      h += `<input type="hidden" name="opening_edit" value="1">
            <input type="hidden" name="opening_year" value="${year}">` +
        fld('opening_residual',`Qalıq dəyər — ${year} ilin əvvəlinə (AZN)`,
            {type:'number',step:'0.01',value:card.opening,
             hint:'Əl ilə daxil edilmiş açılış qalığı (idxal da bura yazır). '
                + 'Boş buraxsanız sətir silinir və qalıq əvvəlki ildən hesablanır.'});
    }
    if (edit && card.opening_source === 'carried'){
      h += `<div class="fld"><div class="h">Qalıq (${year} ilin əvvəlinə)
        <strong>${money(card.opening)}</strong> — əvvəlki ildən hesablanıb,
        saxlanılan rəqəm deyil, ona görə burada redaktə olunmur. Bu il üçün
        onu əl ilə təyin etmək lazımdırsa: «Açılış qalığı».</div></div>`;
    }
    h += fld('note','Qeyd',{value:card&&card.note});
    openModal(edit ? `ƏV redaktəsi — ${card.inv_no || card.name}` : 'Yeni ƏV', h,
      d => post(edit ? 'asset.update' : 'asset.create', d),
      edit ? 'Yadda saxla' : 'Əlavə et');
    // Assigned rather than added: render() runs again on every mode switch,
    // and addEventListener would stack a handler each time.
    document.getElementById('mbody').oninput = batchTotal;
    batchTotal();
  };
  window.ASSETMODE = m => { mode = m; render(); };
  render();
}

/* Inventory numbers come from the office, often out of 1C, so the app
   follows whatever scheme is already in use instead of imposing one: it
   reads the prevailing prefix and padding of the category and steps the
   counter. Always a suggestion, never enforced. */
async function suggestInv(){
  const cat = document.querySelector('#mbody select[name=category]').value;
  const slug = document.getElementById('client').value;
  const r = await fetch(`/api/next-inv?client=${slug}&category=${cat}`);
  const j = await r.json();
  const box = document.querySelector('#mbody input[name=inv_no]');
  if (j.inv_no){ box.value = j.inv_no; box.focus(); }
}

/* ---- opening balance of an existing card ---- */
function formOpening(card){
  openModal(`Açılış qalığı — ${card.inv_no || card.name}`,
    `<input type="hidden" name="asset_id" value="${card.asset_id}">
     <input type="hidden" name="year" value="${REPORT.year}">` +
    fld('residual',`Qalıq dəyər — ${REPORT.year} ilin əvvəlinə (AZN)`,
        {type:'number',step:'0.01',value:card.opening,
         hint:'Boş buraxsanız, bu il üçün açılış qalığı silinir.'}),
    d => post('opening.set', d));
}

/* ---- disposal ---- */
function formDisposal(card){
  const has = !!card.disposal_type;
  openModal(`Xaricetmə — ${card.inv_no || card.name}`,
    `<input type="hidden" name="asset_id" value="${card.asset_id}">` +
    `<div class="row2">
      ${fld('date','Tarix',{type:'date',value:card.disposal_date,req:true})}
      ${fld('type','Növ',{type:'select',req:true,options:
        `<option value="realizasiya" ${card.disposal_type==='realizasiya'?'selected':''}>Realizasiya (satış)</option>
         <option value="leqv" ${card.disposal_type==='leqv'?'selected':''}>Ləğv (silinmə)</option>`})}
     </div>` +
    fld('proceeds','Satış məbləği (AZN)',{type:'number',step:'0.01',
        value:has?card.proceeds:'',
        hint:'Ləğv halında 0. Satışdan gəlir/zərərin bəyannamədə əks etdirilməsi '
           + 'hələ həll olunmayıb — CLAUDE.md §12.1.'}) +
    (has ? `<label style="font-size:12.5px"><input type="checkbox" name="remove"
        style="width:auto"> Xaricetməni ləğv et</label>` : ''),
    d => post('disposal.set', d));
}

/* ---- repair ---- */
function formRepair(card){
  openModal(`Təmir xərci — ${card.inv_no || card.name}`,
    `<input type="hidden" name="asset_id" value="${card.asset_id}">` +
    `<div class="row2">
      ${fld('date','Tarix',{type:'date',req:true,value:REPORT.year+'-01-01'})}
      ${fld('amount','Məbləğ (AZN)',{type:'number',step:'0.01',req:true})}</div>` +
    fld('note','Qeyd',{placeholder:'Mühərrik təmiri'}) +
    `<div class="h">Limit qrup üzrə hesablanır (m.115); limitdən artıq hissə
      bu ƏV-in amortizasiya bazasına əlavə olunur.</div>`,
    d => post('repair.add', d), 'Əlavə et');
}

/* ---- capital addition ----
   A component bought for an asset already on the books. Not a repair: it is
   not limited by article 115, it joins the cost in full. */
function formAddition(card){
  openModal(`Dəyər artımı — ${card.inv_no || card.name}`,
    `<input type="hidden" name="asset_id" value="${card.asset_id}">` +
    `<div class="row2">
      ${fld('date','Tarix',{type:'date',req:true,value:REPORT.year+'-01-01'})}
      ${fld('amount','Məbləğ (AZN)',{type:'number',step:'0.01',req:true})}</div>` +
    fld('note','Nə alınıb',{placeholder:'Əlavə yaddaş, komponent…'}) +
    `<div class="note q" style="margin-top:6px">Təmirdən fərqi: təmir aktivi
      bərpa edir və m.115 limitinə tabedir, dəyər artımı isə aktivi
      <strong>böyüdür</strong> — tam məbləğ ilkin dəyərə və amortizasiya
      bazasına əlavə olunur, limit tətbiq edilmir.<br>
      Vergi baxımından hansı halın hansına aid olması —
      <strong>CLAUDE.md §12.8, həll olunmayıb</strong>.</div>`,
    d => post('addition.add', d), 'Əlavə et');
}

/* ---- rate election ---- */
function formElection(cat, card){
  const ri = card ? card.rate_info : cat.rate;
  const target = card ? `ƏV: ${card.inv_no || card.name}` : `Kateqoriya: ${cat.name_az}`;
  // Two shortcuts, because these are the only two figures the law actually
  // names: the plain article 114.3 norm, and that norm times the
  // entrepreneur coefficient. Typing 37.5 by hand is where the rounding bug
  // used to bite, and the ceiling is the whole point of having a status.
  const quick = [['m.114.3 norması', ri.statutory_max]]
    .concat(parseFloat(ri.coefficient) > 1 ? [['yuxarı hədd', ri.ceiling]] : [])
    .map(([l, v]) => `<button type="button" class="ghost"
       style="padding:8px 12px;white-space:nowrap" onclick="SETRATE('${pctnum(v)}')"
       >${l} ${pct(v)}</button>`).join('');
  openModal('Amortizasiya dərəcəsi',
    `<input type="hidden" name="year" value="${REPORT.year}">
     <input type="hidden" name="category" value="${cat.code}">
     ${card ? `<input type="hidden" name="asset_id" value="${card.asset_id}">` : ''}
     <div class="h" style="margin-bottom:12px">${esc(target)}</div>
     <div class="fld"><label>Tətbiq olunan dərəcə</label>
       <div style="display:flex;gap:6px">
         <input name="applied_rate" value="${pctnum(ri.applied)}">${quick}</div>
       <div class="h">m.114.3 norması ${pct(ri.statutory_max)} · sahibkar əmsalı
         ×${ri.coefficient} · yuxarı hədd <strong>${pct(ri.ceiling)}</strong>.
         Faizlə yazın (məs. 25 və ya 37.5). Boş buraxsanız seçim silinir və
         norma (${pct(ri.statutory_max)}) tətbiq olunur.
         ${card ? '' : 'Ayrı-ayrı ƏV üçün seçilmiş fərdi dərəcə qüvvədə qalır.'}</div>
     </div>`,
    d => post('election.set', d));
}
window.SETRATE = v => {
  const box = document.querySelector('#mbody input[name=applied_rate]');
  box.value = v; box.focus();
};

/* ---- asset history ("лицевой счёт") ----
   Every year of one asset recomputed from the events, so it can never drift
   from the yearly reports. */
async function showHistory(id){
  closeDrawer();
  const slug = document.getElementById('client').value;
  const h = await (await fetch(`/api/asset-history?client=${slug}&asset_id=${id}`)).json();
  if (h.error) return fail(h.error);
  const a = h.asset;
  const last = h.years[h.years.length - 1];

  const ev = h.events.map(e => `<tr><td class="d">${esc(e.date)}</td>
    <td>${esc(e.kind)}</td><td class="num">${e.amount ? money(e.amount) : ''}</td>
    <td>${esc(e.note||'')}</td></tr>`).join('');

  const yr = h.years.map(y => `<tr class="${y.written_off ? 'warn'
      : y.disposal_type ? 'next' : ''}">
    <td><strong>${y.year}</strong>${y.closed ? '<span class="tag d">bağlı</span>' : ''}</td>
    <td class="num">${money(y.opening)}</td>
    <td class="num">${money(y.acquisition)}</td>
    <td class="num">${money(y.addition)}</td>
    <td class="num">${money(y.repair_capitalized)}</td>
    <td class="num">${money(y.disposed)}</td>
    <td class="num">${money(y.base)}</td>
    ${(parseFloat(y.rate)
        ? rateSplit(y.rate, y.rate_statutory, y.coefficient)
        : ['<span class="zero">—</span>', '<span class="zero">—</span>'])
      .map(v => `<td class="num">${v}</td>`).join('')}
    <td class="num">${parseFloat(y.rate) ? pct(y.rate)
      : '<span class="zero">—</span>'}</td>
    <td class="num"><strong>${money(y.depreciation)}</strong></td>
    <td class="num">${money(y.writeoff)}</td>
    <td class="num">${money(y.closing)}</td>
    <td class="num">${money(y.accumulated_end)}</td></tr>`).join('');

  const totDep = h.years.reduce((s,y) => s + parseFloat(y.depreciation), 0);
  const totAdd = h.years.reduce((s,y) => s + parseFloat(y.addition), 0);

  document.getElementById('view').innerHTML = `
    <div class="card" style="padding:16px 18px">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap">
        <div><h2 style="margin:0;font-size:17px;background:none;color:inherit;padding:0">
            ${esc(a.inv_no ? a.inv_no + ' · ' : '')}${esc(a.name)}</h2>
          <div class="hint">${esc(a.category_name)}
            ${a.in_date ? '· alınıb ' + esc(a.in_date) : ''}
            ${a.counterparty ? '· ' + esc(a.counterparty) : ''}</div></div>
        <button class="ghost" onclick="TAB='annual';syncTabs();render()">← hesabata qayıt</button>
      </div>
      <div class="kpis" style="margin:14px 0 0">
        <div class="kpi"><div class="k">İlkin dəyər</div>
          <div class="v">${money(a.cost)}</div></div>
        <div class="kpi"><div class="k">Dəyər artımı (cəmi)</div>
          <div class="v">${fmt.format(totAdd)}</div></div>
        <div class="kpi"><div class="k">Yığılmış amortizasiya</div>
          <div class="v">${fmt.format(totDep)}</div></div>
        <div class="kpi hi"><div class="k">Qalıq dəyər</div>
          <div class="v">${last ? fmt.format(parseFloat(last.closing)) : '—'}</div></div>
      </div>
    </div>

    <h3>İllər üzrə hərəkət</h3>
    <div class="card"><div class="scroll"><table><thead><tr>
      <th>İl</th><th class="num">Qalıq (əvvəl)</th><th class="num">Daxilolma</th>
      <th class="num">Dəyər artımı</th><th class="num">Kapital. təmir</th>
      <th class="num">Xaricetmə</th><th class="num">Baza</th>
      <th class="num">Norma (m.114.3)</th><th class="num">Əmsal</th>
      <th class="num">Dərəcə</th>
      <th class="num">Amortizasiya</th><th class="num">Silinmə</th>
      <th class="num">Qalıq (son)</th><th class="num">Yığılmış</th>
    </tr></thead><tbody>${yr}</tbody></table></div></div>

    <h3>Əməliyyatlar</h3>
    <div class="card"><div class="scroll"><table><thead><tr>
      <th>Tarix</th><th>Əməliyyat</th><th class="num">Məbləğ</th><th>Qeyd</th>
    </tr></thead><tbody>${ev}</tbody></table></div></div>

    <div class="note q">Bu hesabat saxlanmır — hər dəfə hadisələrdən yenidən
      hesablanır, ona görə illik hesabatlarla heç vaxt ayrıla bilməz (§2).</div>`;
  document.getElementById('side').innerHTML = '';
}
