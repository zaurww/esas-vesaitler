/* ---- the client's own grouping, beside the tax category (§13.1) -------

   The tax category belongs to the law: seven codes, fixed, and every figure
   in the return is aggregated by them. «Növ» belongs to the client:
   notebooks, servers, printers -- all of them `yt` at one and the same rate,
   and the office still needs them apart.

   The line between the two is the whole design, and it runs here: a group
   never carries a rate, a repair limit or any other number. It is a way of
   CUTTING the report, not a tax fact. The moment it acquired a rate it would
   be a substitute category and the aggregation by art. 114/115 would stop
   being universal -- exactly what the fixed enum in §4 protects.

   Kept as a dictionary (groups.tsv) rather than free text on the card, for
   the same reason `category` is an enum: "Serverlər" and "Serverler" typed on
   two different days would silently become two groups, and a report split in
   half is worse than no report (§2.1). Renaming is then one edit here, not
   forty in the cards. ------------------------------------------------- */

const NOGROUP = '__none__';                    // the cards in no group at all

const GROUPS = () => (REPORT && REPORT.groups) || [];
const groupName = id => (GROUPS().find(g => g.group_id === id) || {}).name || '';

/* Every card of the year, flat: a group cuts ACROSS categories, so this is
   the list to count over and to choose from. */
const allCards = () => (REPORT ? REPORT.categories.flatMap(c => c.cards) : []);
const groupCount = id => allCards().filter(
  c => id === NOGROUP ? !c.group_id : c.group_id === id).length;

/* ---- the dictionary ---- */
function formGroups(){
  const list = GROUPS();
  const rows = list.map(g => `<tr>
      <td><strong>${esc(g.name)}</strong>
        ${g.note ? `<div class="h">${esc(g.note)}</div>` : ''}</td>
      <td class="num">${groupCount(g.group_id)}</td>
      <td class="acts" style="justify-content:flex-end">
        <button type="button" class="tagbtn"
          onclick="formAssign('${g.group_id}')">ƏV seç</button>
        <button type="button" class="tagbtn"
          onclick="formGroupEdit('${g.group_id}')">adı</button>
        <button type="button" class="tagbtn"
          onclick="formGroupDelete('${g.group_id}')">sil</button></td>
    </tr>`).join('');
  const none = groupCount(NOGROUP);

  openModal('Növlər — müştərinin öz bölgüsü', `
    <div class="note">Növ <strong>heç bir rəqəmə təsir etmir</strong>: dərəcə,
      m.115 limiti və bəyannamə sətirləri həmişə vergi kateqoriyası üzrə
      hesablanır. Növ hesabatı kəsmək üçündür — süzgəc, aralıq yekunlar və
      Excel-də ayrıca sütun.</div>
    ${list.length ? `<div class="scroll" style="max-height:38vh"><table>
      <thead><tr><th>Ad</th><th class="num">ƏV</th><th></th></tr></thead>
      <tbody>${rows}${none ? `<tr><td class="h">— növsüz —</td>
        <td class="num">${none}</td>
        <td class="acts" style="justify-content:flex-end"><button type="button"
          class="tagbtn" onclick="formAssign('${NOGROUP}')">növü sil</button></td>
        </tr>` : ''}</tbody></table></div>`
      : `<p class="h">Hələ növ yaradılmayıb. Məsələn: «Noutbuklar»,
         «Server avadanlığı», «Printerlər».</p>`}
    <hr style="border:0;border-top:1px solid var(--line);margin:14px 0">
    ${fld('name','Yeni növ',{placeholder:'məs. Server avadanlığı'})}`,
    async d => {
      if (!(d.name || '').trim()) throw new Error('Növün adı boş ola bilməz');
      return post('group.create', {name: d.name});
    }, '+ Növ əlavə et');
}

function formGroupEdit(gid){
  const g = GROUPS().find(x => x.group_id === gid);
  openModal(`Növ — ${g.name}`,
    `<input type="hidden" name="group_id" value="${gid}">
     ${fld('name','Ad',{value:g.name,req:true})}
     ${fld('note','Qeyd',{value:g.note})}
     <div class="h">Ad kartlarda saxlanmır, ona görə dəyişiklik bütün
       ƏV-lərdə dərhal görünür — bu, adın deyil, nömrənin kartda
       saxlanmasının səbəbidir.</div>`,
    d => post('group.update', d), 'Yadda saxla');
}

function formGroupDelete(gid){
  const g = GROUPS().find(x => x.group_id === gid);
  const n = groupCount(gid);
  openModal(`«${g.name}» növünü sil`,
    `<input type="hidden" name="group_id" value="${gid}">
     <div class="note">${n
        ? `Bu növdə <strong>${n} ƏV</strong> var və silinmə qəbul edilməyəcək:
           bir kliklə ${n} kartın bölgüsü səssizcə itərdi. Əvvəlcə «ƏV seç»
           ilə onları başqa növə keçirin.`
        : 'Növ boşdur. Silinmə ƏV kartlarına toxunmur.'}</div>`,
    d => post('group.delete', d), 'Sil');
}

/* ---- putting cards INTO a group ----
   One action for the whole selection, not one per card: every write backs the
   folder up and recomputes each open year (§8.1), so forty separate calls
   would mean forty backups for one act of sorting. Same reasoning as the
   500/5% list (§5.3-bis). */
function formAssign(gid){
  const target = gid === NOGROUP ? '' : gid;
  const rows = allCards().map(c => `<tr>
      <td><input type="checkbox" data-aid="${c.asset_id}" style="width:auto"
            ${c.group_id === target ? 'disabled checked' : ''}></td>
      <td>${esc(c.inv_no)}</td><td>${esc(c.name)}</td>
      <td>${esc(c.category)}</td>
      <td class="h">${esc(c.group || '—')}</td></tr>`).join('');

  openModal(target ? `«${groupName(target)}» növünə keçir` : 'Növsüz et', `
    <input type="hidden" name="group_id" value="${target}">
    <div class="fld"><label>Süzgəc</label>
      <input id="assignq" placeholder="ad, inv.№, kateqoriya, indiki növ…"
        oninput="assignFilter(this.value)"></div>
    <div class="acts" style="margin:0 0 8px">
      <button type="button" class="tagbtn" onclick="assignAll(true)"
        >görünənləri seç</button>
      <button type="button" class="tagbtn" onclick="assignAll(false)"
        >seçimi ləğv et</button>
      <span class="h" id="assigncount"></span></div>
    <div class="scroll" style="max-height:38vh" id="assignbox"><table>
      <thead><tr><th></th><th>İnv.№</th><th>Adı</th><th>Kat.</th>
        <th>İndiki növ</th></tr></thead><tbody>${rows}</tbody></table></div>`,
    d => {
      const ids = assignPicked();
      if (!ids.length) throw new Error('ƏV seçilməyib');
      return post('group.assign', {group_id: d.group_id, asset_ids: ids});
    }, 'Keçir');
  document.getElementById('assignbox').onchange = assignCount;
  assignCount();
}

const assignPicked = () =>
  [...document.querySelectorAll('#assignbox input:checked')]
    .filter(el => !el.disabled).map(el => el.dataset.aid);

function assignFilter(q){
  const s = q.trim().toLowerCase();
  for (const tr of document.querySelectorAll('#assignbox tbody tr'))
    tr.style.display = !s || tr.textContent.toLowerCase().includes(s) ? '' : 'none';
}

/* "Select all" means the rows in front of you, not the rows the filter is
   hiding -- selecting what cannot be seen is how a bulk action surprises
   someone. */
function assignAll(on){
  for (const tr of document.querySelectorAll('#assignbox tbody tr')){
    if (tr.style.display === 'none') continue;
    const box = tr.querySelector('input');
    if (!box.disabled) box.checked = on;
  }
  assignCount();
}

function assignCount(){
  const box = document.getElementById('assigncount');
  if (box) box.textContent = assignPicked().length
    ? `${assignPicked().length} ƏV seçilib` : '';
}

/* ---- the field on the card form ----
   A dropdown of the dictionary plus one explicit "new" entry. A free text box
   is precisely what turns one group into two. */
function groupField(card){
  const cur = (card && card.group_id) || '';
  const opts = ['<option value="">— növsüz —</option>']
    .concat(GROUPS().map(g => `<option value="${g.group_id}"
      ${cur === g.group_id ? 'selected' : ''}>${esc(g.name)}</option>`))
    .concat(['<option value="__new__">+ yeni növ…</option>']).join('');
  return `<div class="fld"><label>Növ <span class="h">— müştərinin öz
      bölgüsü, heç bir rəqəmə təsir etmir</span></label>
    <select name="group_id" onchange="groupPick(this)">${opts}</select>
    <input name="group_new" placeholder="yeni növün adı"
      style="display:none;margin-top:6px"></div>`;
}

function groupPick(sel){
  const box = sel.parentNode.querySelector('input[name=group_new]');
  box.style.display = sel.value === '__new__' ? '' : 'none';
  if (sel.value === '__new__') box.focus();
}

/* Creating the group is its own act, so it is its own write -- and it goes
   first, because the card needs the id. Two backups instead of one, and only
   when a new name is actually introduced. */
async function groupResolve(d){
  if (d.group_id === '__new__'){
    const name = (d.group_new || '').trim();
    if (!name) throw new Error('Yeni növün adı boşdur');
    d.group_id = (await post('group.create', {name})).result;
  }
  delete d.group_new;
  return d;
}
