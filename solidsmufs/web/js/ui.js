// UI building blocks: element helper, menus (with submenus), floating dialogs, toasts, clipboard.
import { icon, tool } from './icons.js';

export function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export const iconEl = (name) => { const i = document.createElement('i'); i.dataset.icon = name; i.innerHTML = icon(name); return i; };
export const toolEl = (name, cls = 'ci') => h('span', { class: cls, html: tool(name) });

const layer = () => document.getElementById('layer');
const open = [];

export function closeMenus(depth = 0) {
  while (open.length > depth) open.pop().remove();
  if (!open.length) {
    document.removeEventListener('pointerdown', outside, true);
    document.removeEventListener('keydown', onKey, true);
    activeAnchor?.classList.remove('open');
    activeAnchor = null;
  }
}
let activeAnchor = null;
function outside(e) {
  if (open.some((m) => m.contains(e.target))) return;
  if (activeAnchor && activeAnchor.contains(e.target)) return;
  closeMenus();
}
function onKey(e) {
  if (e.key === 'Escape') { e.stopPropagation(); closeMenus(); }
}
export const menuOpen = () => open.length > 0;

// items: [{label, icon, glyph, kb, check, disabled, action, sub}] | {sep} | {head} | {el}
export function menu(anchor, items, opts = {}) {
  const depth = opts.depth || 0;
  if (!depth) {
    const toggling = activeAnchor === anchor && anchor && open.length;
    closeMenus();
    if (toggling && !opts.at && !opts.force) return null;
    activeAnchor = anchor || null;
    anchor?.classList.add('open');
  } else closeMenus(depth);
  const m = h('div', { class: `menu ${opts.cls || ''}` });
  for (const it of items) {
    if (!it) continue;
    if (it.sep) { m.append(h('div', { class: 'msep' })); continue; }
    if (it.head) { m.append(h('div', { class: 'mhead', text: it.head })); continue; }
    if (it.el) { m.append(it.el); continue; }
    const iconHtml = it.icon ? tool(it.icon) : it.glyph ? icon(it.glyph) : '';
    const b = h('button', { class: `mi${it.on ? ' on' : ''}`, disabled: it.disabled },
      it.check !== undefined ? h('span', { class: 'mi-check', text: it.check ? '✓' : '' }) : null,
      h('span', { class: 'mi-icon', html: iconHtml }),
      h('span', { text: it.label }),
      it.kb ? h('span', { class: 'kb', text: it.kb }) : null,
      it.sub ? h('span', { class: 'sub', text: '▶' }) : null);
    if (it.sub) {
      const openSub = () => {
        const r = b.getBoundingClientRect();
        menu(null, typeof it.sub === 'function' ? it.sub() : it.sub, { depth: depth + 1, at: { x: r.right - 2, y: r.top - 3 }, side: true });
      };
      b.addEventListener('mouseenter', openSub);
      b.addEventListener('click', openSub);
    } else {
      b.addEventListener('mouseenter', () => { closeMenus(depth + 1); it.hover?.(); });
      b.addEventListener('click', () => { closeMenus(); it.action?.(); });
    }
    m.append(b);
  }
  layer().append(m);
  const r = opts.at ? { left: opts.at.x, right: opts.at.x, top: opts.at.y, bottom: opts.at.y } : anchor.getBoundingClientRect();
  const mw = m.offsetWidth, mh = m.offsetHeight;
  let x = opts.align === 'center' ? (r.left + r.right) / 2 - mw / 2 : opts.align === 'right' ? r.right - mw : r.left;
  let y = opts.at ? r.top : r.bottom + 1;
  if (x + mw > innerWidth - 4) x = opts.side ? r.left - mw - 0 : innerWidth - mw - 4;
  x = Math.max(4, x);
  if (y + mh > innerHeight - 4) y = Math.max(4, innerHeight - mh - 4);
  m.style.left = `${x}px`;
  m.style.top = `${y}px`;
  open.push(m);
  if (open.length === 1) {
    setTimeout(() => {
      document.addEventListener('pointerdown', outside, true);
      document.addEventListener('keydown', onKey, true);
    });
  }
  return m;
}

export function toast(msg, kind = 'ok', ms = 2600) {
  const icons = { ok: 'check', error: 'warn', warn: 'warn', info: 'info' };
  const t = h('div', { class: `toast ${kind}` }, iconEl(icons[kind] || 'info'), h('span', { text: msg }));
  document.getElementById('toasts').append(t);
  setTimeout(() => {
    t.style.transition = 'opacity .25s';
    t.style.opacity = '0';
    setTimeout(() => t.remove(), 260);
  }, kind === 'error' ? Math.max(ms, 6000) : ms);
  return t;
}

// A floating, draggable, resizable window (SolidWorks' Measure / Mass Properties style).
let zTop = 100;
export class Dialog {
  constructor({ key, title, icon: iconName, width = 360, height = null, tools = null, body, foot = null, onClose = null, resizable = true, at = null }) {
    this.key = key;
    this.at = at;  // (width, height) => {x, y}: where it opens every time, instead of where it was last left
    this.onClose = onClose;
    this.el = h('div', { class: 'dialog', style: { width: `${width}px`, height: height ? `${height}px` : null, zIndex: ++zTop } });
    this.titleEl = h('span', { class: 'dl-title', text: title });
    const head = h('div', { class: 'dl-head' },
      iconName ? h('span', { class: 'dl-icon', html: tool(iconName) }) : null, this.titleEl,
      h('button', { class: 'dl-x', title: 'Close', text: '×', onclick: () => this.close() }));
    this.toolsEl = tools ? h('div', { class: 'dl-tools' }, tools) : null;
    this.bodyEl = h('div', { class: 'dl-body' }, body);
    this.footEl = foot ? h('div', { class: 'dl-foot' }, foot) : null;
    this.el.append(head, ...[this.toolsEl, this.bodyEl, this.footEl].filter(Boolean));
    if (resizable) this.el.append(h('div', { class: 'dl-resize' }));
    layer().append(this.el);
    this._place();
    this.el.addEventListener('pointerdown', () => { this.el.style.zIndex = ++zTop; });
    this._drag(head);
    if (resizable) this._resize(this.el.querySelector('.dl-resize'));
  }

  _saved() { try { return JSON.parse(localStorage.getItem(`dlg:${this.key}`) || 'null'); } catch { return null; } }
  _save() {
    try {
      const r = this.el.getBoundingClientRect();
      localStorage.setItem(`dlg:${this.key}`, JSON.stringify({ x: r.left, y: r.top, w: r.width, h: this.el.style.height ? r.height : null }));
    } catch { /* storage off */ }
  }

  _place() {
    const s = this.key && this._saved();
    const r = this.el.getBoundingClientRect();
    let x = s?.x ?? Math.max(20, innerWidth - r.width - 70);
    let y = s?.y ?? 150;
    if (s?.w) this.el.style.width = `${s.w}px`;
    if (s?.h) this.el.style.height = `${s.h}px`;
    const fixed = this.at?.(this.el.offsetWidth, this.el.offsetHeight);
    if (fixed) {  // opens in its spot as tall as its contents, growing no further than fixed.bottom
      ({ x, y } = fixed);
      this.el.style.height = '';
      this.el.style.maxHeight = `${Math.max(160, (fixed.bottom ?? innerHeight - 12) - y)}px`;
    }
    x = Math.min(Math.max(0, x), innerWidth - 120);
    y = Math.min(Math.max(0, y), innerHeight - 60);
    this.el.style.left = `${x}px`;
    this.el.style.top = `${y}px`;
  }

  _drag(handle) {
    handle.addEventListener('pointerdown', (e) => {
      if (e.target.closest('button')) return;
      const r = this.el.getBoundingClientRect();
      const dx = e.clientX - r.left, dy = e.clientY - r.top;
      handle.setPointerCapture(e.pointerId);
      const move = (ev) => {
        this.el.style.left = `${Math.min(Math.max(0, ev.clientX - dx), innerWidth - 80)}px`;
        this.el.style.top = `${Math.min(Math.max(0, ev.clientY - dy), innerHeight - 30)}px`;
      };
      const up = () => { handle.removeEventListener('pointermove', move); handle.removeEventListener('pointerup', up); this._save(); };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', up);
    });
  }

  _resize(grip) {
    grip.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      const r = this.el.getBoundingClientRect();
      const sx = e.clientX, sy = e.clientY;
      grip.setPointerCapture(e.pointerId);
      const move = (ev) => {
        this.el.style.width = `${Math.max(260, r.width + ev.clientX - sx)}px`;
        this.el.style.height = `${Math.max(160, r.height + ev.clientY - sy)}px`;
      };
      const up = () => { grip.removeEventListener('pointermove', move); grip.removeEventListener('pointerup', up); this._save(); };
      grip.addEventListener('pointermove', move);
      grip.addEventListener('pointerup', up);
    });
  }

  setTitle(t) { this.titleEl.textContent = t; }
  setBody(...nodes) { this.bodyEl.replaceChildren(...nodes.flat().filter(Boolean)); }
  get closed() { return !this.el.isConnected; }
  close() {
    if (!this.el.isConnected) return;
    this._save();
    this.el.remove();
    this.onClose?.();
  }
}

export function modal(title, body, opts = {}) {
  const back = h('div', { class: 'modal-back' });
  const d = new Dialog({ key: null, title, icon: opts.icon, width: opts.width || 640, body, resizable: false, onClose: () => back.remove() });
  layer().insertBefore(back, d.el);
  d.el.style.left = `${(innerWidth - d.el.offsetWidth) / 2}px`;
  d.el.style.top = `${Math.max(30, (innerHeight - d.el.offsetHeight) / 2)}px`;
  back.addEventListener('pointerdown', () => d.close());
  const onKey = (e) => { if (e.key === 'Escape') { d.close(); document.removeEventListener('keydown', onKey, true); } };
  document.addEventListener('keydown', onKey, true);
  return d;
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = h('textarea', { style: { position: 'fixed', opacity: '0' } });
    ta.value = text;
    document.body.append(ta);
    ta.select();
    const ok = document.execCommand('copy');
    ta.remove();
    return ok;
  }
}

export function debounce(fn, ms) {
  let t = null;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// a number box with spinner arrows (SolidWorks PropertyManager style)
export function spinBox(value, { step = 1, onChange, width = null, format = (v) => String(v), parse = parseFloat } = {}) {
  const inp = h('input', { class: 'inp', value: format(value), style: width ? { width } : null });
  const commit = () => { const v = parse(inp.value); if (Number.isFinite(v)) onChange?.(v); };
  inp.addEventListener('change', commit);
  inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') commit(); });
  const bump = (k) => { const v = (parse(inp.value) || 0) + k * step; inp.value = format(v); onChange?.(v); };
  return h('div', { class: 'spin-inp' }, inp, h('div', { class: 'sbtns' },
    h('button', { text: '▲', onclick: () => bump(1) }), h('button', { text: '▼', onclick: () => bump(-1) })));
}
