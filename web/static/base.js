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
  const d = REPORT, t = d.totals;
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
    const cs = document.getElementById('client');
    cs.innerHTML = CTX.clients.map(c =>
      `<option value="${c.slug}">${esc(c.name)} · ${esc(c.slug)}</option>`).join('');
    if (NEWCLIENT){ cs.value = NEWCLIENT; NEWCLIENT = null; fillYears(); }
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

/* Categories a card may be created in: every one the engine has a schedule
   for. QMA belongs here -- art. 118.2 deducts it as amortisation under art.
   114, so it is entered, carried and disposed of like any other card (§4).

   `it` is the one left out, and deliberately: its term is the lease contract
   (§12.5) and the engine has no schedule for it yet. It used to be offered
   all the same, and picking it stopped the WHOLE year from computing -- every
   other card with it. An option that cannot be honoured is not an option. */
const cardCats = () => CTX.categories.filter(c => c.code !== 'it');

const catOptions = sel => cardCats()
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
