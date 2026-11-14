/* Statement import: preview -> choose rows -> confirm. Uses helpers from app.js. */
let impData = null;
const impMsg = (m, bad) => { const el = $('#imp-msg'); el.textContent = m; el.className = bad ? 'err' : ''; };
const resetImport = () => { impData = null; $('#imp-preview').hidden = true; $('#imp-table tbody').innerHTML = ''; };

async function loadImports() {
  const rows = await api('/api/imports');
  $('#imp-hist tbody').innerHTML = rows.length ? rows.map(r => `<tr><td>${esc(r.filename)} <small>(${r.kind})</small></td>
    <td>${r.date_from} to ${r.date_to}</td><td>${r.rows_new}</td><td>${r.rows_duplicate}</td>
    <td><button class="secondary" data-undo="${r.id}">Undo</button></td></tr>`).join('')
    : '<tr><td colspan="5" class="empty">No imports yet.</td></tr>';
}

$('#imp-form').addEventListener('submit', async e => {
  e.preventDefault(); resetImport(); impMsg('Reading file…');
  const fd = new FormData(e.target);
  if ($('#imp-pw').hidden) fd.delete('password');
  const r = await fetch('/api/import/preview', {method: 'POST', body: fd});
  const j = await r.json();
  if (!r.ok) {
    if (j.code === 'password_required' || j.code === 'wrong_password') {
      $('#imp-pw').hidden = false; $('#imp-pw').focus();
      impMsg(j.error + ' Your password is used once to read the file and is never stored.', true);
    } else impMsg(j.error || 'Upload failed', true);
    return;
  }
  impData = j; $('#imp-pw').hidden = true; $('#imp-pw').value = ''; impMsg('');
  const c = j.counts;
  $('#imp-summary').innerHTML = `<b>${esc(j.filename)}</b>: ${c.total} rows from ${j.date_from} to ${j.date_to}. ` +
    `<b>${c.new} new</b>, <b>${c.duplicate} already in your account</b>.` +
    (j.already_imported ? ` This exact file was imported before (${esc(j.already_imported.created_at)}).` : '');
  $('#imp-warn').innerHTML = j.warnings.map(w => `<li>${esc(w)}</li>`).join('');
  $('#imp-table tbody').innerHTML = j.rows.map(r => `<tr class="${r.duplicate ? 'dup' : ''}" data-i="${r.i}">
    <td><input type="checkbox" ${r.duplicate ? '' : 'checked'} aria-label="Include row ${r.i + 1}"></td><td>${r.date}</td><td>${esc(r.description)}</td>
    <td>${money(r.amount)}</td>
    <td><select aria-label="Type"><option ${r.type === 'expense' ? 'selected' : ''}>expense</option><option ${r.type === 'income' ? 'selected' : ''}>income</option></select></td>
    <td>${r.duplicate ? `<span class="badge dupb" title="${esc(r.matched || '')}">Duplicate</span>` : '<span class="badge newb">New</span>'}${r.confidence === 'guess' ? ' <span class="badge guessb" title="Debit/credit was guessed">Check type</span>' : ''}</td></tr>`).join('');
  $('#imp-all').checked = c.new > 0; $('#imp-preview').hidden = false; updateImpButton();
});

function selectedRows() {
  return [...document.querySelectorAll('#imp-table tbody tr')].filter(tr => tr.querySelector('input').checked).map(tr => {
    const r = impData.rows[+tr.dataset.i];
    return {date: r.date, description: r.description, amount: r.amount, type: tr.querySelector('select').value};
  });
}
function updateImpButton() { const n = selectedRows().length; $('#imp-go').textContent = `Import ${n} selected`; $('#imp-go').disabled = n === 0; }
$('#imp-table').addEventListener('change', updateImpButton);
$('#imp-all').addEventListener('change', e => { document.querySelectorAll('#imp-table tbody tr').forEach(tr => {
  tr.querySelector('input').checked = e.target.checked && !impData.rows[+tr.dataset.i].duplicate; }); updateImpButton(); });
$('#imp-cancel').addEventListener('click', () => { resetImport(); impMsg(''); });
$('#imp-go').addEventListener('click', async () => {
  $('#imp-go').disabled = true;
  try {
    const j = await api('/api/import/confirm', json('POST', {rows: selectedRows(), filename: impData.filename, file_hash: impData.file_hash, kind: impData.kind}));
    resetImport(); $('#imp-form').reset();
    impMsg(`Imported ${j.imported} transaction${j.imported === 1 ? '' : 's'}` + (j.skipped_duplicates ? `, skipped ${j.skipped_duplicates} duplicate${j.skipped_duplicates === 1 ? '' : 's'}.` : '.'));
    await Promise.all([refresh(), loadImports()]);
  } catch (x) { if (x.message !== 'auth') impMsg(x.message, true); $('#imp-go').disabled = false; }
});
$('#imp-hist').addEventListener('click', async e => {
  const id = e.target.dataset.undo; if (!id) return;
  if (!confirm('Remove all transactions added by this import?')) return;
  try { const j = await api('/api/imports/' + id, {method: 'DELETE'}); impMsg(`Removed ${j.removed} transactions.`); await Promise.all([refresh(), loadImports()]); }
  catch (x) { if (x.message !== 'auth') impMsg(x.message, true); }
});
loadImports().catch(() => {});
