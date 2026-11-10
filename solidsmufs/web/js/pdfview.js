// PDF pages over the graphics area. Pages are drawn by the document's worker (PDFium) at exactly the screen's
// pixels, in tiles, so text and fine lines stay sharp at any zoom. While a new zoom is being drawn the tiles
// already here are stretched to fit, so zooming answers at once, and the newest view is always drawn first.
import { api } from './api.js';
import { h, toast } from './ui.js';
import { PrintHints } from './printhints.js';

const TILE = 1536; // device pixels: large, as a word cut by a seam can differ by a pixel across it
const PREVIEW = 900; // long side of the whole-page picture that shows until the tiles land
const GAP = 10; // css px between pages
const IN_FLIGHT = 2;
const MAX_TILES = 60;
const POINT = 96 / 72; // css px per point at 100%
const clamp = (x, a, b) => Math.min(Math.max(x, a), b);

export class PdfView {
  constructor(host, onMode) {
    this.host = host;
    this.onMode = onMode;
    this.doc = null;
    this.run = 0; // bumps when the view is rebuilt: answers for an older one are dropped
    this.el = h('div', { class: 'pdfview', hidden: true });
    this.bar = h('div', { class: 'pv-bar' });
    this.side = h('div', { class: 'pv-side' });
    this.scroller = h('div', { class: 'pv-scroll', tabindex: '0' });
    this.sheet = h('div', { class: 'pv-sheet' });
    this.scroller.append(this.sheet);
    this.el.append(this.bar, h('div', { class: 'pv-body' }, this.side, this.scroller));
    host.append(this.el);
    // a 3D PDF's switch between its model and its pages
    this.toModel = h('button', { class: 'pv-sw', text: '3D model', onclick: () => this.onMode('model') });
    this.toPages = h('button', { class: 'pv-sw', text: 'Pages', onclick: () => this.onMode('pages') });
    this.modeSwitch = h('div', { class: 'pv-switch', hidden: true }, this.toModel, this.toPages);
    host.append(this.modeSwitch);
    this._buildBar();
    this.hints = new PrintHints(this); // fits, inches and French on hover
    this.scroller.addEventListener('scroll', () => { this._schedule(); this._pageNumber(); });
    this.scroller.addEventListener('wheel', (e) => this._wheel(e), { passive: false });
    this.scroller.addEventListener('pointerdown', (e) => this._down(e));
    new ResizeObserver(() => { if (this.doc && !this.el.hidden) this._resized(); }).observe(this.scroller);
    document.addEventListener('keydown', (e) => this._key(e), true);
    document.addEventListener('copy', (e) => {
      if (this.doc && this.selection?.text) {
        e.clipboardData.setData('text/plain', this.selection.text);
        e.preventDefault();
      }
    });
  }

  // ================================================================== toolbar
  _buildBar() {
    const btn = (text, tip, run) => h('button', { class: 'pv-btn', text, title: tip, onclick: run });
    this.pageIn = h('input', { class: 'pv-page', title: 'Go to page', spellcheck: 'false' });
    this.pageIn.addEventListener('change', () => this.goto(parseInt(this.pageIn.value, 10) - 1));
    this.pageOf = h('span', { class: 'pv-of' });
    this.zoomLabel = h('span', { class: 'pv-zoom', title: 'Zoom' });
    this.findIn = h('input', { class: 'pv-find', placeholder: 'Find in PDF', spellcheck: 'false' });
    this.findIn.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { this._find(e.shiftKey ? -1 : 1); e.preventDefault(); }
      if (e.key === 'Escape') { this.findIn.value = ''; this._clearFind(); this.scroller.focus(); }
      e.stopPropagation();
    });
    this.findCount = h('span', { class: 'pv-of' });
    this.chip = h('span', { class: 'pv-chip', hidden: true });
    this.bar.append(
      btn('☰', 'Page thumbnails', () => this._toggleSide()),
      h('span', { class: 'pv-sep' }),
      btn('‹', 'Previous page (Page Up)', () => this.goto(this.current - 1)), this.pageIn, this.pageOf,
      btn('›', 'Next page (Page Down)', () => this.goto(this.current + 1)),
      h('span', { class: 'pv-sep' }),
      btn('−', 'Zoom out (-)', () => this.zoomBy(1 / 1.25)), this.zoomLabel, btn('+', 'Zoom in (+)', () => this.zoomBy(1.25)),
      btn('Fit page', 'See the whole page (Ctrl+0)', () => this.setFit('page')),
      btn('Fit width', 'Fill the width', () => this.setFit('width')),
      btn('100%', 'Actual size', () => this.setFit(null, 1)),
      h('span', { class: 'pv-sep' }),
      btn('⟳', 'Turn the pages a quarter turn', () => this.turn()),
      this.chip,
      h('span', { class: 'pv-grow' }),
      this.findCount, this.findIn,
    );
  }

  _toggleSide() {
    this.state.side = !this.state.side;
    this.side.hidden = !this.state.side;
    if (this.state.side) this._thumbs();
  }

  // ================================================================== opening
  open(doc) {
    if (this.doc === doc) return;
    this.close();
    this.doc = doc;
    this.run++;
    this.pagesInfo = doc.meta.pdf.pages;
    this.state = doc.pdfState ||= { zoom: 1, fit: this.pagesInfo.length > 1 ? 'width' : 'page', turns: 0, top: 0, side: this.pagesInfo.length > 1 };
    this.pageOf.textContent = `/ ${this.pagesInfo.length}`;
    const models = doc.meta.pdf.models || [], hasModel = doc.meta.bodies.length > 0;
    this.chip.hidden = !models.length || hasModel;
    this.chip.title = doc.meta.pdf.problem || '';
    this.chip.textContent = `3D model inside (${models.join(', ')}): can't be shown yet`;
    this.modeSwitch.hidden = !hasModel;
    this.findIn.hidden = !!doc.meta.pdf.picture; // a picture has no text to find
    this.side.hidden = !this.state.side;
    this._buildPages();
    this.hints.open(doc);
    this.setMode(doc.pdfMode);
  }

  // show the pages, or step aside for the 3D view beneath
  setMode(mode) {
    const pages = mode === 'pages';
    if (!pages && !this.el.hidden && this.state) this.state.top = this.scroller.scrollTop;
    this.toModel.classList.toggle('on', !pages);
    this.toPages.classList.toggle('on', pages);
    this.el.hidden = !pages;
    if (!pages) return;
    this._resized();
    this.scroller.scrollTop = this.state.top;
    if (this.state.side) this._thumbs();
    this.scroller.focus({ preventScroll: true });
  }

  close() {
    if (this.doc?.pdfState && !this.el.hidden) this.doc.pdfState.top = this.scroller.scrollTop;
    this.doc = null;
    this.hints?.close();
    this.run++;
    this.el.hidden = true;
    this.modeSwitch.hidden = true;
    this.sheet.replaceChildren();
    this.side.replaceChildren();
    this.pages = [];
    this.queue = [];
    this.busy = 0;
    this.selection = null;
    this.hits = [];
  }

  _buildPages() {
    this.sheet.replaceChildren();
    this.pages = this.pagesInfo.map((p, i) => {
      const el = h('div', { class: 'pv-pagebox' });
      const marks = h('div', { class: 'pv-marks' });
      el.append(marks);
      this.sheet.append(el);
      el.dataset.page = i;
      return { i, el, marks, info: p, tiles: new Map(), preview: null };
    });
  }

  // size of a page as shown, in points, once turned
  _size(p) {
    return this.state.turns % 2 ? [p.info.h, p.info.w] : [p.info.w, p.info.h];
  }

  _fitZoom(mode) {
    const pad = 2 * GAP + 2;
    const W = this.scroller.clientWidth - pad, H = this.scroller.clientHeight - pad;
    const widest = Math.max(...this.pages.map((p) => this._size(p)[0]));
    const [w0, h0] = this._size(this.pages[this._at() || 0]);
    const z = mode === 'width' ? W / widest : Math.min(W / w0, H / h0);
    return clamp(z / POINT, 0.05, 64);
  }

  _resized() {
    if (this.state.fit) this.state.zoom = this._fitZoom(this.state.fit);
    this._layout();
    this._schedule();
  }

  _layout() {
    const dpr = window.devicePixelRatio || 1, z = this.state.zoom;
    const view = this.scroller.clientWidth;
    let y = GAP, right = view;
    for (const p of this.pages) {
      const [w, hh] = this._size(p);
      p.scale = z * POINT * dpr; // device pixels per point
      p.W = Math.max(Math.round(w * p.scale), 1);
      p.H = Math.max(Math.round(hh * p.scale), 1);
      p.scale = p.W / w;
      p.cssW = p.W / dpr;
      p.cssH = p.H / dpr;
      // on whole device pixels, so the tiles land one to one and don't blur
      p.x = Math.round(Math.max(GAP, (view - p.cssW) / 2) * dpr) / dpr;
      p.y = Math.round(y * dpr) / dpr;
      p.el.style.cssText = `left:${p.x}px;top:${p.y}px;width:${p.cssW}px;height:${p.cssH}px`;
      y += p.cssH + GAP;
      right = Math.max(right, p.x + p.cssW + GAP);
    }
    this.sheet.style.width = `${right}px`;
    this.sheet.style.height = `${y}px`;
    this.zoomLabel.textContent = `${Math.round(z * 100)}%`;
    this._pageNumber();
  }

  // ================================================================== moving around
  _at() {
    const mid = this.scroller.scrollTop + this.scroller.clientHeight / 2;
    if (!this.pages?.length) return 0;
    let i = this.pages.findIndex((p) => p.y !== undefined && p.y + p.cssH + GAP > mid);
    if (i < 0) i = this.pages.length - 1;
    return i;
  }

  _pageNumber() {
    this.current = this._at();
    if (document.activeElement !== this.pageIn) this.pageIn.value = this.pagesInfo?.length ? this.current + 1 : '';
    for (const t of this.side.children) t.classList.toggle('on', +t.dataset.page === this.current);
  }

  goto(i) {
    if (!this.pages?.length || Number.isNaN(i)) return;
    const p = this.pages[clamp(i, 0, this.pages.length - 1)];
    this.scroller.scrollTop = p.y - GAP;
    this._pageNumber();
  }

  setFit(fit, zoom) {
    this.state.fit = fit;
    this._zoomTo(fit ? this._fitZoom(fit) : zoom);
  }

  zoomBy(f, cx, cy) {
    this.state.fit = null;
    this._zoomTo(clamp(this.state.zoom * f, 0.05, 64), cx, cy);
  }

  // change the zoom keeping the point under (cx, cy) in the scroller where it is
  _zoomTo(z, cx = this.scroller.clientWidth / 2, cy = this.scroller.clientHeight / 2) {
    const s = this.scroller, px = s.scrollLeft + cx, py = s.scrollTop + cy;
    const p = this.pages.find((q) => py < q.y + q.cssH + GAP / 2) || this.pages[this.pages.length - 1];
    const fx = (px - p.x) / p.cssW, fy = (py - p.y) / p.cssH;
    this.state.zoom = z;
    this._layout();
    s.scrollLeft = p.x + fx * p.cssW - cx;
    s.scrollTop = p.y + fy * p.cssH - cy;
    this._schedule(70);
  }

  turn() {
    this.state.turns = (this.state.turns + 1) % 4;
    this.run++;
    this.queue = [];
    this.selection = null;
    this._buildPages();
    this.side.replaceChildren();
    this._resized();
    if (this.state.side) this._thumbs();
    this._showHits();
  }

  _wheel(e) {
    const rect = this.scroller.getBoundingClientRect();
    // a single sheet zooms on the wheel like the 3D view; a longer document scrolls unless Ctrl is held
    if (e.ctrlKey || this.pages.length === 1) {
      e.preventDefault();
      this.zoomBy(Math.exp(-e.deltaY * 0.0018), e.clientX - rect.left, e.clientY - rect.top);
    }
  }

  _key(e) {
    if (!this.doc || this.el.hidden) return;
    const typing = /INPUT|TEXTAREA/.test(document.activeElement?.tagName || '');
    const done = () => { e.preventDefault(); e.stopPropagation(); };
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') { this.findIn.focus(); this.findIn.select(); done(); return; }
    if (typing) return;
    if ((e.ctrlKey || e.metaKey) && e.key === '0') { this.setFit('page'); done(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === 'PageDown') { this.goto(this.current + 1); done(); }
    else if (e.key === 'PageUp') { this.goto(this.current - 1); done(); }
    else if (e.key === 'Home') { this.goto(0); done(); }
    else if (e.key === 'End') { this.goto(this.pages.length - 1); done(); }
    else if (e.key === '+' || e.key === '=') { this.zoomBy(1.25); done(); }
    else if (e.key === '-') { this.zoomBy(1 / 1.25); done(); }
    else if (e.key === 'r' || e.key === 'R') { this.turn(); done(); }
  }

  // ================================================================== drawing
  _schedule(delay = 0) {
    clearTimeout(this._timer);
    this._timer = setTimeout(() => { if (this.doc && !this.el.hidden) this._wanted(); }, delay);
  }

  _visible() {
    const s = this.scroller, top = s.scrollTop, bottom = top + s.clientHeight, out = [];
    for (const p of this.pages) if (p.y !== undefined && p.y + p.cssH >= top && p.y <= bottom) out.push(p);
    return out;
  }

  // what the current view needs, nearest its middle first; replaces whatever was waiting
  _wanted() {
    const s = this.scroller, dpr = window.devicePixelRatio || 1, want = [];
    const left = s.scrollLeft, right = left + s.clientWidth, top = s.scrollTop, bottom = top + s.clientHeight;
    const mx = (left + right) / 2, my = (top + bottom) / 2;
    for (const p of this._visible()) {
      if (!p.preview && !p.previewAsked) want.push({ kind: 'preview', p, rank: -1 });
      const x0 = Math.floor(Math.max(left - p.x, 0) * dpr / TILE), x1 = Math.floor(Math.min(right - p.x, p.cssW - 0.01) * dpr / TILE);
      const y0 = Math.floor(Math.max(top - p.y, 0) * dpr / TILE), y1 = Math.floor(Math.min(bottom - p.y, p.cssH - 0.01) * dpr / TILE);
      for (let iy = y0; iy <= y1; iy++) {
        for (let ix = x0; ix <= x1; ix++) {
          if (p.tiles.has(this._key3(p, ix, iy))) continue;
          const cx = p.x + (ix + 0.5) * TILE / dpr, cy = p.y + (iy + 0.5) * TILE / dpr;
          want.push({ kind: 'tile', p, ix, iy, rank: Math.hypot(cx - mx, cy - my) });
        }
      }
    }
    want.sort((a, b) => a.rank - b.rank);
    this.queue = want;
    this._pump();
    this._retire();
    this.hints.need(); // once the pages in view are drawn
  }

  _key3(p, ix, iy) { return `${p.W}:${ix}:${iy}`; }

  _pump() {
    while (this.busy < IN_FLIGHT && this.queue.length) {
      const job = this.queue.shift();
      this.busy++;
      const run = this.run;
      const finish = () => {
        if (run === this.run) { this.busy--; this._pump(); if (!this.queue.length && !this.busy) this._retire(); }
      };
      (job.kind === 'preview' ? this._preview(job.p, run) : this._tile(job, run)).catch((e) => {
        if (run === this.run) console.warn('PDF page:', e.message);
      }).finally(finish);
    }
  }

  _paint(buffer, w, hh) {
    const c = document.createElement('canvas');
    c.width = w;
    c.height = hh;
    c.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(buffer), w, hh), 0, 0);
    return c;
  }

  async _preview(p, run) {
    p.previewAsked = true;
    const [w, hh] = this._size(p), scale = PREVIEW / Math.max(w, hh);
    const W = Math.max(Math.round(w * scale), 1), H = Math.max(Math.round(hh * scale), 1);
    const buf = await api.pdfTile(this.doc.id, { page: p.i, scale, x: 0, y: 0, w: W, h: H, turns: this.state.turns });
    if (run !== this.run) return;
    const c = this._paint(buf, W, H);
    c.className = 'pv-preview';
    p.el.prepend(c);
    p.preview = c;
  }

  async _tile({ p, ix, iy }, run) {
    const W = p.W, H = p.H, key = this._key3(p, ix, iy);
    const x = ix * TILE, y = iy * TILE, w = Math.min(TILE, W - x), hh = Math.min(TILE, H - y);
    if (w <= 0 || hh <= 0) return;
    const buf = await api.pdfTile(this.doc.id, { page: p.i, scale: p.scale, x, y, w, h: hh, turns: this.state.turns });
    if (run !== this.run || p.W !== W) return; // zoomed on meanwhile (its replacement is on the way)
    const c = this._paint(buf, w, hh);
    c.className = 'pv-tile';
    c.style.cssText = `left:${x / W * 100}%;top:${y / H * 100}%;width:${w / W * 100}%;height:${hh / H * 100}%`;
    p.el.insertBefore(c, p.marks);
    p.tiles.set(key, { c, W });
  }

  // tiles from other zooms go once the view's own have landed; tiles far away go when there are too many
  _retire() {
    const shown = new Set(this._visible());
    const settled = !this.queue?.length && !this.busy;
    let count = 0;
    for (const p of this.pages) {
      for (const [k, t] of p.tiles) {
        if (t.W !== p.W && (settled || !shown.has(p))) { t.c.remove(); p.tiles.delete(k); } else count++;
      }
    }
    if (count > MAX_TILES) {
      for (const p of this.pages) {
        if (shown.has(p)) continue;
        for (const [k, t] of p.tiles) { t.c.remove(); p.tiles.delete(k); }
      }
    }
  }

  // ================================================================== thumbnails
  _thumbs() {
    if (this.side.children.length) return;
    const io = new IntersectionObserver((rows) => {
      for (const r of rows) {
        if (!r.isIntersecting || r.target.dataset.done) continue;
        r.target.dataset.done = '1';
        this._thumb(r.target);
      }
    }, { root: this.side, rootMargin: '200px' });
    for (const p of this.pages) {
      const [w, hh] = this._size(p);
      const t = h('button', { class: 'pv-thumb', title: `Page ${p.i + 1}`, onclick: () => this.goto(p.i) },
        h('span', { class: 'pv-tpage', style: { aspectRatio: `${w} / ${hh}` } }), h('span', { class: 'pv-tnum', text: String(p.i + 1) }));
      t.dataset.page = p.i;
      this.side.append(t);
      io.observe(t);
    }
    this._pageNumber();
  }

  async _thumb(el) {
    const run = this.run, p = this.pages[+el.dataset.page];
    const [w, hh] = this._size(p), scale = 2 * 112 / w, W = 224, H = Math.max(Math.round(hh * scale), 1);
    try {
      const buf = await api.pdfTile(this.doc.id, { page: p.i, scale, x: 0, y: 0, w: W, h: H, turns: this.state.turns });
      if (run === this.run) el.firstChild.append(this._paint(buf, W, H));
    } catch { /* the page itself will say */ }
  }

  // ================================================================== selecting text and panning
  _pagePoint(p, e) {
    const r = p.el.getBoundingClientRect(), [w, hh] = this._size(p);
    const dx = (e.clientX - r.left) / r.width * w, dy = (e.clientY - r.top) / r.height * hh;
    const W = p.info.w, H = p.info.h;
    switch (this.state.turns) { // back to the page's own points
      case 1: return [dy, H - dx];
      case 2: return [W - dx, H - dy];
      case 3: return [W - dy, dx];
      default: return [dx, dy];
    }
  }

  _down(e) {
    const s = this.scroller;
    if (e.button === 1 || (e.button === 0 && !e.shiftKey)) { // left or middle drag pans; Shift+left-drag selects text
      e.preventDefault();
      s.focus({ preventScroll: true });
      if (e.button === 0 && this.selection) { this.selection = null; this._showSelection(); }
      const x0 = e.clientX, y0 = e.clientY, l0 = s.scrollLeft, t0 = s.scrollTop;
      s.classList.add('panning');
      const move = (m) => { s.scrollLeft = l0 - (m.clientX - x0); s.scrollTop = t0 - (m.clientY - y0); };
      const up = () => { s.classList.remove('panning'); window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
      return;
    }
    if (e.button !== 0) return;
    const box = e.target.closest?.('.pv-pagebox');
    this.selection = null;
    this._showSelection();
    if (!box) return;
    e.preventDefault();
    s.focus({ preventScroll: true });
    const p = this.pages[+box.dataset.page], from = this._pagePoint(p, e);
    let pending = false, last = null;
    const ask = async () => {
      if (pending || !last) return;
      pending = true;
      const to = last;
      last = null;
      try {
        const r = await api.pdfSelect(this.doc.id, { page: p.i, ax: from[0], ay: from[1], bx: to[0], by: to[1] });
        this.selection = { page: p.i, ...r };
        this._showSelection();
      } catch { /* nothing selected */ }
      pending = false;
      ask();
    };
    const move = (m) => { last = this._pagePoint(p, m); ask(); };
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }

  // a rectangle in the page's own points, as percentages of the page as shown
  _rectStyle(p, [x, y, w, hh]) {
    const W = p.info.w, H = p.info.h, t = this.state.turns;
    const [a, b, c, d] = t === 1 ? [H - y - hh, x, hh, w] : t === 2 ? [W - x - w, H - y - hh, w, hh] : t === 3 ? [y, W - x - w, hh, w] : [x, y, w, hh];
    const [sw, sh] = this._size(p);
    return `left:${a / sw * 100}%;top:${b / sh * 100}%;width:${c / sw * 100}%;height:${d / sh * 100}%`;
  }

  _showSelection() {
    for (const p of this.pages) p.marks.querySelectorAll('.pv-sel').forEach((n) => n.remove());
    if (!this.selection) return;
    const p = this.pages[this.selection.page];
    for (const r of this.selection.rects) p.marks.append(h('div', { class: 'pv-sel', style: this._rectStyle(p, r) }));
  }

  // ================================================================== find
  async _find(dir) {
    const q = this.findIn.value.trim();
    if (!q) { this._clearFind(); return; }
    if (q !== this.findQuery) {
      try {
        this.hits = await api.pdfFind(this.doc.id, q);
      } catch (e) { toast(e.message, 'error'); return; }
      this.findQuery = q;
      this.hitAt = -1;
    }
    if (!this.hits.length) { this.findCount.textContent = 'Not found'; this._showHits(); return; }
    this.hitAt = (this.hitAt + dir + this.hits.length) % this.hits.length;
    this.findCount.textContent = `${this.hitAt + 1} of ${this.hits.length}`;
    this._showHits();
    const hit = this.hits[this.hitAt], p = this.pages[hit.page], mark = p.marks.querySelector('.pv-hit.now');
    if (mark) mark.scrollIntoView({ block: 'center', inline: 'nearest' });
    else this.goto(hit.page);
  }

  _clearFind() {
    this.findQuery = null;
    this.hits = [];
    this.findCount.textContent = '';
    this._showHits();
  }

  _showHits() {
    for (const p of this.pages) p.marks.querySelectorAll('.pv-hit').forEach((n) => n.remove());
    (this.hits || []).forEach((hit, k) => {
      const p = this.pages[hit.page];
      for (const r of hit.rects) p.marks.append(h('div', { class: `pv-hit${k === this.hitAt ? ' now' : ''}`, style: this._rectStyle(p, r) }));
    });
  }
}
