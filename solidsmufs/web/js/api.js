// Talking to the local server. The session token comes in the page URL and goes on every call.
const token = new URLSearchParams(location.search).get('t') || '';

async function call(method, path, body, raw = false) {
  const opts = { method, headers: { 'X-Token': token } };
  if (body !== undefined) {
    if (body instanceof Blob || body instanceof ArrayBuffer) opts.body = body;
    else { opts.body = JSON.stringify(body); opts.headers['Content-Type'] = 'application/json'; }
  }
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).error || msg; } catch { /* not JSON */ }
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return raw ? res.arrayBuffer() : res.json();
}

export const api = {
  hello: () => call('GET', '/api/hello'),
  open: (path, quality) => call('POST', '/api/open', { path, quality }),
  upload: (file) => call('POST', `/api/upload?name=${encodeURIComponent(file.name)}`, file),
  status: (id) => call('GET', `/api/docs/${id}`),
  meta: (id) => call('GET', `/api/docs/${id}/meta`),
  mesh: (id) => call('GET', `/api/docs/${id}/mesh`, undefined, true),
  close: (id) => call('POST', `/api/docs/${id}/close`, {}),
  reload: (id, quality, config) => call('POST', `/api/docs/${id}/reload`, config === undefined ? { quality } : { quality, config }),
  measure: (id, selection, options) => call('POST', `/api/docs/${id}/measure`, { selection, options }),
  massprops: (id, bodies, density) => call('POST', `/api/docs/${id}/massprops`, { bodies, density }),
  bbox: (id, bodies, mode) => call('POST', `/api/docs/${id}/bbox`, { bodies, mode }),
  sectionProps: (id, faces) => call('POST', `/api/docs/${id}/sectionprops`, { faces }),
  holes: (id) => call('POST', `/api/docs/${id}/holes`, {}),
  saveStep: (id) => call('POST', `/api/docs/${id}/save-step`, {}),
  settings: (ui) => call('POST', '/api/settings', ui),
  removeRecent: (path) => call('POST', '/api/recent/remove', { path }),
  openDialog: () => call('POST', '/api/dialog/open', {}),
  saveImage: (data, name) => call('POST', '/api/dialog/save-image', { data, name }),
  reveal: (path) => call('POST', '/api/reveal', { path }),
  title: (title) => call('POST', '/api/title', { title }).catch(() => {}),
  fsRoots: () => call('GET', '/api/fs/roots'),
  fsList: (path) => call('POST', '/api/fs/list', { path }),
};
