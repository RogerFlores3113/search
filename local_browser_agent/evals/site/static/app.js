// Tiny helpers shared by the fixture pages (no external dependencies).
async function postJSON(url, body) {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  let data = null;
  try { data = await r.json(); } catch (e) { /* ignore */ }
  return { ok: r.ok, status: r.status, data: data };
}

async function getJSON(url) {
  const r = await fetch(url);
  return r.json();
}
