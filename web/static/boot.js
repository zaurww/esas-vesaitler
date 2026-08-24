document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => {
  TAB = b.dataset.tab; syncTabs(); render();
});
document.getElementById('filter').oninput = e => { FILTER = e.target.value.trim().toLowerCase(); render(); };
document.addEventListener('keydown', e => {
  if (e.key === '/' && e.target.tagName !== 'INPUT'){ e.preventDefault(); document.getElementById('filter').focus(); }
  if (e.key === 'Escape') closeDrawer();
});
// The drawer closes on an outside click -- unlike the modal (§3: a paste
// grid loses unsaved work to a stray click on the backdrop), the drawer
// holds nothing the user typed, so there is nothing a misclick can lose.
// Two exclusions: a click inside the drawer itself, and a click while the
// modal is open on top of it (the modal's own backdrop-click-does-nothing
// rule must not be undermined by the drawer closing invisibly behind it).
document.addEventListener('click', e => {
  if (DRAWER_JUST_OPENED){ DRAWER_JUST_OPENED = false; return; }
  const d = document.getElementById('drawer');
  if (!d.classList.contains('open')) return;
  if (d.contains(e.target) || document.getElementById('modal').contains(e.target)) return;
  closeDrawer();
});
boot();
