// Photos in Ballooning mode: on a characteristic or a production issue. A photo is kept in the PDF as it was taken
// (made no bigger than 1920 pixels along); what's drawn on it (arrows, lines, ovals, boxes, freehand, text) is kept
// beside it as marks, never in the picture, so it can be shown, hidden or changed again. The viewer opens the photo
// nearly full screen; Edit markup draws on it, with undo and redo, until Save.
import { api } from './api.js';
import { h, toast, modal } from './ui.js';

const SVG = 'http://www.w3.org/2000/svg';
const svg = (tag, attrs = {}) => {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) el.setAttribute(k, v);
  return el;
};
export const MARK_COLORS = ['#e02020', '#FF5F05', '#ffd400', '#2bb24c', '#1f9bd7', '#000000', '#ffffff'];
const TOOLS = [['arrow', 'Arrow'], ['line', 'Line'], ['oval', 'Oval'], ['rect', 'Box'], ['pen', 'Sketch'], ['text', 'Text'], ['erase', 'Erase']];
const urls = new Map(); // photo id + document: its picture, fetched once

async function urlOf(b, p) {
  const key = `${b.doc?.id}:${p.id}`;
  if (!urls.has(key)) urls.set(key, api.pdfEdit(b.doc.id, 'balloon_photo', { id: p.id }).then((r) => r.url).catch(() => { urls.delete(key); return ''; }));
  return urls.get(key);
}

// the marks drawn into an <svg> the photo's size (k: how much bigger lines and text are drawn, for a thumbnail)
export function drawMarks(g, marks) {
  g.replaceChildren();
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
    } else if (m.t === 'oval') {
      el = svg('ellipse', { ...common, cx: (m.a[0] + m.b[0]) / 2, cy: (m.a[1] + m.b[1]) / 2, rx: Math.abs(m.b[0] - m.a[0]) / 2, ry: Math.abs(m.b[1] - m.a[1]) / 2 });
    } else if (m.t === 'rect') {
      el = svg('rect', { ...common, x: Math.min(m.a[0], m.b[0]), y: Math.min(m.a[1], m.b[1]), width: Math.abs(m.b[0] - m.a[0]), height: Math.abs(m.b[1] - m.a[1]) });
    } else if (m.t === 'text') {
      el = svg('text', { x: m.at[0], y: m.at[1], fill: m.c, 'font-size': m.size || 48, 'font-family': 'Segoe UI, Arial, sans-serif', 'font-weight': 600,
        stroke: m.c === '#ffffff' ? '#000' : '#fff', 'stroke-width': Math.max((m.size || 48) / 16, 1.5), 'paint-order': 'stroke', 'data-i': i });
      el.textContent = m.s;
    }
    if (el) g.append(el);
  });
}

function picture(p, url) {
  const img = h('img', { src: url, alt: p.name || 'Photo', draggable: 'false' });
  const over = svg('svg', { viewBox: `0 0 ${p.w} ${p.h}`, preserveAspectRatio: 'none', class: 'bp-over' });
  const g = svg('g');
  over.append(g);
  drawMarks(g, p.marks || []);
  return { el: h('div', { class: 'bp-pic' }, img, over), img, over, g };
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
    }), h('button', { class: 'btn bp-add', type: 'button', text: '+ Photo…', title: 'Add a photo from this computer (or paste one with Ctrl+V while this is open)', onclick: () => file.click() }), file);
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
  let tool = 'arrow', color = '#e02020', width = Math.max(Math.round(Math.max(p.w, p.h) / 300), 3);
  const change = (next) => { undo.push(marks); redo.length = 0; marks = next; drawMarks(pic.g, marks); bar(); };
  const at = (e) => {
    const r = pic.over.getBoundingClientRect();
    return [Math.round(((e.clientX - r.left) / r.width) * p.w * 10) / 10, Math.round(((e.clientY - r.top) / r.height) * p.h * 10) / 10];
  };
  const tools = h('div', { class: 'bp-tools' });
  const bar = () => {
    tools.replaceChildren(
      ...TOOLS.map(([k, label]) => h('button', { class: `btn bp-tool${tool === k ? ' on' : ''}`, text: label, onclick: () => { tool = k; bar(); } })),
      h('span', { class: 'pv-sep' }),
      ...MARK_COLORS.map((c) => h('button', { class: `bp-color${color === c ? ' on' : ''}`, style: { background: c }, title: c === '#FF5F05' ? 'Illini orange' : c, onclick: () => { color = c; bar(); } })),
      h('span', { class: 'pv-sep' }),
      h('label', { class: 'bp-width' }, 'Width', (() => { const s = h('input', { type: 'range', min: 1, max: 30, value: width }); s.addEventListener('input', () => { width = +s.value; }); return s; })()),
      h('span', { class: 'pv-sep' }),
      h('button', { class: 'btn', text: 'Undo', disabled: !undo.length, onclick: () => { redo.push(marks); marks = undo.pop(); drawMarks(pic.g, marks); bar(); } }),
      h('button', { class: 'btn', text: 'Redo', disabled: !redo.length, onclick: () => { undo.push(marks); marks = redo.pop(); drawMarks(pic.g, marks); bar(); } }),
      h('button', { class: 'btn', text: 'Clear', disabled: !marks.length, title: 'Take every mark off (the photo stays as it was)', onclick: () => change([]) }));
  };
  bar();
  pic.over.classList.add('editing');
  pic.over.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const a = at(e);
    if (tool === 'erase') {
      const i = e.target.closest('[data-i]')?.getAttribute('data-i');
      if (i !== undefined && i !== null) change(marks.filter((_, k) => k !== +i));
      return;
    }
    if (tool === 'text') { typeAt(a); return; }
    const m = tool === 'pen' ? { t: 'pen', c: color, w: width, pts: [a] } : { t: tool, c: color, w: width, a, b: a };
    const live = [...marks, m];
    pic.over.setPointerCapture(e.pointerId);
    const move = (ev) => {
      const q = at(ev);
      if (tool === 'pen') m.pts.push(q); else m.b = q;
      drawMarks(pic.g, live);
    };
    const up = () => {
      pic.over.removeEventListener('pointermove', move);
      pic.over.removeEventListener('pointerup', up);
      const big = tool === 'pen' ? m.pts.length > 1 : Math.hypot(m.b[0] - m.a[0], m.b[1] - m.a[1]) > 3;
      if (big) change(live); else drawMarks(pic.g, marks);
    };
    pic.over.addEventListener('pointermove', move);
    pic.over.addEventListener('pointerup', up);
  });
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
      h('span', { class: 'bl-hint', text: 'The marks are kept beside the photo, never in it: they can be hidden or changed again.' }),
      h('span', { class: 'pv-grow' }),
      h('button', { class: 'btn', text: 'Cancel', onclick: () => dlg.close() }),
      h('button', { class: 'btn primary', text: 'Save', onclick: async () => {
        dlg.close();
        await b.run('balloon_photo_marks', { id: p.id, marks });
        after?.();
      } }))), { width: Math.min(innerWidth - 40, 1500) });
}
