/* Helpers shared by the settings and admin pages. */
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const api = async (url, opt = {}) => {
  const r = await fetch(url, opt);
  if (r.status === 401) { location.href = '/login'; throw new Error('auth'); }
  let j = {}; try { j = await r.json(); } catch (_) {}
  if (!r.ok) throw new Error(j.error || 'Request failed');
  return j;
};
const json = (method, body) => ({method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
const say = (sel, msg, bad) => { const el = $(sel); if (el) { el.textContent = msg; el.className = bad ? 'err' : 'okmsg'; } };
$('#logout')?.addEventListener('click', async () => { await fetch('/api/logout', {method: 'POST'}); location.href = '/'; });
