/* Goals, notifications bell and report links. Uses helpers from app.js. */
const STATUS = {achieved: ['Achieved', 'newb'], on_track: ['On track', 'newb'], behind: ['Behind', 'guessb'], overdue: ['Overdue', 'guessb'],
  in_progress: ['In progress', 'newb'], no_data: ['Add a contribution to see a projection', 'dupb']};
const gmsg = (m, bad) => { const el = $('#goal-msg'); el.textContent = m; el.className = bad ? 'err' : ''; };

async function loadGoals() {
  const goals = await api('/api/goals');
  $('#goal-list').innerHTML = goals.length ? goals.map(g => {
    const [label, cls] = STATUS[g.status] || ['', ''];
    const facts = [
      `${money(g.saved)} of ${money(g.target_amount)} saved (${g.percent}%)`,
      g.target_date ? `target ${g.target_date}` : null,
      g.required_monthly ? `need ${money(g.required_monthly)} per month` : null,
      g.projected_date && g.status !== 'achieved' ? `projected ${g.projected_date}` : null,
    ].filter(Boolean).join(' · ');
    return `<div class="goal"><div class="ghead"><b>${esc(g.name)}</b> <span class="badge ${cls}">${label}</span></div>
      <div class="bar${g.status === 'behind' || g.status === 'overdue' ? ' warning' : ''}"><i style="width:${g.percent}%"></i></div>
      <small>${esc(facts)}</small>
      <form class="inline gform" data-id="${g.id}"><input name="amount" type="number" step="0.01" placeholder="Add (or -withdraw)" required aria-label="Contribution amount">
        <button class="secondary">Add</button><button class="secondary" type="button" data-gdel="${g.id}" aria-label="Delete goal">Delete</button></form></div>`;
  }).join('') : '<p class="empty">No goals yet. Add one below.</p>';
}
$('#goal-form').addEventListener('submit', async e => {
  e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
  if (!f.target_date) delete f.target_date; if (!f.initial) delete f.initial;
  try { await api('/api/goals', json('POST', f)); e.target.reset(); gmsg('Goal added.'); await loadGoals(); } catch (x) { if (x.message !== 'auth') gmsg(x.message, true); }
});
$('#goal-list').addEventListener('submit', async e => {
  e.preventDefault(); const id = e.target.dataset.id; if (!id) return;
  try { await api(`/api/goals/${id}/contributions`, json('POST', {amount: e.target.amount.value})); gmsg(''); await loadGoals(); loadBell(); } catch (x) { if (x.message !== 'auth') gmsg(x.message, true); }
});
$('#goal-list').addEventListener('click', async e => {
  const id = e.target.dataset.gdel; if (!id || !confirm('Delete this goal and its history?')) return;
  try { await api('/api/goals/' + id, {method: 'DELETE'}); await loadGoals(); } catch (x) { if (x.message !== 'auth') gmsg(x.message, true); }
});

/* notifications */
async function loadBell() {
  const n = await api('/api/notifications');
  const badge = $('#bell-n'); badge.textContent = n.unread; badge.hidden = n.unread === 0;
  $('#bell-list').innerHTML = n.items.length ? n.items.map(i => `<li class="${i.is_read ? 'read' : ''}"><span class="k">${esc(i.kind)}</span> ${esc(i.message)}</li>`).join('') : '<li class="read">No reminders. You are all caught up.</li>';
}
$('#bell').addEventListener('click', () => { const p = $('#bell-panel'); p.hidden = !p.hidden; $('#bell').setAttribute('aria-expanded', String(!p.hidden)); });
document.addEventListener('click', e => { if (!e.target.closest('.bellwrap')) { $('#bell-panel').hidden = true; $('#bell').setAttribute('aria-expanded', 'false'); } });
$('#bell-read').addEventListener('click', async () => { await api('/api/notifications/read', json('POST', {})); loadBell(); });

/* reports */
function reportLinks() {
  const m = $('#month').value || new Date().toISOString().slice(0, 7), y = m.slice(0, 4);
  $('#r-csv-m').href = `/api/report?period=${m}&format=csv`; $('#r-pdf-m').href = `/api/report?period=${m}&format=pdf`;
  $('#r-csv-y').href = `/api/report?period=${y}&format=csv`; $('#r-pdf-y').href = `/api/report?period=${y}&format=pdf`;
  $('#r-csv-m').textContent = `${m} CSV`; $('#r-pdf-m').textContent = `${m} PDF`; $('#r-csv-y').textContent = `${y} CSV`; $('#r-pdf-y').textContent = `${y} PDF`;
}
$('#month').addEventListener('change', reportLinks); reportLinks();
loadGoals().catch(() => {}); loadBell().catch(() => {});
