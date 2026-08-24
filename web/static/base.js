const fmt = new Intl.NumberFormat('az-AZ',{minimumFractionDigits:2,maximumFractionDigits:2});
const money = s => { const n = parseFloat(s); return n === 0
  ? '<span class="zero">—</span>' : fmt.format(n); };
/* A rate is printed with the digits it actually has. Rounding to a whole
   number was not cosmetic: the small-entrepreneur ceiling 25% x 1.5 = 37.5%
   appeared everywhere as "38%", and the rate form prefilled itself from the
   same rendering -- so opening it and pressing save offered 38%, which the
   engine rightly refuses as above the very ceiling it was showing. */
const pctnum = s => String(Math.round(parseFloat(s) * 1e6) / 1e4);
const pct = s => pctnum(s) + '%';
const esc = s => String(s??'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

let CTX = null, REPORT = null, TAB = 'annual', FILTER = '', CATFILTER = '';
// The client's own grouping (§13.1). View state, like CATFILTER -- it
// narrows what is shown and never what is computed.
let GRPFILTER = '';
function fail(msg){
  const box = document.getElementById('error');
  // needStatus() tints the same box blue; reset it back to the error look.
  box.style.background = ''; box.style.borderColor = ''; box.style.color = '';
  box.style.display = 'block';
  box.innerHTML = `<strong>Hesablama dayandırıldı</strong><br>${esc(msg)}`;
  document.getElementById('view').innerHTML = '';
  document.getElementById('side').innerHTML = '';
  document.getElementById('kpis').innerHTML = '';
}

async function boot(){
  // §2.1 — never leave a blank screen: any failure here must be visible.
  try {
    const r = await fetch('/api/context');
    CTX = await r.json();
    if (!r.ok || !CTX.clients) return fail(CTX.error || 'context alınmadı');
  } catch (e) { return fail(e.message); }
  const cs = document.getElementById('client');
  cs.innerHTML = CTX.clients.map(c =>
    `<option value="${c.slug}">${esc(c.name)} · ${esc(c.slug)}</option>`).join('');
  document.getElementById('ver').textContent = 'engine ' + CTX.engine_version;
  cs.onchange = () => { fillYears(); load(); };
  document.getElementById('year').onchange = load;
  fillYears(); load();
  checkUpdate();      // fire-and-forget -- must never delay or block boot()
  checkPendingVerify(); // same -- must never delay or block boot()
}

/* Once per page load, never a repeating timer (§9): a worker who leaves the
   tab open all day should not have it quietly polling GitHub in the
   background. A failed check -- offline, GitHub unreachable -- is silent on
   purpose: it is a courtesy, not something an accountant doing tax work
   should ever see an error about. */
async function checkUpdate(){
  try {
    const r = await fetch('/api/update-check');
    const u = await r.json();
    if (!u.available) return;
    const ver = document.getElementById('ver');
    ver.classList.add('upd');
    ver.textContent = `engine ${u.current} → ${u.latest} var`;
    ver.onclick = () => openUpdateModal(u);
  } catch (e) { /* quiet -- see above */ }
}

function openUpdateModal(u){
  openModal(`Yeniləmə — ${u.latest}`,
    `<div class="h">Hazırkı versiya <strong>${esc(u.current)}</strong>,
      yeni versiya <strong>${esc(u.latest)}</strong> mövcuddur.</div>
     <div class="h" style="margin-top:8px">Müştəri qovluqları
      (<code>clients/</code>), normalar (<code>rates.tsv</code> və s.) və
      bəkaplar toxunulmaz qalır — yalnız proqramın öz faylları yenilənir.</div>`,
    async () => {
      const r = await fetch('/api/update-apply', {method: 'POST'});
      const j = await r.json();
      if (!r.ok || !j.ok) throw new Error(j.error || 'Yeniləmə alınmadı');
      document.getElementById('mtitle').textContent = 'Hazırdır';
      document.getElementById('mbody').innerHTML = `<div class="h">${esc(j.message)}</div>`;
      document.getElementById('msubmit').style.display = 'none';
      document.querySelector('#mform .foot .ghost').textContent = 'Bağla';
      // Stays open to show the message above -- the same escape hatch the
      // import wizard uses to hold the modal across a step (base.js
      // submitModal): any message but this one is treated as a real error.
      throw new Error('__stay__');
    },
    'Yüklə və qur');
}

/* The post-update check (§9, web/app.py's _run_startup_verify): this
   process already ran it once, at its own startup, against every closed
   year of every client. This just asks for the result and shows it -- once
   per page load, like checkUpdate, and just as quiet on a network-shaped
   failure. Unlike checkUpdate this is not a courtesy: a "not ok" result
   means a filed year's numbers no longer agree with what was sealed, and it
   stays on screen (in #updateProblem, outside what load()/fail() rebuild)
   until the accountant acts on it or dismisses it. */
async function checkPendingVerify(){
  try {
    const r = await fetch('/api/update-status');
    const u = await r.json();
    if (!Object.keys(u).length) return;   // nothing pending
    u.ok ? showVerifyOk(u) : showVerifyProblem(u);
  } catch (e) { /* quiet -- see above */ }
}

function showVerifyOk(u){
  const box = document.getElementById('updateProblem');
  box.className = '';
  box.style.cssText =
    'display:block;background:#eef3f9;border:1px solid #8fa8c8;' +
    'color:#2c4a70;padding:10px 16px;border-radius:var(--radius);margin-bottom:12px';
  box.innerHTML = `Yeniləmə yoxlanıldı (${esc(u.from_version)} →
    ${esc(u.to_version)}): bağlı illərin rəqəmləri öncəki nəticələrlə
    üst-üstə düşür.
    <button class="ghost" style="margin-left:10px"
      onclick="document.getElementById('updateProblem').style.display='none'"
      >Bağla</button>`;
}

function showVerifyProblem(u){
  VERIFY_PROBLEM = u;
  const box = document.getElementById('updateProblem');
  box.style.cssText = 'display:block;margin-bottom:12px';
  box.className = 'err';
  const total = Object.values(u.mismatches).reduce((n, l) => n + l.length, 0);
  box.innerHTML = `<strong>Yeniləmədən sonra ${total} uyğunsuzluq
    tapıldı</strong> (${esc(u.from_version)} → ${esc(u.to_version)}) — bağlı
    illərin rəqəmləri artıq təqdim edilmiş bəyannamədəki ilə üst-üstə
    düşmür.
    <div class="acts" style="margin-top:8px">
      <button class="danger" onclick="openVerifyProblemModal()"
        >Təfərrüat və geri qaytarma</button>
    </div>`;
}

let VERIFY_PROBLEM = null;

function openVerifyProblemModal(){
  const u = VERIFY_PROBLEM;
  const rows = Object.entries(u.mismatches)
    .flatMap(([slug, list]) => list.map(m => ({slug, ...m})));
  const shown = rows.slice(0, 20);
  const table = `<table style="width:100%;font-size:12.5px;border-collapse:collapse">
    <tr><th style="text-align:left">Müştəri</th><th style="text-align:left">İl</th>
      <th style="text-align:left">Obyekt</th><th style="text-align:right">Saxlanmış</th>
      <th style="text-align:right">Yenidən hesablanmış</th></tr>
    ${shown.map(m => `<tr><td>${esc(m.slug)}</td><td>${m.year}→${m.year + 1}</td>
      <td>${esc(m.asset_id)}</td><td style="text-align:right">${esc(m.stored)}</td>
      <td style="text-align:right">${esc(m.recomputed)}</td></tr>`).join('')}
  </table>${rows.length > shown.length
    ? `<div class="h">... və daha ${rows.length - shown.length}</div>` : ''}`;
  openModal(`Yeniləmə problemi — ${esc(u.from_version)} → ${esc(u.to_version)}`,
    `<div class="h">Bağlı illərin bəzi obyektləri yeniləmədən sonra artıq
      təqdim edilmiş bəyannamədəki rəqəmlə üst-üstə düşmür. Ən təhlükəsiz
      addım — köhnə versiyaya geri qayıtmaq; bu, yeni versiyanın öz faylını da
      bəkaplayır, ona görə geri qaytarma özü də geri dönən əməliyyatdır.</div>
     <div style="max-height:260px;overflow:auto;margin-top:10px">${table}</div>`,
    async () => {
      const r = await fetch('/api/update-rollback', {method: 'POST'});
      const j = await r.json();
      if (!r.ok || !j.ok) throw new Error(j.error || 'Geri qaytarma alınmadı');
      document.getElementById('updateProblem').style.display = 'none';
      document.getElementById('mtitle').textContent = 'Hazırdır';
      document.getElementById('mbody').innerHTML = `<div class="h">${esc(j.message)}</div>`;
      document.getElementById('msubmit').style.display = 'none';
      document.querySelector('#mform .foot .ghost').textContent = 'Bağla';
      throw new Error('__stay__');
    },
    'Geri qaytar');
}

function fillYears(){
  const c = CTX.clients.find(x => x.slug === document.getElementById('client').value);
  const ys = document.getElementById('year');
  if (!c){ ys.innerHTML = ''; return; }
  ys.innerHTML = (c.years || []).map(y =>
    `<option value="${y}">${y}${c.closed_years.includes(y) ? ' · bağlı' : ''}</option>`).join('');
  // Open on a year that computes, not merely the newest one present.
  if (c.years && c.years.length) ys.value = c.default_year || c.years[c.years.length-1];
}

async function load(){
  const slug = document.getElementById('client').value;
  if (!slug) return welcome();
  const year = document.getElementById('year').value;
  const cinfo = CTX.clients.find(x => x.slug === slug);
  if (cinfo && cinfo.error) return fail(cinfo.error);
  document.getElementById('export').href = `/api/export?client=${slug}&year=${year}`;
  const r = await fetch(`/api/report?client=${slug}&year=${year}`);
  const data = await r.json();
  // §2.1 — a failed calculation is shown, never replaced by zeros.
  // A missing setup step is not an error to stare at: offer the fix.
  if (!r.ok && data.need === 'status') return needStatus(data.year);
  if (!r.ok) return fail(data.error);
  document.getElementById('error').style.display = 'none';
  REPORT = data;
  // The status was only ever reachable while it was MISSING, so picking the
  // wrong one when creating a client left no way back -- the fact was on
  // screen but not editable. Put the control on the fact itself.
  document.getElementById('sub').innerHTML =
    `VÖEN ${esc(data.voen)} · ` + (data.is_closed
      ? `${esc(data.status_name)} · İL BAĞLIDIR`
      : `<button type="button" class="linkish" title="${data.year} üçün statusu dəyiş"
           onclick="formStatus(${data.year})">${esc(data.status_name)}</button>`);
  const n = data.warnings.length + data.open_questions.length;
  document.getElementById('notecount').textContent = n ? `(${n})` : '';
  // Only the undecided ones are counted: a decision already taken is not
  // something still asking to be dealt with.
  const undecided = data.categories.flatMap(c => c.cards)
    .filter(c => c.threshold_hit && !c.written_off).length;
  document.getElementById('thrcount').textContent = undecided ? `(${undecided})` : '';
  render();
}

function render(){
  const d = REPORT, t = visibleTotals(d);
  // Silent once was the failure mode §13.1 already names for the table's own
  // total row: a narrowed sum that looks exactly like the full one. The tiles
  // borrow the same wording so a filtered view never claims to be the whole
  // company without saying so.
  const narrowed = FILTER || GRPFILTER;
  document.getElementById('kpisnote').textContent = narrowed
    ? 'Rəqəmlər süzgəcə görədir, bütün ƏV-ni əhatə etmir'
    : CATFILTER
      ? `Rəqəmlər seçilmiş kateqoriyaya aiddir: ${
          (d.categories.find(c => c.code === CATFILTER) || {}).name_az || ''}`
      : '';
  document.getElementById('kpis').innerHTML = [
    ['Qalıq — il əvvəli', t.opening, ''],
    ['Daxilolma', t.acquisition, ''],
    ['Xaricetmə', t.disposed, ''],
    ['Amortizasiya', t.depreciation, 'hi'],
    ['Silinmə 500/5%', t.writeoff, ''],
    ['Qalıq — il sonu', t.closing, ''],
  ].map(([k,v,c]) => `<div class="kpi ${c}"><div class="k">${k}</div>
      <div class="v">${fmt.format(parseFloat(v))}</div></div>`).join('');

  renderCarry(d);
  document.getElementById('hint').textContent =
    TAB === 'monthly' ? 'İllik məbləğ / 12 · yuvarlaqlaşdırma qalığı dekabrda'
    : TAB === 'annual' ? 'Sətrə klikləyin — hesablamanın gedişi'
    : TAB === 'threshold' ? 'VM m.114.8 · qərar birdəfəlik, bütün seçilmişlərə'
    : TAB === 'declaration' ? 'Mənfəət vergisi bəyannaməsinə köçürülən məbləğlər'
    : TAB === 'ratematrix' ? 'Tətbiq edilmiş dərəcələr · illər üzrə müqayisə'
    : '';

  renderSide(d);
  document.getElementById('view').innerHTML =
    TAB === 'annual' ? viewAnnual(d) : TAB === 'monthly' ? viewMonthly(d)
    : TAB === 'declaration' ? viewDeclaration(d)
    : TAB === 'repair' ? viewRepair(d)
    : TAB === 'threshold' ? viewThreshold(d)
    : TAB === 'norms' || TAB === 'ratematrix'
      ? '<div class="card" style="padding:16px">yüklənir…</div>'
    : viewNotes(d);
  if (TAB === 'norms') loadNorms();
  if (TAB === 'ratematrix') loadRateMatrix();
}
/* ==================== data entry ==================== */

let MSUBMIT = null;

async function post(action, payload){
  const r = await fetch('/api/action', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({client: document.getElementById('client').value, action, payload})
  });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || 'xəta');
  return j;
}

function openModal(title, body, onSubmit, submitLabel){
  // the import wizard repurposes this button as "back"; restore it
  const cancel = document.querySelector('#mform .foot .ghost');
  cancel.textContent = 'İmtina'; cancel.onclick = closeModal;
  document.getElementById('mtitle').textContent = title;
  document.getElementById('mbody').innerHTML = body;
  document.getElementById('ferr').style.display = 'none';
  document.getElementById('msubmit').textContent = submitLabel || 'Yadda saxla';
  MSUBMIT = onSubmit;
  document.getElementById('modal').classList.add('open');
  const first = document.querySelector('#mbody input,#mbody select');
  if (first) first.focus();
}
const closeModal = () => {
  document.getElementById('modal').classList.remove('open'); MSUBMIT = null;
};

async function submitModal(e){
  e.preventDefault();
  const box = document.getElementById('ferr');
  const btn = document.getElementById('msubmit');
  const data = Object.fromEntries(new FormData(document.getElementById('mform')));
  btn.disabled = true;
  try {
    await MSUBMIT(data);
    closeModal();
    CTX = await (await fetch('/api/context')).json();
    // A newly created client is not in the picker yet; rebuild and select it.
    //
    // Rebuilding the options drops the selection back to the FIRST client, so
    // whoever was being worked on has to be put back by hand. Without that,
    // saving an asset moved the screen to another firm entirely -- the
    // alphabetically first one -- and the next card would be entered there.
    // Nothing was lost, but the write landed somewhere the user was not
    // looking, which is the silent kind of wrong (§2.1).
    const cs = document.getElementById('client'), ys = document.getElementById('year');
    const keep = cs.value, keepYear = ys.value;
    cs.innerHTML = CTX.clients.map(c =>
      `<option value="${c.slug}">${esc(c.name)} · ${esc(c.slug)}</option>`).join('');
    if (NEWCLIENT){ cs.value = NEWCLIENT; NEWCLIENT = null; fillYears(); }
    else if (keep){
      cs.value = keep;
      // The year list can move with the write -- a purchase makes a year
      // reachable, closing one adds its mark -- so it is rebuilt as well. But
      // the year on screen is where the user is, and a save must not carry
      // them off it, so it is restored whenever it still exists.
      fillYears();
      if ([...ys.options].some(o => o.value === keepYear)) ys.value = keepYear;
    }
    await load();
  } catch (err) {
    // A wizard step transition is not a failure -- keep the modal open.
    if (err.message === '__stay__'){ btn.disabled = false; return false; }
    // The store rolls itself back on failure, so the message is the whole story.
    box.textContent = err.message; box.style.display = 'block';
  } finally { btn.disabled = false; }
  return false;
}

const val = v => esc(v == null ? '' : v);
const fld = (name, label, o = {}) => `<div class="fld">
  <label>${label}</label>
  ${o.type === 'select'
    ? `<select name="${name}" ${o.req ? 'required' : ''}>${o.options}</select>`
    : `<input name="${name}" type="${o.type || 'text'}" value="${val(o.value)}"
        ${o.req ? 'required' : ''} ${o.step ? `step="${o.step}"` : ''}
        ${o.min != null ? `min="${o.min}"` : ''}
        ${o.placeholder ? `placeholder="${o.placeholder}"` : ''}>`}
  ${o.hint ? `<div class="h">${o.hint}</div>` : ''}</div>`;

/* Categories offered for a NEW RATE ROW (rates.js) or a BULK IMPORT
   (import.js's impCats). `it` is left out of both, but no longer because the
   engine lacks a schedule for it (it has one -- m.115.6-1, §10):

   * a new rate row has nothing to say about `it` -- no percentage rate, no
     repair limit, nothing rates.tsv carries a column for; its schedule comes
     from the lease contract on the card, like `qma-m`'s FİM;
   * bulk import has nowhere to carry the m.115.6-1 confirmation (not
     reimbursed, not offset against rent) that a single card asks for at
     creation -- see mutate.assets.create_asset and mutate.imports, which
     refuses the category outright rather than silently dropping the check. */
const cardCats = () => CTX.categories.filter(c => c.code !== 'it');

const catOptions = sel => cardCats()
  .map(c => `<option value="${c.code}" ${c.code === sel ? 'selected' : ''}>
    ${esc(c.name_az)}</option>`).join('');

/* Categories a CARD may be created in -- every one the engine has a schedule
   for, `it` included. QMA belongs here for the same reason: art. 118.2
   deducts it as amortisation under art. 114, so it is entered, carried and
   disposed of like any other card (§4); `it` is entered the same way, one
   card per capitalised repair-year (m.115.6-1, §10). */
const assetCats = () => CTX.categories;

const assetCatOptions = sel => assetCats()
  .map(c => `<option value="${c.code}" ${c.code === sel ? 'selected' : ''}>
    ${esc(c.name_az)}</option>`).join('');

/* Is this code a qeyri-maddi aktiv? Asked in several places, so the answer
   comes from the engine's own classification rather than from the shape of
   the code string. */
const isQma = code => (CTX.categories.find(c => c.code === code) || {}).kind === 'qma';

/* The tab strip follows TAB rather than the other way round, so a jump made
   from inside a view (a declaration line to the table behind it) does not
   leave the strip pointing at the tab the reader just left. */
function syncTabs(){
  document.querySelectorAll('.tabs button').forEach(
    x => x.setAttribute('aria-selected', String(x.dataset.tab === TAB)));
}
