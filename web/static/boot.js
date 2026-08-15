document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => {
  TAB = b.dataset.tab; syncTabs(); render();
});
document.getElementById('filter').oninput = e => { FILTER = e.target.value.trim().toLowerCase(); render(); };
document.addEventListener('keydown', e => {
  if (e.key === '/' && e.target.tagName !== 'INPUT'){ e.preventDefault(); document.getElementById('filter').focus(); }
  if (e.key === 'Escape') closeDrawer();
});
boot();
