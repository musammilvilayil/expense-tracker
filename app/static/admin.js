const tile = (label, v) => `<div class="card"><h3>${label}</h3><p>${v}</p></div>`;
async function load() {
  const [st, us, ms, au, md] = await Promise.all([api('/api/admin/stats'), api('/api/admin/users'), api('/api/admin/messages'), api('/api/admin/audit'), api('/api/admin/model')]);
  $('#a-stats').innerHTML = tile('Users', st.users) + tile('Active', st.active_users) + tile('Admins', st.admins) + tile('Transactions', st.transactions) + tile('Open messages', st.open_messages);
  $('#a-users tbody').innerHTML = us.map(u => `<tr><td>${esc(u.username)}</td><td>${esc(u.email || '')}</td><td>${u.role}</td>
    <td>${u.is_active ? 'active' : '<span class="neg">disabled</span>'}</td><td>${u.transaction_count}</td><td>${esc((u.created_at || '').slice(0, 10))}</td>
    <td class="acts">${u.username === document.querySelector('.apptop span').textContent ? '<small>you</small>' : `
      <button class="secondary" data-act="${u.is_active ? 'disable' : 'enable'}" data-id="${u.id}">${u.is_active ? 'Disable' : 'Enable'}</button>
      <button class="secondary" data-act="${u.role === 'admin' ? 'demote' : 'promote'}" data-id="${u.id}">${u.role === 'admin' ? 'Remove admin' : 'Make admin'}</button>
      <button class="secondary" data-act="reset" data-id="${u.id}" ${u.email ? '' : 'disabled title="No email on file"'}>Send reset email</button>`}</td></tr>`).join('');
  $('#a-msgs').innerHTML = ms.length ? ms.map(m => `<div class="msg ${m.resolved ? 'done' : ''}"><div><b>${esc(m.subject)}</b> <small>from ${esc(m.name)} &lt;${esc(m.email)}&gt; · ${esc(m.created_at)}</small></div>
    <p>${esc(m.message)}</p><button class="secondary" data-mact="${m.resolved ? 'reopen' : 'resolve'}" data-id="${m.id}">${m.resolved ? 'Reopen' : 'Mark resolved'}</button>
    <button class="secondary" data-mact="delete" data-id="${m.id}">Delete</button></div>`).join('') : '<p class="hint">No messages.</p>';
  $('#a-audit tbody').innerHTML = au.length ? au.map(a => `<tr><td>${esc(a.created_at)}</td><td>${esc(a.admin || '')}</td><td>${esc(a.action)}</td><td>${esc(a.target)}</td></tr>`).join('') : '<tr><td colspan="4" class="empty">No admin actions yet.</td></tr>';
  if (md.available) { const m = md.metrics;
    $('#a-model').innerHTML = `<p>Accuracy (merchant held-out): <b>${(m.grouped_cv.accuracy * 100).toFixed(1)}%</b> · Macro-F1: <b>${(m.grouped_cv.macro_f1 * 100).toFixed(1)}%</b></p>
      <p>Accuracy (random split): ${(m.random_cv.accuracy * 100).toFixed(1)}% · ${m.samples} labeled samples · model: ${esc(m.model)}</p><p>See docs/CATEGORIZER_EVALUATION.md for the full report.</p>`;
  } else $('#a-model').textContent = 'No evaluation yet. Run: python -m app.ml.evaluate';
}
document.addEventListener('click', async e => {
  const t = e.target, id = t.dataset.id; if (!id) return;
  try {
    if (t.dataset.act) {
      const a = t.dataset.act;
      if (a === 'reset') { await api(`/api/admin/users/${id}/reset-password`, {method: 'POST'}); say('#a-msg', 'Reset email sent to the user.'); }
      else if (a === 'disable' || a === 'enable') { if (a === 'disable' && !confirm('Disable this account? They will be signed out.')) return; await api('/api/admin/users/' + id, json('PATCH', {is_active: a === 'enable'})); }
      else await api('/api/admin/users/' + id, json('PATCH', {role: a === 'promote' ? 'admin' : 'user'}));
    } else if (t.dataset.mact) {
      const a = t.dataset.mact;
      if (a === 'delete') { if (!confirm('Delete this message?')) return; await api('/api/admin/messages/' + id, {method: 'DELETE'}); }
      else await api('/api/admin/messages/' + id, json('PATCH', {resolved: a === 'resolve'}));
    }
    await load();
  } catch (x) { if (x.message !== 'auth') say('#a-msg', x.message, true); }
});
load().catch(x => say('#a-msg', x.message, true));
