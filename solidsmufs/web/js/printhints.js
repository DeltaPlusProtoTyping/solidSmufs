// What hovering the words on a print shows, over the page view: an ISO fit's limits (H is a hole, h a shaft), French
// in English, and, with "Inches on hover" on, a metric size in inches. The marks come from the document's worker
// (kernel/printmarks.py): the PDF's own text at once, then what Windows OCR reads off the page's picture.
import { api } from './api.js';
import { h } from './ui.js';

const RANK = { fit: 0, dim: 1, fr: 2 }; // a size inside a French line wins over the line
const AGAIN = 1500; // ms between asks while OCR is still reading a page
const SLACK = 3; // css px around small text that still counts as on it

export class PrintHints {
  constructor(view) {
    this.v = view;
    this.doc = null;
    this.box = h('div', { class: 'pv-hint' });
    this.tip = h('div', { class: 'pv-tip', hidden: true });
    document.body.append(this.tip);
    this.btn = h('button', { class: 'pv-btn pv-toggle', text: 'Inches on hover',
      title: 'Hover a size on the print to see it in inches. Fit classes like H7 always show their limits (H is a hole,\nh a shaft), and French notes show in English. On by itself when the print looks metric.',
      onclick: () => this._inches(!this.store.inches) });
    this.status = h('span', { class: 'pv-of pv-ocr', hidden: true });
    view.chip.after(h('span', { class: 'pv-sep' }), this.btn, this.status);
    view.scroller.addEventListener('pointermove', (e) => this._move(e));
    view.scroller.addEventListener('pointerleave', () => this.hide());
    view.scroller.addEventListener('scroll', () => this.hide());
  }

  open(doc) {
    this.doc = doc;
    this.store = doc.printHints ||= { pages: {}, inches: null }; // kept with the document, across tabs and modes
    for (const [i, e] of Object.entries(this.store.pages)) if (e.waiting) delete this.store.pages[i]; // ask again
    this._button();
    this._status();
  }

  close() {
    this.doc = null;
    this.hide();
  }

  /** The pages now in view: ask for any not asked yet. */
  need(pages) {
    if (!this.doc) return;
    for (const p of pages) if (!this.store.pages[p.i]) this._ask(p.i);
  }

  async _ask(i) {
    const doc = this.doc, store = this.store;
    store.pages[i] = { ...(store.pages[i] || { marks: [] }), waiting: true };
    let r;
    try { r = await api.pdfMarks(doc.id, i); } catch { delete store.pages[i]; return; }
    store.pages[i] = { marks: r.marks, ocr: r.ocr, waiting: r.ocr === 'pending' };
    if (store.inches === null && (r.metric || r.ocr !== 'pending')) store.inches = !!r.metric; // metric prints turn it on
    if (doc !== this.doc) return; // another document's on screen: it asks again when it's back
    this._button();
    this._status();
    if (r.ocr === 'pending') setTimeout(() => { if (doc === this.doc && store.pages[i]?.waiting) this._ask(i); }, AGAIN);
  }

  _inches(on) {
    this.store.inches = on;
    this._button();
    this.hide();
  }

  _button() {
    this.btn.classList.toggle('on', !!this.store?.inches);
  }

  _status() {
    const pages = Object.values(this.store?.pages || {});
    const reading = pages.some((e) => e.ocr === 'pending'), failed = pages.some((e) => e.ocr === 'error');
    this.status.hidden = !reading && !failed;
    this.status.textContent = reading ? 'Reading the print…' : 'OCR couldn\'t read this print';
    this.status.title = reading ? 'Windows OCR is reading the page, for sizes drawn as lines' : '';
  }

  hide() {
    this.tip.hidden = true;
    this.box.remove();
    this.shown = null;
  }

  _move(e) {
    if (!this.doc || e.buttons) { this.hide(); return; } // not while panning or selecting
    const box = e.target.closest?.('.pv-pagebox');
    const p = box && this.v.pages[+box.dataset.page];
    const marks = p && this.store.pages[p.i]?.marks;
    if (!marks?.length) { this.hide(); return; }
    const [x, y] = this.v._pagePoint(p, e);
    const slack = SLACK * this.v._size(p)[0] / p.cssW; // in points
    const hits = marks.filter((m) => (m.kind !== 'dim' || this.store.inches)
      && x >= m.x - slack && x <= m.x + m.w + slack && y >= m.y - slack && y <= m.y + m.h + slack);
    if (!hits.length) { this.hide(); return; }
    const m = hits.reduce((a, b) => ((RANK[b.kind] - RANK[a.kind]) || (b.w * b.h - a.w * a.h)) < 0 ? b : a);
    if (this.shown !== m) {
      this.shown = m;
      this.box.className = `pv-hint ${m.kind}`;
      this.box.style.cssText = this.v._rectStyle(p, [m.x - 1, m.y - 1, m.w + 2, m.h + 2]);
      p.marks.append(this.box);
      this.tip.textContent = m.tip;
      this.tip.hidden = false;
    }
    // beside the pointer, kept inside the window
    const tw = this.tip.offsetWidth, th = this.tip.offsetHeight;
    const left = e.clientX + 16 + tw > innerWidth ? e.clientX - 12 - tw : e.clientX + 16;
    const top = e.clientY + 18 + th > innerHeight ? e.clientY - 10 - th : e.clientY + 18;
    this.tip.style.left = `${Math.max(left, 4)}px`;
    this.tip.style.top = `${Math.max(top, 4)}px`;
  }
}
