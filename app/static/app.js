const $ = s => document.querySelector(s);
const money = n => (n < 0 ? '-' : '') + Math.abs(n).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const api = async (url, opt = {}) => {
  const r = await fetch(url, opt);
  if (r.status === 401) { location.href = '/login'; throw new Error('auth'); }
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || 'Request failed');
  return j;
};
const json = (method, body) => ({method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
const status = (m, bad) => { const el = $('#status'); el.textContent = m; el.className = bad ? 'err' : ''; };
let charts = {};
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
const tween = (el, to, fmt = money) => {
  const from = parseFloat(el.dataset.v || 0); el.dataset.v = to;
  if (reduceMotion) { el.textContent = fmt(to); return; }
  const t0 = performance.now();
  const step = t => { const p = Math.min((t - t0) / 900, 1), e = 1 - Math.pow(1 - p, 3);
    el.textContent = fmt(from + (to - from) * e); if (p < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
};
const FC_COLORS = {hist: '#2f6b0a', fc: '#e0803f', band: 'rgba(224,128,63,.16)'};
const PAL = ['#2f6b0a', '#b8f06f', '#5bb8d4', '#e0803f', '#f3dc6b', '#a99bf0', '#0d1a08', '#d6e4c4'];
$('#month').value = new Date().toISOString().slice(0, 7);

function chart(id, cfg) { charts[id]?.destroy(); if (window.Chart) charts[id] = new Chart($(id), cfg); }

async function refresh() {
  loadForecast().catch(e => { if (e.message !== 'auth') console.error(e); });
  const month = $('#month').value;
  const [ins, txs, ap] = await Promise.all([api('/api/insights?month=' + month), api('/api/transactions'), api('/api/autopay')]);
  $('#ap tbody').innerHTML = ap.length ? ap.map(a => `<tr><td>${esc(a.description)}${a.active ? '' : ' (paused)'}</td><td>${a.type === 'income' ? '+' : '-'}${money(a.amount)}</td><td>${a.frequency}</td><td>${a.next_date}</td><td><button class="secondary" data-pause="${a.id}" data-active="${a.active ? 0 : 1}">${a.active ? 'Pause' : 'Resume'}</button> <button class="secondary" data-apdel="${a.id}" aria-label="Delete autopay">×</button></td></tr>`).join('') : '<tr><td colspan="5">No autopay rules.</td></tr>';
  const s = ins.summary;
  tween($('#k-inc'), s.income); tween($('#k-exp'), s.expense);
  tween($('#k-sav'), s.savings); $('#k-sav').className = s.savings < 0 ? 'neg' : 'pos';
  tween($('#k-rate'), s.savings_rate, v => v.toFixed(1) + '%');

  $('#alerts').innerHTML = [
    ...ins.renewals_due.map(r => `Renewal due ${esc(r.next_renewal)}: ${esc(r.name)} (${money(r.amount)})`),
    ...ins.budgets.filter(b => b.status === 'over').map(b => `Over ${esc(b.category)} budget: ${money(b.spent)} / ${money(b.limit)}`),
    ...ins.anomalies.slice(0, 3).map(a => `Unusual ${esc(a.category)} charge: ${esc(a.description)} ${money(a.amount)} (typical ${money(a.typical)})`),
  ].map(t => `<div class="alert">${t}</div>`).join('');

  $('#recs').innerHTML = ins.recommendations.map(r => `<li>${esc(r)}</li>`).join('');
  $('#anoms').innerHTML = ins.anomalies.length
    ? ins.anomalies.map(a => `<li>${esc(a.date)} · ${esc(a.description)} · <b>${money(a.amount)}</b> vs typical ${money(a.typical)} (${esc(a.category)})</li>`).join('')
    : '<li>No unusual spending detected.</li>';
  $('#subs tbody').innerHTML = ins.subscriptions.length
    ? ins.subscriptions.map(x => `<tr><td>${esc(x.name)}</td><td>${x.frequency}</td><td>${money(x.amount)}</td><td>${x.next_renewal}</td></tr>`).join('')
    : '<tr><td colspan="4" class="empty">No recurring charges detected yet.</td></tr>';
  $('#budgets').innerHTML = ins.budgets.length
    ? ins.budgets.map(b => `<div><div>${esc(b.category)}: ${money(b.spent)} / ${money(b.limit)}</div><div class="bar ${b.status}"><i style="width:${Math.min(b.percent, 100)}%"></i></div></div>`).join('')
    : '<p>No budgets set.</p>';

  chart('#c-cat', {type: 'doughnut', options: {maintainAspectRatio: false}, data: {labels: Object.keys(s.by_category), datasets: [{data: Object.values(s.by_category), backgroundColor: PAL, borderColor: '#fff'}]}});
  const months = Object.keys(ins.yearly.by_month);
  chart('#c-trend', {type: 'bar', options: {maintainAspectRatio: false}, data: {labels: months, datasets: [
    {label: 'Income', data: months.map(m => ins.yearly.by_month[m].income), backgroundColor: '#2f6b0a'},
    {label: 'Expense', data: months.map(m => ins.yearly.by_month[m].expense), backgroundColor: '#e0803f'}]}});

  $('#tx tbody').innerHTML = txs.slice(0, 100).map(t => `<tr><td>${t.date}</td><td>${esc(t.description)}</td>
    <td class="${t.type === 'income' ? 'pos' : ''}">${t.type === 'income' ? '+' : '-'}${money(t.amount)}</td>
    <td>${t.type === 'expense' ? `<select data-id="${t.id}" aria-label="Category">${CATS.map(c => `<option ${c === t.category ? 'selected' : ''}>${c}</option>`).join('')}</select>` : 'Income'}</td>
    <td><button class="secondary" data-del="${t.id}" aria-label="Delete transaction">×</button></td></tr>`).join('');
}


async function loadForecast() {
  const f = await api('/api/forecast?horizon=3');
  const fe = f.forecast.expense, fs = f.forecast.savings;
  const conf = $('#f-conf'); conf.textContent = f.confidence + ' confidence · ' + f.months_of_data + ' full month' + (f.months_of_data === 1 ? '' : 's');
  conf.className = 'conf ' + f.confidence;
  const range = x => x ? `likely ${money(x.low)} to ${money(x.high)}` : '';
  $('#f-next').textContent = fe.length ? money(fe[0].pred) : '–'; $('#f-next-r').textContent = range(fe[0]);
  $('#f-sav').textContent = fs.length ? money(fs[0].pred) : '–'; $('#f-sav').className = fs.length && fs[0].pred < 0 ? 'neg' : '';
  $('#f-sav-r').textContent = fs.length ? range(fs[0]) : 'needs income data';
  const cm = f.current_month;
  $('#f-proj').textContent = money(cm.projected); $('#f-proj-r').textContent = `${money(cm.spent_so_far)} spent, ${cm.days_left} days left`;
  $('#f-com').textContent = money(f.commitments_total); $('#f-com-r').textContent = f.commitments.length + ' scheduled payment' + (f.commitments.length === 1 ? '' : 's');
  $('#f-tips').innerHTML = f.insights.map(t => `<li>${esc(t)}</li>`).join('');
  $('#f-cats tbody').innerHTML = f.categories.length ? f.categories.map(c => `<tr><td>${esc(c.category)}</td>
    <td class="${c.budget_risk ? 'risk-' + c.budget_risk : ''}">${money(c.predicted)}</td><td>${money(c.low)} – ${money(c.high)}</td>
    <td>${c.change_pct === null ? '–' : (c.change_pct > 0 ? '+' : '') + c.change_pct + '%'}</td></tr>`).join('')
    : '<tr><td colspan="4" class="empty">Add transactions across a few months to see category forecasts.</td></tr>';

  const hm = f.history.months, fm = f.forecast.months, labels = [...hm, cm.month, ...fm], pad = Array(hm.length + 1).fill(null);
  const last = hm.length - 1;
  const fcLine = [...pad.map((_, i) => i === last ? f.history.expense[last] : i === hm.length ? cm.projected : null), ...fe.map(x => x.pred)];
  charts['#c-fc']?.destroy();
  if (window.Chart && labels.length) charts['#c-fc'] = new Chart($('#c-fc'), {type: 'line', options: {maintainAspectRatio: false,
      plugins: {legend: {labels: {filter: i => !i.text.startsWith('_')}}}, interaction: {mode: 'index', intersect: false}},
    data: {labels, datasets: [
      {label: '_high', data: [...pad, ...fe.map(x => x.high)], borderWidth: 0, pointRadius: 0, fill: '+1', backgroundColor: FC_COLORS.band},
      {label: '_low', data: [...pad, ...fe.map(x => x.low)], borderWidth: 0, pointRadius: 0, fill: false},
      {label: 'Spending', data: [...f.history.expense, null, ...fm.map(() => null)], borderColor: FC_COLORS.hist, backgroundColor: FC_COLORS.hist, tension: .3},
      {label: 'Forecast', data: fcLine, borderColor: FC_COLORS.fc, backgroundColor: FC_COLORS.fc, borderDash: [6, 5], tension: .3},
    ]}});
}

const guard = fn => async e => { e.preventDefault(); try { await fn(e); await refresh(); } catch (x) { if (x.message !== 'auth') status(x.message, true); } };
$('#tf').addEventListener('submit', guard(async e => {
  await api('/api/transactions', json('POST', Object.fromEntries(new FormData(e.target)))); e.target.description.value = ''; e.target.amount.value = ''; status('Added.');
}));
$('#bf').addEventListener('submit', guard(async e => api('/api/budgets', json('PUT', Object.fromEntries(new FormData(e.target))))));
$('#tx').addEventListener('change', guard(async e => { if (e.target.dataset.id) await api('/api/transactions/' + e.target.dataset.id, json('PATCH', {category: e.target.value})); }));
$('#tx').addEventListener('click', guard(async e => { const id = e.target.dataset.del; if (id) await api('/api/transactions/' + id, {method: 'DELETE'}); }));
$('#af').addEventListener('submit', guard(async e => { await api('/api/autopay', json('POST', Object.fromEntries(new FormData(e.target)))); status('Autopay added.'); }));
$('#ap').addEventListener('click', guard(async e => {
  const t = e.target;
  if (t.dataset.pause) await api('/api/autopay/' + t.dataset.pause, json('PATCH', {active: t.dataset.active === '1'}));
  else if (t.dataset.apdel) await api('/api/autopay/' + t.dataset.apdel, {method: 'DELETE'});
}));
$('#month').addEventListener('change', refresh);
$('#logout').addEventListener('click', async () => { await fetch('/api/logout', {method: 'POST'}); location.href = '/'; });
refresh();
