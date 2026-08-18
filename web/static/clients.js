/* A fresh install has no clients at all. Say so and offer the one action
   that makes sense, instead of an empty screen. */
let NEWCLIENT = null;

function welcome(){
  const box = document.getElementById('error');
  box.style.display = 'block';
  box.style.background = '#eef3f9';
  box.style.borderColor = '#8fa8c8';
  box.style.color = '#2c4a70';
  box.innerHTML = `<strong>Hələ heç bir müştəri yoxdur</strong><br>
    Başlamaq üçün müştəri yaradın — proqram bütün lazımi faylları özü
    yaradacaq. Sonra ƏV-ləri əl ilə və ya Excel-dən idxal edərək əlavə edin.
    <div class="acts" style="margin:10px 0 0">
      <button onclick="formClient()">Yeni müştəri yarat</button>
    </div>`;
  document.getElementById('view').innerHTML = '';
  document.getElementById('side').innerHTML = '';
  document.getElementById('kpis').innerHTML = '';
  document.getElementById('carry').innerHTML = '';
  document.getElementById('sub').textContent = '';
}

function formClient(){
  const y = new Date().getFullYear();
  openModal('Yeni müştəri',
    fld('client_name','Müştərinin adı',{req:true,placeholder:'«Demo» MMC'}) +
    `<div class="row2">
      ${fld('voen','VÖEN',{placeholder:'1400123456'})}
      ${fld('start_year','Uçotun başlanğıc ili',{type:'number',value:y,req:true,
            hint:'Ən erkən il, hansı üçün məlumat var'})}</div>` +
    fld('status','Sahibkarlıq statusu',{type:'select',req:true,options:
      [['mikro','Mikro sahibkar (×2)'],['kicik','Kiçik sahibkar (×1.5)'],
       ['orta','Orta sahibkar (×1)'],['iri','İri sahibkar (×1)']]
      .map(([v,t]) => `<option value="${v}" ${v==='orta'?'selected':''}>${t}</option>`).join('')}) +
    `<div class="h">Bütün fayllar <code>clients/&lt;ad&gt;/</code> qovluğunda
      yaradılacaq. Sonradan hər şeyi dəyişmək olar.</div>`,
    async d => { NEWCLIENT = (await post('client.create', d)).result; }, 'Yarat');
}

/* Moving a client to another machine.
   Copying the folder alone is not enough and fails silently: the norms live
   next to the engine, and an older engine there does not read files added
   later. The archive carries both and the import compares before writing. */
function formBaza(){
  const slug = document.getElementById('client').value;
  openModal('Bazanın köçürülməsi',
    `<div class="fld"><label>Bu müştərini arxivləşdirin</label>
      <div class="h" style="margin:0 0 8px">Müştərinin bütün faylları,
        istifadə olunan normalar və hansı mühərriklə yazıldığı — bir fayl.</div>
      ${slug ? `<a class="btn" style="border:1px solid var(--line)"
        href="/api/client-archive?client=${slug}">⬇ «${esc(slug)}» arxivini yüklə</a>`
        : '<div class="h">Müştəri seçilməyib.</div>'}</div>
    <hr style="border:0;border-top:1px solid var(--line);margin:16px 0">
    <div class="fld"><label>Başqa maşından gələn arxivi yükləyin</label>
      <input type="file" id="bazafile" accept=".zip"></div>
    <div id="bazainfo"></div>`,
    async () => {
      const f = document.getElementById('bazafile').files[0];
      if (!f) throw new Error('Fayl seçilməyib');
      const b64 = await new Promise(res => {
        const fr = new FileReader();
        fr.onload = () => res(fr.result.split(',')[1]);
        fr.readAsDataURL(f);
      });
      const info = (await post('client.import', {b64, dry_run: true})).result;
      if (info.blocking.length) throw new Error(info.blocking.join(' '));
      const m = info.manifest;
      document.getElementById('bazainfo').innerHTML = `
        <div class="note q"><strong>${esc(m.client_name)}</strong> ·
          VÖEN ${esc(m.voen)} · mühərrik ${esc(m.engine_version)} ·
          format v${m.format_version}<br>
          ${esc(m.exported_at)} tarixində ${esc(m.exported_by)} tərəfindən
          ixrac edilib, ${Object.keys(m.files).length} fayl.</div>
        ${info.notes.map(n => `<div class="note">${esc(n)}</div>`).join('')}
        ${fld('slug','Qovluğun adı',{value:info.exists ? '' : info.suggested_slug,
              req:true, placeholder:info.suggested_slug})}
        <label style="font-size:12.5px;display:flex;gap:8px;align-items:flex-start">
          <input type="checkbox" name="apply_norms" checked style="width:auto;margin-top:3px">
          <span>Arxivdəki normaları tətbiq et — <strong>bütün müştərilərə
            təsir edir</strong>, çünki normalar proqramın yanındadır.</span></label>`;
      MSUBMIT = async d => {
        const r = await post('client.import',
          {b64, slug: d.slug, apply_norms: !!d.apply_norms});
        NEWCLIENT = r.result.slug;
      };
      document.getElementById('msubmit').textContent = 'İdxal et';
      throw new Error('__stay__');
    }, 'Arxivi oxu');
}

function needStatus(year){
  const box = document.getElementById('error');
  box.style.display = 'block';
  box.style.background = '#eef3f9';
  box.style.borderColor = '#8fa8c8';
  box.style.color = '#2c4a70';
  box.innerHTML = `<strong>${year} ili hələ qurulmayıb</strong><br>
    Sahibkarlıq statusu olmadan normaya tətbiq olunan əmsal məlum deyil, ona
    görə hesablama başlamır.
    <div class="acts" style="margin:10px 0 0">
      <button onclick="formStatus(${year})">${year} üçün statusu təyin et</button>
    </div>`;
  document.getElementById('view').innerHTML = '';
  document.getElementById('side').innerHTML = '';
  document.getElementById('kpis').innerHTML = '';
}

/* The one act in the program that destroys facts in bulk, so it is spelled
   out rather than confirmed with a yes/no: what goes, what stays, and the
   name typed back by hand. The mis-click it guards against is real -- the
   button sits among ordinary settings.

   Not a hidden feature: without it "I imported, found mistakes, I want to
   start again" had no answer inside the program at all. Import appends and
   should keep appending -- "this file replaces everything" is a far bigger
   claim than "these rows are assets" -- so starting over is its own act. */
function formClearAssets(){
  const slug = document.getElementById('client').value;
  const n = REPORT ? REPORT.categories.reduce((s, c) => s + c.cards.length, 0) : 0;
  openModal(`Bütün ƏV-ləri sil — ${esc(REPORT.client_name || slug)}`,
    `<div class="note"><strong>${n} ƏV</strong> və onlara bağlı hər şey
      silinəcək: açılış qalıqları, xaricetmələr, təmirlər, dəyər artımları,
      500/5% qərarları və ayrı-ayrı ƏV üçün seçilmiş dərəcələr.
      <br><br>Qalacaq: firmanın özü, illər üzrə sahibkarlıq statusu,
      kateqoriya üzrə dərəcə seçimləri və «Növ» siyahısı.
      <br><br>Əməliyyatdan əvvəl ehtiyat nüsxə götürülür
      (<code>backups/${esc(slug)}/</code>), changelog-a yazılır.</div>
     ${fld('confirm','Təsdiq üçün müştərinin adını yazın',
           {req:true, placeholder:REPORT.client_name || slug})}
     <div class="h">«${esc(REPORT.client_name || slug)}» və ya
       «${esc(slug)}» — hər ikisi qəbul edilir.</div>`,
    d => post('asset.clear', d), 'Sil');
}

/* ---- taxpayer status ---- */
/* Everything about the FIRM, as opposed to its assets. The creation form
   asked for these once and then there was nowhere to go: a typo in the name,
   the wrong VÖEN or the wrong status was permanent. */
function formSettings(){
  if (!REPORT) return fail('Əvvəlcə müştəri seçin');
  const slug = document.getElementById('client').value;
  openModal(`Firmanın parametrləri — ${esc(REPORT.client_name || slug)}`,
    fld('client_name','Firmanın adı',{value:REPORT.client_name,req:true}) +
    `<div class="row2">
      ${fld('voen','VÖEN',{value:REPORT.voen})}
      ${fld('start_year','Başlanğıc il',{type:'number',value:REPORT.start_year,req:true,
            hint:'Bundan əvvəlki illər göstərilmir.'})}</div>
    <div class="fld"><label>Sahibkarlıq statusu — ${REPORT.year}</label>
      <div class="h" style="margin:0 0 8px">Status <strong>il üzrə</strong>
        saxlanılır: dövriyyə və işçi sayı hər il yenidən qiymətləndirilir,
        ona görə keçmiş illər dəyişmir.</div>
      ${REPORT.is_closed
        ? `<div class="note">${REPORT.year} bağlıdır — status dəyişdirilmir.</div>`
        : `<button type="button" class="btn" style="border:1px solid var(--line)"
             onclick="closeModal(); formStatus(${REPORT.year})"
             >${esc(REPORT.status_name)} — dəyiş</button>`}</div>
    <div class="note q">Qovluğun adı — <code>${esc(slug)}</code> — dəyişmir:
      onunla ehtiyat nüsxələr və arxivlər bağlıdır. Başqa ad lazımdırsa,
      «⇄ Baza» ilə ixrac edib yeni adla idxal edin.</div>
    <hr style="border:0;border-top:1px solid var(--line);margin:14px 0">
    <div class="fld"><label>Sıfırdan başlamaq</label>
      <div class="h" style="margin:0 0 8px">İdxal mövcud kartları
        <strong>silmir, üstünə əlavə edir</strong>. Cədvəli düzəldib yenidən
        gətirmək üçün əvvəlcə kartları təmizləyin.</div>
      <button type="button" class="ghost" style="border-color:var(--neg);
        color:var(--neg)" onclick="closeModal(); formClearAssets()"
        >Bütün ƏV-ləri sil…</button></div>`,
    d => post('client.update', d));
}

/* The four statuses and what each multiplies the norm by. Comes from the
   report, i.e. from the rate table, because a coefficient is a figure of the
   law and §5.1-bis keeps those out of code. Before the first report exists
   there is nothing to compute a ceiling for, so plain labels will do. */
const STATUS_FALLBACK = {mikro:{name:'Mikro sahibkar'}, kicik:{name:'Kiçik sahibkar'},
                         orta:{name:'Orta sahibkar'}, iri:{name:'İri sahibkar'}};

function formStatus(year){
  // Reachable before any report exists, so it cannot read REPORT.
  const y = year || REPORT.year;
  const cur = REPORT ? REPORT.status : 'mikro';
  const COEF = (REPORT && REPORT.coefficients) || STATUS_FALLBACK;

  // Setting the status is the moment the right to the coefficient appears,
  // so it is the moment to ask whether to use it. The engine never applies it
  // by itself (§5.2) -- doubling a client's depreciation is not a decision a
  // program makes -- but the election used to live on another screen
  // entirely, which is how "I set kiçik and the 1.5 never applied" happens.
  //
  // Per CATEGORY, not one switch for everything: the answer is often "yes for
  // the cars, no for the building". Nothing is ticked by default, and a rate
  // chosen for an individual asset is more specific and survives untouched,
  // which is how "all the cars at 1.5 except this one" stays expressible.
  const cats = (REPORT ? REPORT.categories : []).filter(c => c.cards.length);
  const coefBox = cats.length ? `<div class="fld" id="coefbox">
      <label>Əmsalı tətbiq et — kateqoriya üzrə</label>
      ${cats.map(c => `<label data-max="${c.rate.statutory_max}"
        style="display:flex;gap:8px;align-items:center;padding:3px 0">
        <input type="checkbox" name="apply_cat" value="${c.code}" style="width:auto">
        <span>${esc(c.name_az)} — <span class="cur"></span></span></label>`).join('')}
      <div class="h">Qeyd edilməyən kateqoriyalar m.114.3 norması ilə qalır.
        Ayrı-ayrı ƏV üçün seçilmiş fərdi dərəcələr dəyişmir.</div>
    </div>` : '';

  openModal(`Sahibkarlıq statusu — ${y}`,
    `<input type="hidden" name="year" value="${y}">` +
    fld('status','Status',{type:'select',req:true,options:
      Object.entries(COEF).map(([v,s]) => `<option value="${v}"
        ${v===cur?'selected':''}>${esc(s.name)}${s.coefficient
          ? ` (×${esc(s.coefficient)})` : ''}</option>`).join('')}) +
    fld('basis','Əsas',{placeholder:'İllik dövriyyə, işçi sayı…'}) +
    `<div class="fld"><label style="display:flex;gap:8px;align-items:flex-start">
       <input type="checkbox" name="no_coefficient" style="width:auto;margin-top:3px"
         ${REPORT && REPORT.use_coefficient === false ? 'checked' : ''}>
       <span><strong>Əmsalsız hesabla</strong>
         <div class="h" style="margin:2px 0 0">Sahibkarlıq əmsalından imtina:
           yuxarı hədd m.114.3 normasında qalır və hesabat əmsalı təklif etmir.
           Status faktdır, əmsaldan istifadə isə qərardır — ayrıca saxlanılır.</div>
       </span></label></div>` + coefBox,
    d => post('status.set', {...d, use_coefficient: !d.no_coefficient,
      // FormData collapses repeated names, so the ticks are read from the DOM.
      apply_coefficient_to: [...document.querySelectorAll(
        '#mbody input[name=apply_cat]:checked')].map(x => x.value)}));

  const sel = document.querySelector('#mbody select[name=status]');
  const off = document.querySelector('#mbody input[name=no_coefficient]');
  window.STATUSCOEF = () => {
    const box = document.getElementById('coefbox');
    if (!box) return;
    const c = off.checked ? 1 : parseFloat((COEF[sel.value] || {}).coefficient || 1);
    box.style.display = c > 1 ? '' : 'none';
    box.querySelectorAll('[data-max]').forEach(el => {
      const max = parseFloat(el.dataset.max), ceil = Math.min(max * c, 1);
      el.querySelector('.cur').innerHTML =
        `${pct(max)} × ${c} = <strong>${pct(ceil)}</strong>`;
    });
  };
  sel.onchange = off.onchange = STATUSCOEF;
  STATUSCOEF();
}

