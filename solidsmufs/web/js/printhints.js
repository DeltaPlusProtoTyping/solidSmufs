// What hovering the words on a print shows, over the page view: an ISO fit's limits (H is a hole, h a shaft), French
// in English, and, with "Inches on hover" on, a metric size in inches. The marks come from the document's worker
// (kernel/printmarks.py): the PDF's own text at once, then what Windows OCR reads off the page's picture.
import { api } from './api.js';
import { h } from './ui.js';

const RANK = { gdt: -1, fit: 0, dim: 1, fr: 2 }; // a size inside a French line wins over the line
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
    this.tpBtn = h('button', { class: 'pv-btn pv-toggle', text: 'TP on hover',
      title: 'Hover a feature control frame (true position and the other geometric tolerances) to see what it means,\nits zone, and how hard it is to hold and to measure, from 1 to 10. The scores are a first guess, still being tuned.',
      onclick: () => { this.store.tp = !this.store.tp; try { localStorage.setItem('pv:tp', this.store.tp ? '1' : '0'); } catch { /* storage off */ } this._button(); this.hide(); } });
    this.status = h('span', { class: 'pv-of pv-ocr', hidden: true });
    view.chip.after(h('span', { class: 'pv-sep' }), this.btn, this.tpBtn, this.status);
    view.scroller.addEventListener('pointermove', (e) => this._move(e));
    view.scroller.addEventListener('pointerleave', () => this.hide());
    view.scroller.addEventListener('scroll', () => this.hide());
  }

  open(doc) {
    this.doc = doc;
    this.store = doc.printHints ||= { pages: {}, inches: null }; // kept with the document, across tabs and modes
    if (this.store.tp === undefined) { let on = true; try { on = localStorage.getItem('pv:tp') !== '0'; } catch { /* storage off */ } this.store.tp = on; }
    for (const [i, e] of Object.entries(this.store.pages)) if (e.waiting) delete this.store.pages[i]; // ask again
    this._button();
    this._status();
  }

  close() {
    this.doc = null;
    this.hide();
  }

  /** Ask for the hints of the pages in view not asked yet, once their pictures are all drawn: reading a page's
   *  words takes the worker a while, and the page itself mustn't wait behind it. */
  need() {
    clearTimeout(this._later);
    if (!this.doc) return;
    const v = this.v;
    if (v.busy || v.queue?.length) { this._later = setTimeout(() => this.need(), 250); return; }
    for (const p of v._visible()) if (!this.store.pages[p.i]) { this._ask(p.i); return; } // one at a time, the view first
    // then the rest of the print, so the part's overall difficulty counts every page (not a long manual's)
    if (v.pages.length <= 40) for (const p of v.pages) if (!this.store.pages[p.i]) { this._ask(p.i); return; }
  }

  async _ask(i) {
    const doc = this.doc, store = this.store;
    store.pages[i] = { ...(store.pages[i] || { marks: [] }), waiting: true };
    let r;
    try { r = await api.pdfMarks(doc.id, i); } catch { delete store.pages[i]; return; }
    store.pages[i] = { marks: r.marks, ocr: r.ocr, reading: r.reading, waiting: r.reading || r.ocr === 'pending' };
    // the whole part's difficulty, on the command bar: shown as it stands, and marked while pages are still being read
    const part = r.part ? { ...r.part, whole: r.part.whole && Object.keys(store.pages).length >= Math.min(this.v.pages.length, 40) } : null;
    if (JSON.stringify(part) !== JSON.stringify(doc.partDifficulty || null)) {
      doc.partDifficulty = part;
      this.v.app?.shell?.renderCommandManager();
    }
    if (store.inches === null && !r.reading && (r.metric || r.ocr !== 'pending')) store.inches = !!r.metric; // metric prints turn it on
    if (doc !== this.doc) return; // another document's on screen: it asks again when it's back
    this._button();
    this._status();
    if (r.reading) this._again(i, 0); // more of the page to read: the next slice, between the page's pictures
    else if (r.ocr === 'pending') this._again(i, AGAIN); // OCR is reading it on its own
    else this.need(); // the next page in view, if any
  }

  /** Ask about page i again after `ms`, once no page pictures are waiting to be drawn. */
  _again(i, ms) {
    const doc = this.doc;
    setTimeout(() => {
      if (doc !== this.doc || !this.store.pages[i]?.waiting) return;
      if (this.v.busy || this.v.queue?.length) { this._again(i, 150); return; }
      this._ask(i);
    }, ms);
  }

  _inches(on) {
    this.store.inches = on;
    this._button();
    this.hide();
  }

  _button() {
    this.btn.classList.toggle('on', !!this.store?.inches);
    this.tpBtn.classList.toggle('on', !!this.store?.tp);
  }

  _status() {
    const pages = Object.values(this.store?.pages || {});
    const reading = pages.some((e) => e.reading || e.ocr === 'pending'), failed = pages.some((e) => e.ocr === 'error');
    this.status.hidden = !reading && !failed;
    this.status.textContent = reading ? 'Reading the print…' : 'OCR couldn\'t read this print';
    this.status.title = reading ? 'Windows OCR is reading the page, for sizes drawn as lines' : '';
  }

  hide() {
    this.tip.hidden = true;
    this.box.remove();
    this.shown = null;
  }

  // a geometric tolerance's popup: what it is in a few short lines, then how hard it is to machine and to measure,
  // each as a gauge of ten cells from green (easy) through yellow to red (hard)
  _card(c) {
    const gauge = (label, n) => h('div', { class: 'pv-gauge' }, h('span', { class: 'pv-gl', text: label }),
      h('span', { class: 'pv-gb' }, ...Array.from({ length: 10 }, (_, i) => h('i', { class: i < n ? 'on' : '', style: i < n ? { background: `hsl(${Math.round(125 - (125 * i) / 9)} 75% 42%)` } : null }))),
      h('span', { class: 'pv-gn', text: `${n}/10` }));
    return [
      h('div', { class: 'pv-ch', text: c.head }),
      ...c.lines.map((t) => h('div', { class: 'pv-cl', text: t })),
      ...c.notes.map((t) => h('div', { class: 'pv-cn', text: t })),
      h('div', { class: 'pv-cg' }, gauge('Machining', c.machining), gauge('Measuring', c.measuring)),
    ];
  }

  _move(e) {
    if (!this.doc || e.buttons) { this.hide(); return; } // not while panning or selecting
    const box = e.target.closest?.('.pv-pagebox');
    const p = box && this.v.pages[+box.dataset.page];
    const marks = p && this.store.pages[p.i]?.marks;
    if (!marks?.length) { this.hide(); return; }
    const [x, y] = this.v._pagePoint(p, e);
    const slack = SLACK * this.v._size(p)[0] / p.cssW; // in points
    const hits = marks.filter((m) => (m.kind !== 'dim' || this.store.inches) && (m.kind !== 'gdt' || this.store.tp)
      && x >= m.x - slack && x <= m.x + m.w + slack && y >= m.y - slack && y <= m.y + m.h + slack);
    if (!hits.length) { this.hide(); return; }
    const m = hits.reduce((a, b) => ((RANK[b.kind] - RANK[a.kind]) || (b.w * b.h - a.w * a.h)) < 0 ? b : a);
    if (this.shown !== m) {
      this.shown = m;
      this.box.className = `pv-hint ${m.kind}`;
      this.box.style.cssText = this.v._rectStyle(p, [m.x - 1, m.y - 1, m.w + 2, m.h + 2]);
      p.marks.append(this.box);
      if (m.card) this.tip.replaceChildren(...this._card(m.card)); // a geometric tolerance: short lines, then two gauges
      else this.tip.textContent = m.tip;
      this.tip.classList.toggle('card', !!m.card);
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
