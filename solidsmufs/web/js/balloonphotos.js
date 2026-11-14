// Photos in Ballooning mode: on a characteristic or a production issue. A photo is kept in the PDF as it was taken
// (made no bigger than 1920 pixels along); what's drawn on it is kept beside it as marks, never in the picture, so it
// can be shown, hidden or changed again. The viewer opens the photo nearly full screen; Edit markup draws on it, with
// undo and redo, until Save: arrows, lines, ovals, boxes, freeform shapes (lasso), sketches, text and stamps. A box, an
// oval or a lasso shape can be filled, or blur what's under it (only in the markup: Hide markup shows the photo as
// taken). Select picks marks with a box drawn round them, to move them or Delete them.
// From phone… shows a QR code (and the address) for a phone on the same network to send photos straight here: they
// arrive while the box is open and are added as any photo is (so Undo takes them back).
import { api } from './api.js';
import { h, toast, modal } from './ui.js';

const SVG = 'http://www.w3.org/2000/svg';
const svg = (tag, attrs = {}) => {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) el.setAttribute(k, v);
  return el;
};
export const MARK_COLORS = ['#e02020', '#FF5F05', '#ffd400', '#2bb24c', '#1f9bd7', '#000000', '#ffffff'];
const TOOLS = [['select', 'Select'], ['arrow', 'Arrow'], ['line', 'Line'], ['oval', 'Oval'], ['rect', 'Box'], ['lasso', 'Lasso'], ['pen', 'Sketch'],
  ['text', 'Text'], ['stamp', 'Stamp'], ['erase', 'Erase']];
const FILLS = [['none', 'No fill'], ['solid', 'Filled'], ['blur', 'Blur']];
const FILLED = new Set(['oval', 'rect', 'lasso']);
const STAMPS = ['✔', '✖', 'OK', 'NG', '⚠', 'Burr', 'Rework', 'Scrap', 'Check', 'Ø', 'Datum'];
const keepStamps = (list) => { try { localStorage.setItem('bl:stamps', JSON.stringify(list)); } catch { /* storage off */ } };
const myStamps = () => { try { const v = JSON.parse(localStorage.getItem('bl:stamps') || '[]'); return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []; } catch { return []; } };
const urls = new Map(); // photo id + document: its picture, fetched once
let uid = 0;

async function urlOf(b, p) {
  const key = `${b.doc?.id}:${p.id}`;
  if (!urls.has(key)) urls.set(key, api.pdfEdit(b.doc.id, 'balloon_photo', { id: p.id }).then((r) => r.url).catch(() => { urls.delete(key); return ''; }));
  return urls.get(key);
}

// a mark's outline as an svg shape (for drawing, clipping a blur, and picking)
function shape(m, attrs) {
  if (m.t === 'oval') return svg('ellipse', { ...attrs, cx: (m.a[0] + m.b[0]) / 2, cy: (m.a[1] + m.b[1]) / 2, rx: Math.abs(m.b[0] - m.a[0]) / 2, ry: Math.abs(m.b[1] - m.a[1]) / 2 });
  if (m.t === 'rect') return svg('rect', { ...attrs, x: Math.min(m.a[0], m.b[0]), y: Math.min(m.a[1], m.b[1]), width: Math.abs(m.b[0] - m.a[0]), height: Math.abs(m.b[1] - m.a[1]) });
  if (m.t === 'lasso') return svg('polygon', { ...attrs, points: (m.pts || []).map((q) => q.join(',')).join(' ') });
  return null;
}

// how far a mark reaches: [x0, y0, x1, y1] in the photo's pixels
export function extent(m) {
  const pts = m.pts?.length ? m.pts : m.a ? [m.a, m.b] : m.at ? [m.at, [m.at[0] + (m.s || '').length * (m.size || 48) * 0.6, m.at[1] - (m.size || 48)]] : [];
  if (!pts.length) return [0, 0, 0, 0];
  const xs = pts.map((q) => q[0]), ys = pts.map((q) => q[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

// the marks drawn into an <svg> the photo's size; pic: {url, w, h} for a blur to draw the photo under it
export function drawMarks(g, marks, pic = null, chosen = null) {
  g.replaceChildren();
  const root = g.ownerSVGElement;
  let defs = root?.querySelector('defs');
  if (root && !defs) { defs = svg('defs'); root.prepend(defs); }
  defs?.querySelectorAll('[data-mark]').forEach((el) => el.remove());
  marks.forEach((m, i) => {
    const common = { stroke: m.c, 'stroke-width': m.w, fill: 'none', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'data-i': i };
    let el;
    if (m.t === 'pen') el = svg('polyline', { ...common, points: (m.pts || []).map((q) => q.join(',')).join(' ') });
    else if (m.t === 'line' || m.t === 'arrow') {
      el = svg('g', { 'data-i': i });
      el.append(svg('line', { ...common, x1: m.a[0], y1: m.a[1], x2: m.b[0], y2: m.b[1] }));
      if (m.t === 'arrow') {
        const ang = Math.atan2(m.b[1] - m.a[1], m.b[0] - m.a[0]), L = Math.max(m.w * 4, 18);
        const p = (d) => [m.b[0] - L * Math.cos(ang + d), m.b[1] - L * Math.sin(ang + d)];
        el.append(svg('polyline', { ...common, points: [p(0.45), m.b, p(-0.45)].map((q) => q.join(',')).join(' ') }));
      }
    } else if (FILLED.has(m.t)) {
      el = svg('g', { 'data-i': i });
      if (m.fill === 'blur' && pic?.url && defs) { // the photo, blurred, inside the shape
        const id = `bpm${++uid}`;
        const clip = svg('clipPath', { id: `${id}c`, 'data-mark': '1' });
        clip.append(shape(m, {}));
        const blur = svg('filter', { id: `${id}f`, 'data-mark': '1', x: '-5%', y: '-5%', width: '110%', height: '110%' });
        blur.append(svg('feGaussianBlur', { stdDeviation: Math.max(pic.w, pic.h) / 90 }));
        defs.append(clip, blur);
        el.append(svg('image', { href: pic.url, x: 0, y: 0, width: pic.w, height: pic.h, 'clip-path': `url(#${id}c)`, filter: `url(#${id}f)`, preserveAspectRatio: 'none' }));
      }
      el.append(shape(m, { ...common, fill: m.fill === 'solid' ? m.c : 'none', 'stroke-opacity': m.fill === 'blur' ? 0.35 : 1 }));
    } else if (m.t === 'text' || m.t === 'stamp') {
      const size = m.size || 48;
      el = svg('g', { 'data-i': i });
      const t = svg('text', { x: m.at[0], y: m.at[1], fill: m.c, 'font-size': size, 'font-family': 'Segoe UI, Segoe UI Symbol, Arial, sans-serif', 'font-weight': 700,
        stroke: m.c === '#ffffff' ? '#000' : '#fff', 'stroke-width': Math.max(size / 16, 1.5), 'paint-order': 'stroke' });
      t.textContent = m.s;
      el.append(t);
      if (m.t === 'stamp') { // a stamp: its words in a box
        const wide = (m.s || '').length * size * 0.62 + size * 0.5;
        el.prepend(svg('rect', { x: m.at[0] - size * 0.25, y: m.at[1] - size * 0.95, width: wide, height: size * 1.25, rx: size * 0.2,
          fill: 'rgba(255,255,255,.7)', stroke: m.c, 'stroke-width': Math.max(size / 12, 2) }));
      }
    }
    if (el) {
      if (chosen?.has(i)) el.setAttribute('class', 'bp-chosen');
      g.append(el);
    }
  });
}

function picture(p, url) {
  const img = h('img', { src: url, alt: p.name || 'Photo', draggable: 'false' });
  const over = svg('svg', { viewBox: `0 0 ${p.w} ${p.h}`, preserveAspectRatio: 'none', class: 'bp-over' });
  const g = svg('g');
  over.append(g);
  const ctx = { url, w: p.w, h: p.h };
  drawMarks(g, p.marks || [], ctx);
  return { el: h('div', { class: 'bp-pic' }, img, over), img, over, g, ctx };
}

// the photos on something (on: 'char' or 'issue', of: its id), as thumbnails, and a way to add more
export function photoStrip(b, on, of) {
  const box = h('div', { class: 'bp-strip' });
  const fill = () => {
    const mine = (b.data.photos || []).filter((p) => p.on === on && p.of === of);
    const file = h('input', { type: 'file', accept: 'image/*', multiple: true, hidden: true });
    file.addEventListener('change', async () => {
      for (const f of file.files) await addFile(b, on, of, f);
      fill();
    });
    box.replaceChildren(...mine.map((p) => {
      const t = h('button', { class: 'bp-thumb', type: 'button', title: `${p.name || 'Photo'}: click to open it${(p.marks || []).length ? ' (it has markup)' : ''}` });
      urlOf(b, p).then((url) => { const pic = picture(p, url); t.replaceChildren(pic.el); });
      t.addEventListener('click', () => openPhoto(b, p.id, fill));
      return t;
    }), h('button', { class: 'btn bp-add', type: 'button', text: '+ Photo…', title: 'Add a photo from this computer (or paste one with Ctrl+V while this is open)', onclick: () => file.click() }),
    h('button', { class: 'btn bp-add', type: 'button', text: 'From phone…', title: 'Send photos from a phone on the same network: scan the code it shows', onclick: () => fromPhone(b, on, of, fill) }), file);
  };
  fill();
  // a picture pasted while the dialog is open goes on too
  const paste = async (e) => {
    if (!box.isConnected) { document.removeEventListener('paste', paste, true); return; }
    const item = [...(e.clipboardData?.items || [])].find((x) => x.type.startsWith('image/'));
    if (!item) return;
    e.preventDefault();
    await addFile(b, on, of, item.getAsFile());
    fill();
  };
  document.addEventListener('paste', paste, true);
  return box;
}

// what a photo is of, for the phone's page
function whatFor(b, on, of) {
  if (on === 'char') { const c = b.data.chars.find((x) => x.id === of); return c ? `Balloon ${c.label}: ${c.text || ''}` : 'a balloon'; }
  const i = (b.data.issues || []).find((x) => x.id === of);
  return i ? `Issue #${i.n}: ${i.title || ''}` : 'an issue';
}

// a phone sends photos while this is open: each one that comes is added (polled every two seconds)
async function fromPhone(b, on, of, after) {
  let link;
  try { link = await api.phoneStart(`${whatFor(b, on, of)}${b.data.info?.part ? ` (${b.data.info.part})` : ''}`); } catch (e) { toast(e.message, 'error'); return; }
  let got = 0, open = true, dlg = null, timer = null;
  const say = h('p', { class: 'bp-got', text: 'Waiting for photos…' });
  const left = h('span', { class: 'bl-hint' });
  const tick = async () => {
    if (!open) return;
    try {
      const r = await api.phoneTake(link.code);
      for (const ph of r.photos) {
        const ok = await b.run('balloon_photo_add', { on, of, image: ph.image, name: ph.name || 'phone photo' }, 'Adding the photo…');
        if (ok) got++;
      }
      if (r.photos.length) { say.textContent = `${got} photo${got === 1 ? '' : 's'} received.`; after?.(); }
      const mins = Math.max(Math.ceil((link.until * 1000 - Date.now()) / 60000), 0);
      left.textContent = mins ? `The link works for ${mins} more minute${mins === 1 ? '' : 's'}.` : 'The link has run out: close this and make a new one.';
    } catch { /* (tried again in a moment) */ }
    if (open) timer = setTimeout(tick, 2000);
  };
  const code = h('div', { class: 'bp-qr' });
  if (link.qr) code.innerHTML = link.qr; // (SVG made by the app itself, from the address)
  dlg = modal('Photos from a phone', h('div', { class: 'pe-fprops bl-props bp-phone' },
    h('p', { text: `${link.qr ? 'Scan with a phone on the shop network' : 'Open this address on a phone on the shop network'}. Photos go onto ${whatFor(b, on, of)}.` }),
    link.qr ? code : '',
    h('div', { class: 'bp-url', text: link.url }),
    say, left,
    h('p', { class: 'bl-hint', text: 'If Windows asks about the network, allow private networks.' }),
    h('div', { class: 'pe-pop-foot' }, h('span', { class: 'pv-grow' }),
      h('button', { class: 'btn primary', text: 'Done', onclick: () => dlg.close() }))), { width: 520 });
  const close = dlg.close.bind(dlg);
  dlg.close = () => { open = false; clearTimeout(timer); close(); tick0.then(() => api.phoneTake(link.code)).then(async (r) => {
    for (const ph of r?.photos || []) await b.run('balloon_photo_add', { on, of, image: ph.image, name: ph.name || 'phone photo' });
    if (r?.photos?.length) after?.();
  }).catch(() => {}).finally(() => api.phoneStop(link.code).catch(() => {})); };
  const tick0 = tick();
}

async function addFile(b, on, of, f) {
  if (!f) return;
  const url = await new Promise((done) => { const r = new FileReader(); r.onload = () => done(r.result); r.onerror = () => done(null); r.readAsDataURL(f); });
  if (!url) { toast("That picture couldn't be read.", 'error'); return; }
  await b.run('balloon_photo_add', { on, of, image: url, name: f.name || '' }, 'Adding the photo…');
}

// a photo nearly full screen: its markup shown or hidden, edited, or the photo deleted
export async function openPhoto(b, id, after = null) {
  const p = (b.data.photos || []).find((x) => x.id === id);
  if (!p) return;
  const url = await urlOf(b, p);
  const pic = picture(p, url);
  let showing = true;
  const toggle = h('button', { class: 'btn', text: 'Hide markup', disabled: !(p.marks || []).length, onclick: () => {
    showing = !showing;
    pic.over.style.display = showing ? '' : 'none';
    toggle.textContent = showing ? 'Hide markup' : 'Show markup';
  } });
  let dlg = null;
  const foot = h('div', { class: 'pe-pop-foot' },
    h('span', { class: 'bl-hint', text: `${p.name ? `${p.name} · ` : ''}${p.w} × ${p.h} · ${new Date(p.at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}${p.by ? ` · ${p.by}` : ''}` }),
    h('span', { class: 'pv-grow' }),
    h('button', { class: 'btn', text: 'Delete photo', onclick: async () => {
      dlg.close();
      await b.run('balloon_photo_delete', { id: p.id });
      after?.();
    } }),
    toggle,
    h('button', { class: 'btn primary', text: 'Edit markup', onclick: () => { dlg.close(); editMarks(b, p, url, after); } }),
    h('button', { class: 'btn', text: 'Close', onclick: () => dlg.close() }));
  dlg = modal(p.name || 'Photo', h('div', { class: 'bp-view' }, pic.el, foot), { width: Math.min(innerWidth - 40, 1500) });
}

// drawing on a photo: the marks only, saved together; undo and redo while it's open
function editMarks(b, p, url, after) {
  const pic = picture(p, url);
  let marks = (p.marks || []).map((m) => JSON.parse(JSON.stringify(m)));
  const undo = [], redo = [];
  let tool = 'arrow', color = '#e02020', fill = 'none', stamp = STAMPS[0], width = Math.max(Math.round(Math.max(p.w, p.h) / 300), 3);
  let chosen = new Set(); // marks picked with Select
  const draw = (list = marks) => drawMarks(pic.g, list, pic.ctx, chosen);
  const change = (next) => { undo.push(marks); redo.length = 0; marks = next; chosen = new Set([...chosen].filter((i) => i < marks.length)); draw(); bar(); };
  const at = (e) => {
    const r = pic.over.getBoundingClientRect();
    return [Math.round(((e.clientX - r.left) / r.width) * p.w * 10) / 10, Math.round(((e.clientY - r.top) / r.height) * p.h * 10) / 10];
  };
  const tools = h('div', { class: 'bp-tools' });
  const stampPick = () => {
    const sel = h('select', { title: 'The stamp a click puts down' }, ...[...STAMPS, ...myStamps()].map((s) => h('option', { value: s, text: s, selected: s === stamp })),
      h('option', { value: '+', text: 'New stamp…' }));
    sel.addEventListener('change', async () => {
      if (sel.value !== '+') { stamp = sel.value; return; }
      if (!await b._asLead()) { bar(); return; }
      const s = await b._ask('New stamp', 'Its words', 'Add stamp', "A stamp everyone on this PC can put on a photo: a word or two, or a symbol. What it's for goes in its words.");
      if (s) { keepStamps([...new Set([...myStamps(), s.slice(0, 24)])]); stamp = s.slice(0, 24); }
      bar();
    });
    sel.addEventListener('keydown', (e) => e.stopPropagation());
    return sel;
  };
  const bar = () => {
    const fills = h('select', { title: 'What a box, oval or lasso shape is filled with: nothing, its color, or the photo blurred' },
      ...FILLS.map(([k, label]) => h('option', { value: k, text: label, selected: k === fill })));
    fills.addEventListener('change', () => {
      fill = fills.value;
      if (chosen.size) change(marks.map((m, i) => (chosen.has(i) && FILLED.has(m.t) ? { ...m, fill } : m)));
    });
    tools.replaceChildren(
      ...TOOLS.map(([k, label]) => h('button', { class: `btn bp-tool${tool === k ? ' on' : ''}`, text: label, onclick: () => { tool = k; if (k !== 'select') { chosen = new Set(); draw(); } bar(); } })),
      tool === 'stamp' ? stampPick() : '',
      h('span', { class: 'pv-sep' }),
      ...MARK_COLORS.map((c) => h('button', { class: `bp-color${color === c ? ' on' : ''}`, style: { background: c }, title: c === '#FF5F05' ? 'Illini orange' : c, onclick: () => {
        color = c;
        if (chosen.size) change(marks.map((m, i) => (chosen.has(i) ? { ...m, c } : m))); else bar();
      } })),
      h('span', { class: 'pv-sep' }),
      fills,
      h('label', { class: 'bp-width' }, 'Width', (() => { const s = h('input', { type: 'range', min: 1, max: 30, value: width }); s.addEventListener('input', () => { width = +s.value; }); return s; })()),
      h('span', { class: 'pv-sep' }),
      h('button', { class: 'btn', text: 'Undo', disabled: !undo.length, onclick: () => { redo.push(marks); marks = undo.pop(); chosen = new Set(); draw(); bar(); } }),
      h('button', { class: 'btn', text: 'Redo', disabled: !redo.length, onclick: () => { undo.push(marks); marks = redo.pop(); chosen = new Set(); draw(); bar(); } }),
      chosen.size ? h('button', { class: 'btn', text: `Delete ${chosen.size}`, onclick: () => { const gone = chosen; chosen = new Set(); change(marks.filter((_, i) => !gone.has(i))); } }) : '',
      h('button', { class: 'btn', text: 'Clear', disabled: !marks.length, title: 'Take every mark off (the photo stays as it was)', onclick: () => { chosen = new Set(); change([]); } }));
  };
  bar();
  pic.over.classList.add('editing');
  const drag = (e, move, up) => {
    try { pic.over.setPointerCapture(e.pointerId); } catch { /* (a pointer that's already gone) */ }
    const mv = (ev) => move(at(ev));
    const done = (ev) => { pic.over.removeEventListener('pointermove', mv); pic.over.removeEventListener('pointerup', done); up(at(ev)); };
    pic.over.addEventListener('pointermove', mv);
    pic.over.addEventListener('pointerup', done);
  };
  pic.over.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    if (document.activeElement && !pic.el.contains(document.activeElement)) document.activeElement.blur?.(); // (Delete is for the marks now)
    const a = at(e);
    if (tool === 'erase') {
      const i = e.target.closest('[data-i]')?.getAttribute('data-i');
      if (i !== undefined && i !== null) change(marks.filter((_, k) => k !== +i));
      return;
    }
    if (tool === 'text') { typeAt(a); return; }
    if (tool === 'stamp') { const size = Math.max(width * 8, 28); change([...marks, { t: 'stamp', c: color, w: width, at: [a[0], a[1] + size / 2], s: stamp, size }]); return; }
    if (tool === 'select') {
      const hit = e.target.closest('[data-i]')?.getAttribute('data-i');
      if (hit !== null && hit !== undefined && (chosen.has(+hit) || !e.shiftKey)) { // drag what's picked (or this one)
        if (!chosen.has(+hit)) chosen = new Set([+hit]);
        const from = marks;
        let moved = from;
        drag(e, (q) => {
          const dx = q[0] - a[0], dy = q[1] - a[1], sh = (pt) => [Math.round((pt[0] + dx) * 10) / 10, Math.round((pt[1] + dy) * 10) / 10];
          moved = from.map((m, i) => (!chosen.has(i) ? m : { ...m, ...(m.a ? { a: sh(m.a), b: sh(m.b) } : {}), ...(m.pts ? { pts: m.pts.map(sh) } : {}), ...(m.at ? { at: sh(m.at) } : {}) }));
          draw(moved);
        }, () => { if (moved !== from) change(moved); else { draw(); bar(); } });
        return;
      }
      const box = svg('rect', { class: 'bp-band', x: a[0], y: a[1], width: 0, height: 0 });
      pic.over.append(box);
      drag(e, (q) => {
        box.setAttribute('x', Math.min(a[0], q[0])); box.setAttribute('y', Math.min(a[1], q[1]));
        box.setAttribute('width', Math.abs(q[0] - a[0])); box.setAttribute('height', Math.abs(q[1] - a[1]));
      }, (q) => {
        box.remove();
        const [x0, y0, x1, y1] = [Math.min(a[0], q[0]), Math.min(a[1], q[1]), Math.max(a[0], q[0]), Math.max(a[1], q[1])];
        const inside = marks.map((m, i) => [i, extent(m)]).filter(([, r]) => r[0] >= x0 && r[1] >= y0 && r[2] <= x1 && r[3] <= y1).map(([i]) => i);
        chosen = new Set(e.shiftKey ? [...chosen, ...inside] : inside);
        draw();
        bar();
      });
      return;
    }
    const m = tool === 'pen' || tool === 'lasso' ? { t: tool, c: color, w: width, pts: [a] } : { t: tool, c: color, w: width, a, b: a };
    if (FILLED.has(tool)) m.fill = fill;
    const live = [...marks, m];
    drag(e, (q) => {
      if (m.pts) m.pts.push(q); else m.b = q;
      draw(live);
    }, () => {
      const big = m.pts ? m.pts.length > (tool === 'lasso' ? 2 : 1) : Math.hypot(m.b[0] - m.a[0], m.b[1] - m.a[1]) > 3;
      if (big) change(live); else draw();
    });
  });
  // Delete takes the marks picked off
  const onKey = (e) => {
    if (!pic.el.isConnected) { document.removeEventListener('keydown', onKey, true); return; }
    const typingHere = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName) && tools.parentNode?.contains(document.activeElement);
    if ((e.key === 'Delete' || e.key === 'Backspace') && chosen.size && !typingHere) {
      e.preventDefault();
      e.stopPropagation();
      const gone = chosen;
      chosen = new Set();
      change(marks.filter((_, i) => !gone.has(i)));
    }
  };
  document.addEventListener('keydown', onKey, true);
  // text: typed where it was clicked, Enter to put it down
  const typeAt = (a) => {
    pic.el.querySelector('.bp-type')?.remove();
    const r = pic.over.getBoundingClientRect(), k = r.width / p.w;
    const size = Math.max(width * 8, 24);
    const inp = h('input', { class: 'bp-type', type: 'text', placeholder: 'Type, then Enter',
      style: { left: `${a[0] * k}px`, top: `${(a[1] - size) * k}px`, fontSize: `${Math.max(size * k, 12)}px`, color } });
    pic.el.append(inp);
    setTimeout(() => inp.focus(), 0);
    let done = false;
    const put = () => {
      if (done) return;
      done = true;
      const s = inp.value.trim();
      inp.remove();
      if (s) change([...marks, { t: 'text', c: color, w: width, at: a, s, size }]);
    };
    inp.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') put(); if (e.key === 'Escape') { done = true; inp.remove(); } });
    inp.addEventListener('blur', put);
  };
  let dlg = null;
  dlg = modal(`Markup: ${p.name || 'photo'}`, h('div', { class: 'bp-view' }, tools, pic.el,
    h('div', { class: 'pe-pop-foot' },
      h('span', { class: 'bl-hint', text: 'The marks are kept beside the photo, never in it: they can be hidden or changed again. A blur too.' }),
      h('span', { class: 'pv-grow' }),
      h('button', { class: 'btn', text: 'Cancel', onclick: () => dlg.close() }),
      h('button', { class: 'btn primary', text: 'Save', onclick: async () => {
        dlg.close();
        await b.run('balloon_photo_marks', { id: p.id, marks });
        after?.();
      } }))), { width: Math.min(innerWidth - 40, 1500) });
  document.activeElement?.blur?.();
}
