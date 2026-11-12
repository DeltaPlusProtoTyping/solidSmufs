// Ballooning a print, on the page view: the Balloon button (beside "TP on hover") reads the print's sizes,
// tolerances, threads, finishes, feature control frames and notes into a numbered inspection list, with a balloon
// beside each one on the page. The list is the panel on the right: check it against the print, fix what was read
// wrong, add what was missed, then write the inspection report. The document's worker does the reading and keeps
// the list and the balloons in the PDF itself (kernel/balloons.py, kernel/balloonops.py); this draws the balloons
// to drag and the list to edit. Every change goes through the PDF editor's run(), so it's undone with Ctrl+Z.
import { api } from './api.js';
import { h, toast, modal } from './ui.js';

const TOLS = [['0', 'X'], ['1', '.X'], ['2', '.XX'], ['3', '.XXX'], ['4', '.XXXX'], ['angle', 'Angles']];
const MEASURED = new Set(['dim', 'angle', 'chamfer']);
const typing = (el) => el && (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || el.isContentEditable);
const rectOf = (a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1])];
const decimals = (s) => ((String(s).split(/[.,]/)[1] || '').length);

export class Balloons {
  constructor(view) {
    this.v = view;
    this.doc = null;
    this.on = false;
    this.data = { chars: [], tols: {}, unit: null, labels: {}, info: {}, fields: [], layouts: [] };
    this.sel = null;
    this.els = new Map();
    this.adding = false;
    this.btn = h('button', { class: 'pv-btn pv-toggle', text: 'Balloon',
      title: 'Balloon this print: number every dimension, tolerance, thread, finish, geometric tolerance and note,\nlist them with their limits, and write the inspection report. The balloons are saved into the PDF.',
      onclick: () => this.toggle() });
    view.hints.tpBtn.after(this.btn);
    this.panel = h('div', { class: 'bl-panel', hidden: true });
    view.body.append(this.panel);
    this.target = h('div', { class: 'bl-target' });
    view.scroller.addEventListener('pointerdown', (e) => this._addDown(e), true);
    document.addEventListener('keydown', (e) => this._key(e), true);
  }

  get ed() { return this.v.editor; }

  // ================================================================== opening and closing
  open(doc) {
    this.doc = doc;
    this.sel = null;
    this.data = { chars: [], tols: {}, unit: null, labels: {}, info: {}, fields: [] };
    this.btn.hidden = !this.ed.editable; // balloons are kept in a PDF (a picture is printed to one first)
    this._show(!!doc.balloonsOn && this.ed.editable);
    if (this.on) this.load();
  }

  close() {
    this._adding(false);
    this.doc = null;
    this.on = false;
    this.panel.hidden = true;
    this.btn.classList.remove('on');
    this._clearEls();
  }

  _clearEls() {
    for (const el of this.els.values()) el.remove();
    this.els.clear();
    this.target.remove();
  }

  _show(on) {
    this.on = on;
    if (this.doc) this.doc.balloonsOn = on;
    this.btn.classList.toggle('on', on);
    const was = this.panel.hidden;
    this.panel.hidden = !on;
    if (was !== !on && this.v.doc && !this.v.el.hidden) this.v._resized();
    if (!on) { this._adding(false); this._clearEls(); }
  }

  async toggle() {
    if (!this.doc) return;
    this._show(!this.on);
    if (!this.on) return;
    this.render();
    await this.load();
    if (this.on && !this.data.chars.length) this.detect(true);
  }

  async load() {
    const doc = this.doc;
    try {
      await this.ed._ready;
      const data = await api.pdfEdit(doc.id, 'balloons');
      if (this.doc !== doc) return;
      this.data = data;
    } catch (e) { toast(e.message, 'error'); }
    this.render();
  }

  /** The PDF editor made a change (an edit here, or an undo): the list as it is now. */
  changed(r) {
    if (!this.on) return;
    if (r?.result?.chars) { this.data = r.result; this.render(); } else this.load();
  }

  run(op, args, busy) { return this.ed.run(op, args, busy); }

  char(id) { return this.data.chars.find((c) => c.id === id) || null; }

  // ================================================================== what the buttons do
  async detect(first = false) {
    const n = this.data.chars.length;
    if (n && !await this.ed._confirm('Detect again', `This reads the print again and replaces the ${n} balloon${n === 1 ? '' : 's'} on it, with any changes made to them.`, 'Detect again')) return;
    let notes = true;
    try { notes = localStorage.getItem('bl:notes') !== '0'; } catch { /* storage off */ }
    this._busy(true);
    const r = await this.run('balloon_auto', { notes }, 'Reading the print…');
    this._busy(false);
    if (!r) return;
    const found = r.result?.found || 0;
    if (!found) toast(first ? 'Nothing to balloon was found on this print. Use Add to balloon it by hand.' : 'Nothing to balloon was found.', 'info', 6000);
    else toast(`${found} characteristic${found === 1 ? '' : 's'} ballooned. Check them against the print.`, 'ok', 5000);
  }

  _busy(on) {
    this.panel.classList.toggle('busy', on);
  }

  _adding(on) {
    this.adding = on;
    this.v.scroller.classList.toggle('bl-adding', on);
    this.addBtn?.classList.toggle('on', on);
  }

  async clear() {
    const n = this.data.chars.length;
    if (!n || !await this.ed._confirm('Remove the balloons', `Take all ${n} balloon${n === 1 ? '' : 's'} and the inspection list off this print?`, 'Remove')) return;
    this.sel = null;
    this.run('balloon_clear');
  }

  // Report…: what the report says about the job (kept with the list in the PDF), then where to save the workbook
  report() {
    if (!this.data.chars.length) { toast('There are no balloons to report yet.', 'info'); return; }
    const was = this.data.info || {}, doc = this.doc;
    const row = (label, el) => h('label', { class: 'pe-frow' }, h('span', { text: label }), el);
    const inputs = (this.data.fields || []).map(([k, label]) => [k, label, h('input', { type: 'text', spellcheck: 'false', value: was[k] ?? '' })]);
    const parts = h('input', { type: 'number', min: 1, max: 50, step: 1, value: was.parts || 5,
      title: 'How many parts will be inspected: the report gets a results column for each one\n(the inspection sheet has them in fives)' });
    const kept = (k) => { try { return localStorage.getItem(k) || ''; } catch { return ''; } };
    const layout = h('select', {}, ...(this.data.layouts || []).map(([k, label]) => h('option', { value: k, text: label, selected: k === kept('bl:layout') })));
    const footer = h('textarea', { rows: 2, spellcheck: 'false', placeholder: 'Your form number, a policy note…',
      title: 'Lines for the bottom of the inspection sheet. Remembered on this computer for every report.' });
    footer.value = kept('bl:footer');
    let dlg = null;
    const ok = async () => {
      dlg.close();
      const info = { parts: Math.min(Math.max(parseInt(parts.value, 10) || 1, 1), 50) };
      for (const [k, , el] of inputs) if (el.value.trim()) info[k] = el.value.trim();
      try { localStorage.setItem('bl:layout', layout.value); localStorage.setItem('bl:footer', footer.value); } catch { /* storage off */ }
      const same = info.parts === was.parts && inputs.every(([k]) => (info[k] || '') === (was[k] || ''));
      if (!same && !await this.run('balloon_info', { info })) return;
      const name = `${info.part || doc.name.replace(/\.pdf$/i, '')} inspection report.xlsx`;
      const r = await api.saveXlsxDialog(name, 'Save Inspection Report As').catch((e) => { toast(e.message, 'error'); return null; });
      if (!r?.path || this.doc !== doc) return;
      try {
        const done = await api.pdfEdit(doc.id, 'balloon_report', { path: r.path, parts: info.parts, layout: layout.value, footer: footer.value });
        this.ed._saved(`Inspection report saved: ${done.count} characteristic${done.count === 1 ? '' : 's'}, room for ${done.parts} part${done.parts === 1 ? '' : 's'}. The sheet is beside it as a PDF.`, done.path);
      } catch (e) { toast(e.message, 'error'); }
    };
    dlg = modal('Inspection report', h('div', { class: 'pe-fprops bl-props' },
      ...inputs.map(([, label, el]) => row(label, el)),
      row('Parts to inspect', parts), row('Layout', layout), row('Footer', footer),
      h('p', { class: 'bl-hint', text: 'An Excel workbook: each balloon with its description, gage, nominal and limits, and a column for each part. A result typed in outside its limits turns red. The inspection sheet is saved as a PDF too, beside the workbook under the same name. The job details are kept with the balloons in the print.' }),
      h('div', { class: 'pe-pop-foot' },
        h('span', { class: 'pv-grow' }),
        h('button', { class: 'btn', text: 'Cancel', onclick: () => dlg.close() }),
        h('button', { class: 'btn primary', text: 'Save report…', onclick: ok }))), { width: 440 });
    footer.addEventListener('keydown', (e) => e.stopPropagation());
    for (const el of [parts, ...inputs.map((i) => i[2])]) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') ok(); e.stopPropagation(); });
    setTimeout(() => inputs[0]?.[2].focus(), 30);
  }

  remove(id) {
    if (this.sel === id) this.sel = null;
    this.run('balloon_delete', { ids: [id] });
  }

  select(id, { toPage = false, toRow = false } = {}) {
    this.sel = id;
    this.layout();
    for (const tr of this.panel.querySelectorAll('tr[data-id]')) {
      const on = +tr.dataset.id === id;
      tr.classList.toggle('on', on);
      if (on && toRow) tr.scrollIntoView({ block: 'nearest' });
    }
    if (toPage) this.els.get(id)?.scrollIntoView({ block: 'center', inline: 'center' });
  }

  // ================================================================== the keyboard
  _key(e) {
    if (!this.on || !this.doc || this.v.el.hidden || typing(e.target) || document.querySelector('.modal-back')) return;
    if (e.key === 'Escape' && (this.adding || this.sel !== null)) {
      if (this.adding) this._adding(false); else this.select(null);
      e.stopImmediatePropagation();
      return;
    }
    if ((e.key === 'Delete' || e.key === 'Backspace') && this.sel !== null && !this.ed.sel && !this.ed.fsel) {
      this.remove(this.sel);
      e.preventDefault();
      e.stopImmediatePropagation();
    }
  }

  // ================================================================== the balloons over the pages
  _fmt(v, places, kind) {
    if (v === null || v === undefined) return '';
    const want = kind === 'angle' ? places || 0 : Math.max(places || 0, this.data.unit === 'mm' ? 2 : 3);
    let s = v.toFixed(6);
    while (s.length - s.indexOf('.') - 1 > want && s.endsWith('0')) s = s.slice(0, -1);
    return s;
  }

  _limits(c) {
    const p = c.places || 0, f = (v) => this._fmt(v, p, c.kind).replace(/\.$/, '') + (c.kind === 'angle' ? '°' : '');
    if (c.lo !== null && c.hi !== null) return `${f(c.lo)} – ${f(c.hi)}`;
    if (c.hi !== null) return `${f(c.hi)} max`;
    if (c.lo !== null) return `${f(c.lo)} min`;
    return '';
  }

  _put(el, p, c, at) {
    el.style.cssText = this.v._rectStyle(p, [at[0] - c.r, at[1] - c.r, 2 * c.r, 2 * c.r]);
    const k = p.cssW / this.v._size(p)[0], n = String(c.label).length;
    el.style.fontSize = `${c.r * k * (n < 2 ? 1.25 : n === 2 ? 1.08 : n === 3 ? 0.8 : 0.64)}px`;
    el.style.borderWidth = `${Math.max(c.r * 0.13 * k, 1)}px`;
  }

  layout() {
    if (!this.on || !this.doc) return;
    const live = new Set();
    for (const c of this.data.chars) {
      const p = this.v.pages?.[c.page];
      if (!p) continue;
      live.add(c.id);
      let el = this.els.get(c.id);
      if (!el) {
        el = h('div', { class: 'bl' });
        el.addEventListener('pointerdown', (e) => this._down(e, el));
        el.addEventListener('dblclick', (e) => { e.stopPropagation(); this.edit(el.char); });
        this.els.set(c.id, el);
      }
      el.char = c;
      el.textContent = c.label;
      el.title = `${c.label}: ${c.text || '(no requirement yet)'}${this._limits(c) ? `\n${this._limits(c)}` : ''}\nDrag to move, double-click to change, Delete to remove`;
      el.classList.toggle('on', this.sel === c.id);
      if (el.parentNode !== p.edit) p.edit.append(el);
      this._put(el, p, c, c.at);
    }
    for (const [id, el] of this.els) if (!live.has(id)) { el.remove(); this.els.delete(id); }
    const s = this.sel === null ? null : this.char(this.sel), sp = s && this.v.pages?.[s.page];
    if (sp) {
      this.target.style.cssText = this.v._rectStyle(sp, [s.box[0] - 1.5, s.box[1] - 1.5, s.box[2] + 3, s.box[3] + 3]);
      if (this.target.parentNode !== sp.marks) sp.marks.append(this.target);
    } else this.target.remove();
  }

  // a balloon is pressed: it's selected, and a drag moves it
  _down(e, el) {
    if (e.button !== 0 || this.adding) return;
    e.preventDefault();
    e.stopPropagation();
    const c = el.char, p = this.v.pages[c.page], at0 = [...c.at];
    let at = at0;
    this.select(c.id, { toRow: true });
    this.ed._drag(e, p, this.v._pagePoint(p, e), (a, b) => {
      at = [at0[0] + b[0] - a[0], at0[1] + b[1] - a[1]];
      this._put(el, p, c, at);
    }, (a, b, moved) => { if (moved) this.run('balloon_move', { id: c.id, at }); });
  }

  // Add is on: a box dragged around a callout balloons what's in it; a click leaves an empty balloon to fill in
  _addDown(e) {
    if (!this.adding || e.button !== 0) return;
    const box = e.target.closest?.('.pv-pagebox');
    if (!box) return;
    e.preventDefault();
    e.stopPropagation();
    const p = this.v.pages[+box.dataset.page], ghost = h('div', { class: 'bl-ghost' });
    p.marks.append(ghost);
    this.ed._drag(e, p, this.v._pagePoint(p, e), (a, b) => { ghost.style.cssText = this.v._rectStyle(p, rectOf(a, b)); }, async (a, b, moved) => {
      ghost.remove();
      this._adding(false);
      const rect = moved ? rectOf(a, b) : [a[0], a[1], 0, 0];
      const r = await this.run('balloon_add', { page: p.i, rect }, 'Reading it…');
      const id = r?.result?.ids?.[0];
      if (id === undefined) return;
      this.select(id, { toRow: true });
      const c = this.char(id);
      if (c && !c.text) this.edit(c);
    });
  }

  // ================================================================== the list
  render() {
    if (!this.on) return;
    const d = this.data, n = d.chars.length;
    const btn = (text, tip, run, cls = '') => h('button', { class: `btn bl-btn ${cls}`, text, title: tip, onclick: run });
    this.addBtn = btn('Add', 'Balloon something by hand: drag a box around a callout on the print (its text is read),\nor click a spot for an empty balloon to fill in. Esc cancels.', () => this._adding(!this.adding), this.adding ? 'on' : '');
    let notes = true;
    try { notes = localStorage.getItem('bl:notes') !== '0'; } catch { /* storage off */ }
    const notesBox = h('input', { type: 'checkbox', checked: notes });
    notesBox.addEventListener('change', () => { try { localStorage.setItem('bl:notes', notesBox.checked ? '1' : '0'); } catch { /* storage off */ } });
    const tols = h('div', { class: 'bl-tols', title: 'The title block\'s tolerances by the number of decimals. A size with no tolerance of its own gets its limits\nfrom these. Read from the print: correct them here if they were read wrong.' },
      h('span', { class: 'bl-tl', text: 'Title block ±' }),
      ...TOLS.map(([k, label]) => {
        const inp = h('input', { type: 'text', spellcheck: 'false', value: d.tols[k] ?? '', placeholder: '–' });
        inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') inp.blur(); e.stopPropagation(); });
        inp.addEventListener('change', () => {
          const next = { ...d.tols };
          const v = parseFloat(inp.value.replace(',', '.'));
          if (v > 0) next[k] = v; else delete next[k];
          this.run('balloon_tols', { tols: next });
        });
        return h('label', {}, h('span', { text: label }), inp);
      }));
    const rows = d.chars.map((c) => {
      const tr = h('tr', { 'data-id': c.id, class: this.sel === c.id ? 'on' : '' },
        h('td', { class: 'bl-n' }, h('span', { text: c.label })),
        h('td', { class: 'bl-req' }, h('div', { class: 'bl-text', text: c.text || '(no requirement yet)' }),
          h('div', { class: 'bl-kind', text: `${d.labels[c.kind] || c.kind}${d.chars.some((x) => x.page !== d.chars[0].page) ? ` · sheet ${c.page + 1}` : ''}` })),
        h('td', { class: `bl-lim${c.tol === 'default' ? ' def' : ''}`, text: this._limits(c), title: c.tol === 'default' ? 'From the title block\'s tolerances' : c.tol === 'print' ? 'From the tolerance on the callout' : MEASURED.has(c.kind) ? 'No tolerance was found for this size' : '' }),
        h('td', { class: 'bl-x' }, h('button', { class: 'bl-del', text: '×', title: 'Remove this balloon', onclick: (e) => { e.stopPropagation(); this.remove(c.id); } })));
      tr.addEventListener('click', () => this.select(c.id, { toPage: true }));
      tr.addEventListener('dblclick', () => this.edit(c));
      return tr;
    });
    const open = MEASURED.size && d.chars.filter((c) => MEASURED.has(c.kind) && c.lo === null && c.hi === null).length;
    this.panel.replaceChildren(
      h('div', { class: 'bl-head' }, h('b', { text: 'Inspection list' }), h('span', { class: 'bl-count', text: n ? `${n} characteristic${n === 1 ? '' : 's'}` : '' }),
        h('span', { class: 'pv-grow' }), h('button', { class: 'bl-close', text: '×', title: 'Close the list (the balloons stay on the print)', onclick: () => this.toggle() })),
      h('div', { class: 'bl-tools' },
        btn(n ? 'Detect again' : 'Detect', 'Read the print and balloon what\'s found', () => this.detect()),
        this.addBtn,
        btn('Renumber', 'Number the balloons 1, 2, 3… in their order, closing the gaps deleted ones left', () => this.run('balloon_renumber')),
        btn('Report…', 'Write the inspection report as an Excel workbook: the sheet to print and fill in, five parts to a table,\nor the list with Pass / Fail worked out from the results, with AS9102 Form 3', () => this.report(), 'primary')),
      h('label', { class: 'bl-opt', title: 'Whether Detect balloons the numbered notes too' }, notesBox, 'Balloon the numbered notes'),
      tols,
      n ? h('div', { class: 'bl-list' }, h('table', {}, h('thead', {}, h('tr', {}, h('th', { text: '#' }), h('th', { text: 'Requirement' }), h('th', { text: 'Limits' }), h('th', {}))), h('tbody', {}, ...rows)))
        : h('div', { class: 'bl-empty', text: this.panel.classList.contains('busy') ? 'Reading the print…' : 'No balloons on this print yet. Detect reads it; Add balloons by hand.' }),
      n ? h('div', { class: 'bl-foot' },
        h('span', { text: open ? `${open} size${open === 1 ? ' has' : 's have'} no limits yet. ` : '' }),
        h('span', { text: 'Double-click a row or a balloon to change it. The balloons are saved with the PDF.' }),
        h('button', { class: 'bl-link', text: 'Remove all', onclick: () => this.clear() })) : null,
    );
    this.layout();
  }

  // ================================================================== one characteristic's dialog
  edit(c) {
    const d = this.data;
    const row = (label, el) => h('label', { class: 'pe-frow' }, h('span', { text: label }), el);
    const text = (v, ph = '') => h('input', { type: 'text', spellcheck: 'false', value: v ?? '', placeholder: ph });
    const num = (v) => text(v === null || v === undefined ? '' : this._fmt(v, c.places, c.kind).replace(/\.$/, ''));
    const n = text(c.label), req = text(c.text, 'As written on the print'), qty = text(c.count || 1);
    n.title = 'Its place in the list: 4 makes it the fourth. 4.2 puts it second under number 4, for one callout with several things to check.';
    const desc = text(c.desc, 'What it is: Overall Length, Cross Hole Diameter…'), gage = text(c.gage, 'Calipers, Height Gage, Gage Pin…');
    const kind = h('select', {}, ...Object.entries(d.labels).map(([k, label]) => h('option', { value: k, text: label, selected: k === c.kind })));
    const f = { nominal: num(c.nominal), plus: num(c.plus), minus: num(c.minus), lo: num(c.lo), hi: num(c.hi) };
    const was = Object.fromEntries(Object.entries(f).map(([k, el]) => [k, el.value]));
    let dlg = null;
    const ok = () => {
      dlg.close();
      const o = { id: c.id };
      if (kind.value !== c.kind) o.kind = kind.value;
      if (req.value.trim() !== (c.text || '')) o.text = req.value.trim();
      if ((parseInt(qty.value, 10) || 1) !== (c.count || 1)) o.count = parseInt(qty.value, 10) || 1;
      if (desc.value.trim() !== (c.desc || '')) o.desc = desc.value.trim();
      if (gage.value.trim() !== (c.gage || '')) o.gage = gage.value.trim();
      for (const [k, el] of Object.entries(f)) {
        if (el.value.trim() === was[k]) continue;
        const v = parseFloat(el.value.replace(',', '.'));
        o[k] = Number.isFinite(v) ? v : null;
        if (k === 'nominal' && Number.isFinite(v)) o.places = decimals(el.value.trim());
      }
      const to = n.value.trim().replace(',', '.');
      if (/^\d+(\.\d+)?$/.test(to) && to !== String(c.label)) o.n = to;
      if (Object.keys(o).length > 1) this.run('balloon_edit', o);
    };
    const sub = async () => {
      dlg.close();
      const r = await this.run('balloon_sub', { id: c.id });
      const made = this.char(r?.result?.ids?.[0]);
      if (made) { this.select(made.id, { toRow: true }); this.edit(made); }
    };
    dlg = modal(`Balloon ${c.label}`, h('div', { class: 'pe-fprops bl-props' },
      row('Number', n), row('Type', kind), row('Requirement', req), row('Description', desc), row('Gage', gage), row('Quantity', qty),
      h('div', { class: 'bl-nums' }, row('Nominal', f.nominal), row('+ Tolerance', f.plus), row('− Tolerance', f.minus), row('Lower limit', f.lo), row('Upper limit', f.hi)),
      h('p', { class: 'bl-hint', text: 'Limits follow the nominal and its tolerance. With no tolerance here, they come from the title block\'s. Type the limits themselves for a size given as limits.' }),
      h('div', { class: 'pe-pop-foot' },
        h('button', { class: 'btn', text: 'Delete balloon', onclick: () => { dlg.close(); this.remove(c.id); } }),
        h('button', { class: 'btn', text: 'Add sub-balloon', title: `Another thing to check on the same callout: a new balloon under this number (${c.n}.1, ${c.n}.2…).\nChanges typed here are not kept.`, onclick: sub }),
        h('span', { class: 'pv-grow' }),
        h('button', { class: 'btn', text: 'Cancel', onclick: () => dlg.close() }),
        h('button', { class: 'btn primary', text: 'OK', onclick: ok }))), { width: 440 });
    for (const el of [n, req, desc, gage, qty, ...Object.values(f)]) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') ok(); e.stopPropagation(); });
    setTimeout(() => { req.focus(); req.select(); }, 30);
  }
}
