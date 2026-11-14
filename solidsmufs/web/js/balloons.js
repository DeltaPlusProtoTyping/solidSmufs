// Ballooning mode, on the page view. The Balloon button (beside "TP on hover") turns the PDF view into a place to
// balloon a print, and back: while it's on, the PDF editor's toolbar gives way to this mode's own (Auto Balloon, Add,
// Sub-balloon, Renumber, Report…), every callout that has a balloon is marked on the print, and the Bill of
// Characteristics is docked under the pages: a row for each balloon with its zone, type, requirement, nominal,
// tolerances, limits, description, gage and note, typed into in place. Nothing else of the app changes, and leaving
// the mode puts the PDF view back as it was.
// The dock has a second tab, Results: a column for each part inspected, to type what it measured for every
// characteristic. A result is green inside its limits and red outside them, and each row says Pass or Fail. The parts
// and their results are kept with the list in the PDF, and go into the report.
// The third tab, Production Issues: what has to be dialed in before a part runs, or while it does, each about a balloon.
// A machinist marks one fixed, ready for a lead; a lead resolves it (a machinist's fix, or moved to troubleshooting) or
// reopens it. Hide puts one out of the way; Delete hides it and asks for it to be deleted for good.
// A list is a Draft until it's released: then its balloons and characteristics are fixed, while results, issues and the
// job's details are still filled in. Superseded by the next revision, nothing in it changes. Back to draft (with a
// change note) is how either is changed again.
// Roles, on this PC: with a lead password set, a lead's actions (release, back to draft, superseded, resolving or
// reopening an issue, deleting one for good) ask for it first, and stay unlocked for four hours from the last one.
// Views are boxes drawn round the drawing's views: their balloons are drawn in the view's color, and Renumber goes
// view by view (by rows, by columns, or clockwise round the view), each from its own start number if it has one.
// A characteristic that applies in several places (4X) can be multiplied: one balloon still, but a row for each place
// (3.1 to 3.4) here and in the report, all saying the same. Detached, the places become balloons of their own.
// The document's worker reads the print and keeps the list and the balloons in the PDF itself (kernel/balloons.py,
// kernel/balloonops.py); this draws the balloons to drag and the list to edit. Every change goes through the PDF
// editor's run(), so it's undone with Ctrl+Z.
import { api } from './api.js';
import { h, toast, modal, menu } from './ui.js';
import { photoStrip } from './balloonphotos.js';

const TOLS = [['0', 'X'], ['1', '.X'], ['2', '.XX'], ['3', '.XXX'], ['4', '.XXXX'], ['angle', 'Angles']];
const MEASURED = new Set(['dim', 'angle', 'chamfer']);
const typing = (el) => el && (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || el.isContentEditable);
const rectOf = (a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1])];
const decimals = (s) => ((String(s).split(/[.,]/)[1] || '').length);
const keep = (k, v) => { try { localStorage.setItem(k, v); } catch { /* storage off */ } };
const kept = (k, d = '') => { try { return localStorage.getItem(k) ?? d; } catch { return d; } };
const empty = () => ({ chars: [], tols: {}, unit: null, labels: {}, info: {}, fields: [], layouts: [], samples: [], results: {}, views: [], tags: [], log: [], sid: null, issues: [], issueTags: [], photos: [] });
const ISSUE_SHOW = [['open', 'Not resolved'], ['all', 'All'], ['resolved', 'Resolved'], ['hidden', 'Hidden'], ['delete', 'To be deleted']];
const issueStatus = (i) => (i.delete ? 'To be deleted' : i.status === 'fixed' ? 'Fixed, ready for lead'
  : i.status === 'resolved' ? (i.route === 'troubleshooting' ? 'Resolved: moved to troubleshooting' : 'Resolved: machinist fix') : 'Open');
const unresolved = (i) => !i.hidden && i.status !== 'resolved';
const STATUS_LABEL = { draft: 'Draft', released: 'Released', superseded: 'Superseded' };
const when = (iso) => { const d = new Date(iso); return Number.isNaN(+d) ? String(iso || '') : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }); };
const ORDERS = [['list', 'In list order', 'Close the gaps, keeping the order they are in'], ['rows', 'By rows', 'Across the sheet a row at a time, top to bottom'],
  ['columns', 'By columns', 'Down the sheet a column at a time, left to right'], ['clockwise', 'Clockwise', "Round from twelve o'clock about the middle of each view"]];
// does a result meet its characteristic? true, false, or null when that can't be said (nothing there, words, no limits)
// how a row's measurements spread, from two or more: n, mean, min, max, range, sd, cp, cpk (null with fewer)
const stats = (c, values) => {
  const xs = values.map((v) => (v === '' || v == null ? NaN : Number(v))).filter(Number.isFinite);
  if (xs.length < 2) return null;
  const n = xs.length, mean = xs.reduce((s, x) => s + x, 0) / n, sd = Math.sqrt(xs.reduce((s, x) => s + (x - mean) ** 2, 0) / (n - 1));
  const min = Math.min(...xs), max = Math.max(...xs), spread = sd > 1e-12;
  const sides = [c.hi != null ? c.hi - mean : null, c.lo != null ? mean - c.lo : null].filter((x) => x !== null);
  return { n, mean, min, max, range: max - min, sd, cp: spread && c.lo != null && c.hi != null ? (c.hi - c.lo) / (6 * sd) : null, cpk: spread && sides.length ? Math.min(...sides) / (3 * sd) : null };
};
const judge = (c, v) => {
  if (v === 'Pass' || v === 'Fail') return v === 'Pass';
  const x = v === '' || v == null ? NaN : Number(v);
  if (!Number.isFinite(x) || (c.lo == null && c.hi == null)) return null;
  return (c.lo == null || x >= c.lo - 1e-9) && (c.hi == null || x <= c.hi + 1e-9);
};
const bare = (c) => c.tol === 'ref' || c.tol === 'basic'; // a reference or basic size: it has no limits, and isn't meant to
const open = (c) => MEASURED.has(c.kind) && c.lo == null && c.hi == null && !bare(c); // a size with nothing to measure it against yet
const multiplied = (c) => !!c.mult && c.count > 1; // inspected in each of its places: a row for each
const TOL_TYPES = [['', 'Toleranced'], ['ref', 'Reference'], ['basic', 'Basic']];
// "1, 3-5" as page numbers counted from 0
const pagesOf = (text, count) => {
  const out = new Set();
  for (const part of String(text).split(/[,;]+/)) {
    const m = /^(\d+)(?:\s*[-–]\s*(\d+))?$/.exec(part.trim());
    if (!m) continue;
    for (let i = +m[1]; i <= +(m[2] || m[1]) && i <= count; i++) if (i >= 1) out.add(i - 1);
  }
  return [...out].sort((a, b) => a - b);
};

// the Bill of Characteristics' columns: k what of the characteristic it shows, w its width, edit how a double-click
// changes it in place (none: it's worked out, not typed)
const COLS = [
  { k: 'reviewed', head: 'Reviewed', w: 86, tip: 'Tick a characteristic once it has been checked against the print.\nThe box up here ticks every one shown.' },
  { k: 'n', head: 'Dim #', w: 58, edit: 'text', tip: "The balloon's number. 4 makes it the fourth; 4.2 puts it second under number 4,\nfor one callout with several things to check." },
  { k: 'where', head: 'Dwg. Zone', w: 78, tip: "The sheet, and the zone of the drawing's border the callout is in" },
  { k: 'kind', head: 'Type', w: 112, edit: 'select' },
  { k: 'text', head: 'Requirement', w: 210, edit: 'text', mono: true, tip: 'As written on the print' },
  { k: 'count', head: 'Mult', w: 50, edit: 'text', tip: 'How many places it applies to (4X)' },
  { k: 'nominal', head: 'Nominal', w: 78, edit: 'num' },
  { k: 'plus', head: 'Upper Tol', w: 78, edit: 'num' },
  { k: 'minus', head: 'Lower Tol', w: 78, edit: 'num' },
  { k: 'lo', head: 'Lower Limit', w: 86, edit: 'num', tip: 'Follows the nominal and its tolerance. Type it for a size given as limits.' },
  { k: 'hi', head: 'Upper Limit', w: 86, edit: 'num', tip: 'Follows the nominal and its tolerance. Type it for a size given as limits.' },
  { k: 'tol', head: 'Tol Type', w: 86, edit: 'select', tip: "General: the size has no tolerance of its own, so it takes the title block's.\nReference and Basic sizes have no limits." },
  { k: 'desc', head: 'Description', w: 180, edit: 'text', tip: 'What it is, in words: Overall Length, Cross Hole Diameter…' },
  { k: 'gage', head: 'Gage', w: 140, edit: 'text', tip: "What it's checked with: Calipers, Height Gage, Gage Pin…" },
  { k: 'tags', head: 'Tags', w: 160, edit: 'tags', tip: 'How it is inspected: Visual, Measured, Spot check, 100% check, Custom gage…\nAs many as apply, or none. Not printed.' },
  { k: 'note', head: 'Note', w: 220, edit: 'text' },
];
const FILTERS = [['all', 'All'], ['todo', 'Not reviewed'], ['done', 'Reviewed'], ['open', 'No limits yet']];

export class Balloons {
  constructor(view) {
    this.v = view;
    this.doc = null;
    this.on = false;
    this.data = empty();
    this.sel = null;
    this.els = new Map(); // the balloons over the pages
    this.vels = new Map(); // the views' boxes
    this.reqs = new Map(); // the marks over their callouts
    this.adding = false;
    this.busy = false;
    this.filter = 'all';
    this.tab = 'chars'; // which of the dock's lists is showing: 'chars', 'results' or 'issues'
    this.ishow = 'open'; // which issues the Issues tab shows
    this.col = 'text'; // the column last clicked: where Enter starts typing
    this.btn = h('button', { class: 'pv-btn pv-toggle', text: 'Balloon',
      title: 'Ballooning mode: number every dimension, tolerance, thread, finish, geometric tolerance and note on this print,\nlist them with their limits, and write the inspection report. The balloons are saved into the PDF.\nClick again to go back to the PDF view.',
      onclick: () => this.toggle() });
    view.hints.tpBtn.after(this.btn);
    // the mode's own toolbar, where the PDF editor's is
    this.row = h('div', { class: 'bl-row', hidden: true });
    view.el.insertBefore(this.row, view.body);
    // the Bill of Characteristics, docked under the pages
    this.grip = h('div', { class: 'bl-grip', title: 'Drag to make the list taller or shorter' });
    this.head = h('div', { class: 'bl-dhead' });
    this.wrap = h('div', { class: 'bl-gridwrap', tabindex: '0' });
    this.dock = h('div', { class: 'bl-dock', hidden: true }, this.grip, this.head, this.wrap);
    this.dock.style.height = `${Math.min(Math.max(parseInt(kept('bl:dock', '250'), 10) || 250, 110), 900)}px`;
    view.el.append(this.dock);
    this.grip.addEventListener('pointerdown', (e) => this._gripDown(e));
    view.scroller.addEventListener('pointerdown', (e) => this._addDown(e), true);
    document.addEventListener('keydown', (e) => this._key(e), true);
    // Undo, Redo and Save are the PDF editor's: this toolbar's follow its own
    const bar = this.ed._bar.bind(this.ed);
    this.ed._bar = () => { bar(); if (this.on) this._row(); };
  }

  get ed() { return this.v.editor; }

  // the characteristics are fixed: the list is released or superseded
  get fixed() { return (this.data.status || 'draft') !== 'draft'; }

  _fixedSay() {
    toast(this.data.status === 'superseded' ? 'This revision is superseded: nothing in it changes. Back to draft (the status beside the sheet id) to change it.'
      : 'This list is released: its balloons and characteristics are fixed. Back to draft (the status beside the sheet id) to change them.', 'info');
  }

  _statusMenu(anchor) {
    const s = this.data.status || 'draft';
    menu(anchor, [
      { head: `Status: ${STATUS_LABEL[s]}` },
      s === 'draft' ? { label: 'Release', action: () => this.release() } : null,
      s === 'released' ? { label: 'Mark superseded (by the next revision)', action: () => this._lead(() => this.run('balloon_status', { status: 'superseded' })) } : null,
      s !== 'draft' ? { label: 'Back to draft…', action: async () => {
        if (!await this._asLead()) return;
        const note = await this._ask('Back to draft', 'Why', 'Back to draft', s === 'superseded' ? 'It becomes a draft to change. The change note is kept with who and when.' : 'Its balloons and characteristics can be changed again. The change note is kept with who and when.');
        if (note) this._lead(() => this.run('balloon_status', { status: 'draft', note }));
      } } : null,
    ]);
  }

  // ------------------------------------------------------------------ roles: a lead's actions, behind the lead password
  _roleText() {
    const r = this.roles;
    if (!r?.on) return 'Roles off ▾';
    return r.level ? `🔓 ${r.level === 'admin' ? 'Admin' : 'Lead'} ▾` : '🔒 Operator ▾';
  }

  _roleTip() {
    const r = this.roles;
    if (!r?.on) return 'No lead password is set on this PC, so everyone may release, resolve and delete.\nSet one to keep those for leads.';
    if (r.level) return `Unlocked as ${r.level} until ${new Date(r.until).toLocaleTimeString(undefined, { timeStyle: 'short' })}: each lead action starts the four hours again.`;
    return "Releasing, back to draft, resolving or reopening an issue and deleting one for good are a lead's:\nthey ask for the lead password, then stay unlocked for four hours.";
  }

  async _rolesRefresh() {
    try { this.roles = await api.pdfEdit(this.doc.id, 'balloon_roles', {}); } catch { /* (kept as it was) */ }
    this._row();
  }

  // a lead's action: unlocked first if it has to be (false: it wasn't)
  async _asLead() {
    if (!this.roles?.on || this.roles.level) return true;
    const pw = await this._ask('Lead password', 'Password', 'Unlock', "That's a lead's to do. The lead (or admin) password unlocks it, and every lead action for the next four hours.", 'password');
    if (!pw) return false;
    try { this.roles = await api.pdfEdit(this.doc.id, 'balloon_roles', { action: 'unlock', password: pw }); } catch (e) { toast(e.message, 'error'); return false; }
    this._row();
    return true;
  }

  async _lead(fn) {
    if (!await this._asLead()) return null;
    const r = await fn();
    this._rolesRefresh(); // (the four hours start again)
    return r;
  }

  _rolesMenu(anchor) {
    const r = this.roles || {};
    const roleAct = async (o) => {
      try { this.roles = await api.pdfEdit(this.doc.id, 'balloon_roles', o); } catch (e) { toast(e.message, 'error'); return false; }
      this._row();
      return true;
    };
    menu(anchor, [
      { head: r.on ? (r.level ? `Unlocked as ${r.level}` : 'Operator: lead actions locked') : 'No roles on this PC' },
      r.on && !r.level ? { label: 'Unlock…', action: () => this._asLead() } : null,
      r.level ? { label: 'Lock now', action: () => roleAct({ action: 'lock' }) } : null,
      { sep: true },
      { label: r.lead ? 'Change the lead password…' : 'Set a lead password…', action: () => this._setPassword('lead') },
      { label: r.admin ? 'Change the admin password…' : 'Set an admin password…', action: () => this._setPassword('admin') },
    ]);
  }

  _setPassword(role) {
    const r = this.roles || {};
    const has = !!r[role], free = r.level === 'admin';
    const field = (label) => { const inp = h('input', { type: 'password', autocomplete: 'new-password' }); return [inp, h('label', { class: 'pe-frow' }, h('span', { text: label }), inp)]; };
    const [cur, curRow] = field(`The ${role} password now`);
    const [pw, pwRow] = field('New password');
    const [again, againRow] = field('Again');
    let dlg = null;
    const save = async () => {
      if (pw.value !== again.value) { toast("The two new passwords don't match.", 'info'); return; }
      if (!pw.value && !has) { toast('Type the new password.', 'info'); return; }
      try { this.roles = await api.pdfEdit(this.doc.id, 'balloon_roles', { action: 'set', role, new: pw.value, current: cur.value }); } catch (e) { toast(e.message, 'error'); return; }
      dlg.close();
      this._row();
      toast(pw.value ? `The ${role} password is set.` : `The ${role} password is taken away.`);
    };
    for (const el of [cur, pw, again]) el.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') save(); });
    dlg = modal(`${has ? 'Change' : 'Set'} the ${role} password`, h('div', { class: 'pe-fprops bl-props' },
      h('p', { class: 'bl-hint', text: role === 'lead'
        ? 'With a lead password, releasing, back to draft, resolving or reopening an issue and deleting one for good ask for it, then stay unlocked for four hours. Kept on this PC, for everyone who uses it.'
        : 'The admin password does what the lead password does, and changes either password. Kept on this PC.' }),
      has && !free ? curRow : '', pwRow, againRow,
      has ? h('p', { class: 'bl-hint', text: 'Leave the new password empty to take it away.' }) : '',
      h('div', { class: 'pe-pop-foot' }, h('span', { class: 'pv-grow' }),
        h('button', { class: 'btn', text: 'Cancel', onclick: () => dlg.close() }),
        h('button', { class: 'btn primary', text: 'Save', onclick: save }))), { width: 520 });
    setTimeout(() => (has && !free ? cur : pw).focus(), 30);
  }

  async release() {
    if (!await this._asLead()) return;
    const d = this.data, todo = d.chars.filter((c) => !c.reviewed).length, bare = d.chars.filter(open).length;
    const warn = [todo ? `${todo} of ${d.chars.length} characteristics aren't reviewed.` : '', bare ? `${bare} have no limits yet.` : ''].filter(Boolean).join(' ');
    const ok = await new Promise((done) => {
      let dlg = null, answered = false;
      const answer = (v) => { if (answered) return; answered = true; dlg.close(); done(v); };
      dlg = modal('Release', h('div', { class: 'pe-fprops bl-props' },
        h('p', { text: 'Released, the balloons and characteristics are fixed: the parts\' results, production issues and job details are still filled in. Back to draft changes them again, with a change note.' }),
        warn ? h('p', { class: 'bl-warn', text: warn }) : '',
        h('div', { class: 'pe-pop-foot' }, h('span', { class: 'pv-grow' }),
          h('button', { class: 'btn', text: 'Cancel', onclick: () => answer(false) }),
          h('button', { class: 'btn primary', text: warn ? 'Release anyway' : 'Release', onclick: () => answer(true) }))), { width: 540 });
      const close = dlg.close.bind(dlg);
      dlg.close = () => { close(); if (!answered) { answered = true; done(false); } };
    });
    if (ok) this._lead(() => this.run('balloon_status', { status: 'released' }));
  }

  // ================================================================== into the mode and out of it
  open(doc) {
    this.doc = doc;
    this.sel = null;
    this.data = empty();
    this.filter = 'all';
    this.btn.hidden = !this.ed.editable; // balloons are kept in a PDF (a picture is printed to one first)
    this._show(!!doc.balloonsOn && this.ed.editable);
    if (this.on) { this.render(); this.load(); }
  }

  close() {
    this._adding(false);
    this.doc = null;
    this.on = false;
    this.btn.classList.remove('on');
    this.v.el.classList.remove('ballooning');
    this.row.hidden = true;
    this.dock.hidden = true;
    this._clearEls();
  }

  _clearEls() {
    for (const el of this.els.values()) el.remove();
    for (const el of this.reqs.values()) el.remove();
    for (const el of this.vels.values()) el.remove();
    this.els.clear();
    this.reqs.clear();
    this.vels.clear();
  }

  _show(on) {
    const was = this.on;
    this.on = on;
    if (this.doc) this.doc.balloonsOn = on;
    this.btn.classList.toggle('on', on);
    this.v.el.classList.toggle('ballooning', on); // (hides the editor's toolbar and its comments list: see the style sheet)
    this.row.hidden = !on;
    this.dock.hidden = !on;
    if (on && this.doc) { // whatever the editor had in hand is put down
      if (this.ed.tool !== 'select') this.ed.setTool('select');
      if (this.ed.sel) this.ed.select(null);
    }
    if (!on) { this._adding(false); this._clearEls(); }
    if (was !== on && this.v.doc && !this.v.el.hidden) this.v._resized();
  }

  async toggle() {
    if (!this.doc) return;
    this._show(!this.on);
    if (!this.on) return;
    this.render();
    await this.load();
    if (this.on && !this.data.chars.length) this.auto(); // a print with no balloons yet: what to balloon on it
  }

  async load() {
    const doc = this.doc;
    try {
      await this.ed._ready;
      const [data, roles] = await Promise.all([api.pdfEdit(doc.id, 'balloons'), api.pdfEdit(doc.id, 'balloon_roles', {}).catch(() => null)]);
      if (this.doc !== doc) return;
      this.data = data;
      this.roles = roles;
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
  // what Auto Balloon reads and balloons, as it was last set on this computer
  _prefs() {
    let p = {};
    try { p = JSON.parse(kept('bl:auto', '{}')) || {}; } catch { p = {}; }
    return { scope: 'all', pick: '', noBasic: false, noRef: false, noGeneral: false, finish: true, flags: true, notes: kept('bl:notes', '1') !== '0', title: true, split: false, ...p };
  }

  // Auto Balloon: which pages to read and what to balloon on them, then the reading
  auto() {
    if (document.querySelector('.bl-auto')) return;
    const p = this._prefs(), n = this.data.chars.length, count = this.v.pages.length, cur = Math.min(this.v.current || 0, count - 1), doc = this.doc;
    const tick = (key, label, tip) => {
      const box = h('input', { type: 'checkbox' });
      box.checked = !!p[key];
      return [key, box, h('label', { class: 'bl-tick', title: tip }, box, label)];
    };
    const left = [
      tick('noBasic', 'Do not balloon Basic dimensions', 'A basic size (marked BSC, or drawn in a box of its own) locates a tolerance zone and has no limits.\nBallooned, it shows as Basic in the list.'),
      tick('noRef', 'Do not balloon Reference dimensions', 'A reference size (in brackets, or marked REF or STOCK) is for information and has no limits.\nBallooned, it shows as Reference in the list.'),
      tick('noGeneral', 'Do not balloon General Tolerance dimensions', "Sizes with no tolerance of their own, which take the title block's"),
    ];
    const right = [
      tick('finish', 'Surface finish detection', 'Balloon surface finishes: 63 RMS, Ra 1.6'),
      tick('flags', 'Flag note detection', "Balloon a note's number drawn in a triangle or flag by a feature, with the note's words"),
      tick('notes', 'Numbered notes', 'Balloon the numbered notes: 1. BREAK ALL SHARP EDGES…'),
      tick('title', 'Ignore title block', "Leave out what's written in the title block"),
      tick('split', 'Split sub-characteristics', "One callout's several characteristics share a number: a hole's diameter and its depth are 2.1 and 2.2,\na size and the feature control frame under it likewise"),
    ];
    const scope = (value, label) => {
      const r = h('input', { type: 'radio', name: 'bl-scope', value });
      r.checked = (count > 1 ? p.scope : 'all') === value;
      return [r, h('label', { class: 'bl-tick' }, r, label)];
    };
    const scopes = [scope('page', `Current page (${cur + 1})`), scope('all', 'All pages'), scope('pick', 'Select pages')];
    const pick = h('input', { class: 'bl-pick', type: 'text', spellcheck: 'false', placeholder: '1, 3-5', value: p.pick || '' });
    pick.addEventListener('focus', () => { scopes[2][0].checked = true; });
    let dlg = null;
    const ok = async () => {
      const next = { scope: scopes.find(([r]) => r.checked)?.[0].value || 'all', pick: pick.value.trim() };
      for (const [key, box] of [...left, ...right]) next[key] = box.checked;
      let pages = null;
      if (count > 1 && next.scope === 'page') pages = [cur];
      else if (count > 1 && next.scope === 'pick') {
        pages = pagesOf(next.pick, count);
        if (!pages.length) { toast(`Say which pages to read, like 1, 3-5. This print has ${count}.`, 'error'); pick.focus(); return; }
      }
      dlg.close();
      keep('bl:auto', JSON.stringify(next));
      keep('bl:notes', next.notes ? '1' : '0');
      if (this.doc !== doc || !this.on) return;
      this._busy(true);
      const r = await this.run('balloon_auto', { notes: next.notes, pages, split: next.split,
        want: { basic: !next.noBasic, ref: !next.noRef, general: !next.noGeneral, finish: next.finish, flags: next.flags, title: next.title } }, 'Reading the print…');
      this._busy(false);
      if (!r) return;
      const found = r.result?.found || 0;
      if (!found) toast(n ? 'Nothing to balloon was found.' : 'Nothing to balloon was found on this print. Use Add to balloon it by hand.', 'info', 6000);
      else toast(`${found} characteristic${found === 1 ? '' : 's'} ballooned. Check them against the print.`, 'ok', 5000);
    };
    dlg = modal('Auto Balloon', h('div', { class: 'bl-auto' },
      count > 1 ? h('div', { class: 'bl-scope' }, ...scopes.map((s) => s[1]), pick) : null,
      h('div', { class: 'bl-ticks' }, h('div', {}, ...left.map((t) => t[2])), h('div', {}, ...right.map((t) => t[2]))),
      n ? h('p', { class: 'bl-hint bl-warn', text: `This reads the print again. The balloons on the pages it reads are replaced, with any changes made to them (${n} on the print now).${Object.keys(this.data.results || {}).length ? ' What the parts measured against those balloons goes with them.' : ''}` })
        : h('p', { class: 'bl-hint', text: 'Reads the print and balloons what there is to inspect on it. These choices are remembered.' }),
      h('div', { class: 'pe-pop-foot' },
        h('span', { class: 'pv-grow' }),
        h('button', { class: 'btn', text: 'Cancel', onclick: () => dlg.close() }),
        h('button', { class: 'btn primary', text: 'OK', onclick: ok }))), { width: 560 });
    pick.addEventListener('keydown', (e) => { if (e.key === 'Enter') ok(); e.stopPropagation(); });
  }

  _busy(on) {
    this.busy = on;
    this.dock.classList.toggle('busy', on);
    if (!this.data.chars.length) this._grid();
  }

  _adding(on) {
    this.adding = on === true ? 'balloon' : on || false; // what a box dragged now makes: 'balloon' or 'view'
    this.v.scroller.classList.toggle('bl-adding', !!this.adding);
    this.addBtn?.classList.toggle('on', this.adding === 'balloon');
    this.viewBtn?.classList.toggle('on', this.adding === 'view');
    if (this.adding === 'view') toast('Drag a box round the view. Esc cancels.', 'info', 3500);
  }

  _autoMenu(anchor) {
    const n = this.data.chars.length;
    menu(anchor, [
      { label: n ? 'Auto Balloon again…' : 'Auto Balloon…', action: () => this.auto() },
      { label: 'Carry over from the last revision…', action: () => this.carry() },
      { sep: true },
      { label: 'Remove all balloons…', disabled: !n, action: () => this.clear() },
    ]);
  }

  _multMenu(anchor) {
    const chars = this.data.chars, sel = this.sel === null ? null : this.char(this.sel);
    const can = (c) => c.count > 1 && !c.mult, any = chars.some(can), some = chars.some(multiplied);
    menu(anchor, [
      { label: sel && can(sel) ? `Multiply ${sel.label} (${sel.count} rows)` : 'Multiply', disabled: !(sel && can(sel)), action: () => this.multiply([sel.id], true) },
      { label: 'Multiply All', disabled: !any, action: () => this.multiply(null, true) },
      { sep: true },
      { label: sel && multiplied(sel) ? `Detach ${sel.label} (${sel.count} balloons)` : 'Detach', disabled: !(sel && multiplied(sel)), action: () => this.detach([sel.id]) },
      { label: 'Detach All Multiplied', disabled: !some, action: () => this.detach(null) },
      { sep: true },
      { label: sel && multiplied(sel) ? `Reset ${sel.label}` : 'Reset', disabled: !(sel && multiplied(sel)), action: () => this.multiply([sel.id], false) },
      { label: 'Reset All Multiplied', disabled: !some, action: () => this.multiply(null, false) },
    ]);
  }

  /** A row for each place a characteristic applies in (on), or back to its one row. ids: which ones (null: all). */
  async multiply(ids, on) {
    const r = await this.run('balloon_multiply', { ids, on });
    const did = r?.result?.did;
    if (did === undefined) return;
    if (!did) toast(on ? 'Nothing here applies in more than one place: Multiply is for a 4X, with a count under Mult.' : 'Nothing is multiplied.', 'info', 5000);
    else if (on) toast(`${did} characteristic${did === 1 ? '' : 's'} multiplied: ${r.result.rows} rows to inspect.`, 'ok', 4000);
    else toast(`${did} characteristic${did === 1 ? '' : 's'} back to one row.`, 'ok', 3000);
  }

  /** A multiplied characteristic's places become balloons of their own, to put by their own features. */
  async detach(ids) {
    const r = await this.run('balloon_detach', { ids }, 'Placing the balloons…');
    const made = r?.result?.made;
    if (made === undefined) return;
    if (!made) toast('Nothing is multiplied: Multiply first.', 'info', 4000);
    else toast(`${made} balloon${made === 1 ? '' : 's'} added around ${ids && ids.length === 1 ? 'the callout' : 'their callouts'}. Drag each to its own feature.`, 'ok', 5000);
  }

  // a new revision of the print: balloon it from the last revision's ballooned PDF, numbers and details carried over
  async carry() {
    const doc = this.doc, n = this.data.chars.length;
    const pick = await api.openFiles('pdfonly', "Choose the last revision's ballooned PDF").catch((e) => { toast(e.message, 'error'); return null; });
    const path = pick?.files?.[0]?.path;
    if (!path || this.doc !== doc) return;
    if (n && !await this.ed._confirm('Carry over', `This reads this print again and replaces its ${n} balloon${n === 1 ? '' : 's'} with the last revision's, matched to what is on this one.`, 'Carry over')) return;
    const p = this._prefs();
    this._busy(true);
    const r = await this.run('balloon_carry', { path, notes: p.notes, split: p.split,
      want: { basic: !p.noBasic, ref: !p.noRef, general: !p.noGeneral, finish: p.finish, flags: p.flags, title: p.title } }, 'Reading the print…');
    this._busy(false);
    const got = r?.result?.carried;
    if (!r) return;
    if (!got) { toast('Nothing to balloon was found on this print.', 'info'); return; }
    const list = (title, rows, line) => (rows.length ? [h('h4', { class: 'bl-ch', text: `${title} (${rows.length})` }),
      h('ul', { class: 'bl-cl' }, ...rows.slice(0, 40).map((x) => h('li', {}, h('span', { class: 'bl-num', text: x.n }), line(x))))] : []);
    let dlg = null;
    dlg = modal('Carried over from the last revision', h('div', { class: 'bl-carry' },
      h('p', { class: 'bl-hint', text: `From ${got.from}: ${got.kept} the same, ${got.changed.length} changed, ${got.added.length} new, ${got.removed.length} gone. Changed and new ones are left unreviewed, and their notes say so. The numbers of those that are gone are left out: Renumber closes the gaps.` }),
      ...list('Changed', got.changed, (x) => h('span', {}, h('s', { text: x.was }), ' → ', h('b', { text: x.now }))),
      ...list('New on this revision', got.added, (x) => h('b', { text: x.now })),
      ...list('Gone from this revision', got.removed, (x) => h('s', { text: x.was })),
      h('div', { class: 'pe-pop-foot' }, h('span', { class: 'pv-grow' }), h('button', { class: 'btn primary', text: 'OK', onclick: () => dlg.close() }))), { width: 560 });
    this.filter = got.changed.length || got.added.length ? 'todo' : this.filter; // (what's to look at)
    this._head();
    this._grid();
  }

  async clear() {
    const n = this.data.chars.length;
    if (!n || !await this.ed._confirm('Remove the balloons', `Take all ${n} balloon${n === 1 ? '' : 's'} and the list of characteristics off this print?`, 'Remove')) return;
    this.sel = null;
    this.run('balloon_clear');
  }

  // the job's details as boxes to type in: [key, label, input], with a mark on those changed before that shows how
  _infoInputs(was, showLog) {
    const mine = { org: 'bl:org', supplier: 'bl:supplier' }; // (who we are: the same on every job, so kept on this computer)
    const log = this.data.log || [];
    return (this.data.fields || []).map(([k, label]) => {
      const el = h('input', { type: 'text', spellcheck: 'false', value: was[k] ?? (mine[k] ? kept(mine[k]) : '') });
      const n = log.filter((x) => x.field === k).length;
      const mark = n ? h('button', { class: 'bl-edmark', type: 'button', text: '✎', title: `Changed ${n} time${n === 1 ? '' : 's'}: click to see when, by whom and why`, onclick: (e) => { e.preventDefault(); showLog(k); } }) : null;
      return [k, label, el, mark];
    });
  }

  // the job's details as typed, saved: a detail changed once it was filled in asks for a change note first
  // (prefilled with what it was and is, when and who), and isn't saved without one. false: not saved.
  async _saveInfo(info) {
    const was = this.data.info || {}, label = Object.fromEntries(this.data.fields || []);
    const changed = (this.data.fields || []).filter(([k]) => (was[k] ?? '') !== '' && String(was[k]) !== String(info[k] ?? ''));
    const same = info.parts === was.parts && (this.data.fields || []).every(([k]) => (info[k] || '') === (was[k] || ''));
    if (same) return true;
    let note = null;
    if (changed.length) {
      const stamp = `${new Date().toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}${this.data.who ? `, ${this.data.who}` : ''}`;
      const lines = changed.map(([k]) => `${label[k]}: ${was[k]} → ${info[k] || '(empty)'}`).join('\n');
      note = await new Promise((done) => {
        const ta = h('textarea', { rows: 3, spellcheck: 'true', placeholder: 'Why it changed' });
        let dlg = null, answered = false;
        const answer = (v) => { if (answered) return; answered = true; dlg.close(); done(v); };
        const save = () => {
          const v = ta.value.trim();
          if (!v) { toast('Say why it changed: the change note is needed.', 'info'); return; }
          answer(v);
        };
        ta.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter' && e.ctrlKey) save(); });
        dlg = modal('Change note', h('div', { class: 'pe-fprops bl-props' },
          h('div', { class: 'bl-logh', style: { whiteSpace: 'pre-wrap' }, text: lines }),
          h('div', { class: 'bl-logw', text: stamp }),
          h('p', { class: 'bl-hint', text: 'Say why it changed. The note is kept with the change, who made it and when (Job… shows them).' }),
          ta,
          h('div', { class: 'pe-pop-foot' },
            h('span', { class: 'pv-grow' }),
            h('button', { class: 'btn', text: 'Cancel', onclick: () => answer(null) }),
            h('button', { class: 'btn primary', text: 'Save change', onclick: save }))), { width: 560 });
        const close = dlg.close.bind(dlg);
        dlg.close = () => { close(); if (!answered) { answered = true; done(null); } };
        setTimeout(() => ta.focus(), 30);
      });
      if (note === null) return false;
    }
    return !!await this.run('balloon_info', { info, note });
  }

  // Search…: characteristics and issues, on this print or every ballooned print saved on this computer
  search() {
    const q = h('input', { type: 'search', spellcheck: 'false', placeholder: 'Balloon number, .375, cross hole, pin gage, burr, a job number…', value: this._lastSearch || '' });
    const scope = h('select', {}, h('option', { value: 'here', text: 'This print' }), h('option', { value: 'all', text: 'All jobs on this computer', selected: kept('bl:searchAll') === '1' }));
    const out = h('div', { class: 'bl-found' });
    let dlg = null, seq = 0;
    const go = async () => {
      const text = q.value.trim(), mine = ++seq;
      this._lastSearch = text;
      keep('bl:searchAll', scope.value === 'all' ? '1' : '0');
      if (!text) { out.replaceChildren(h('p', { class: 'bl-hint', text: 'Every word typed is looked for, in any order. All jobs searches every ballooned print saved on this computer.' })); return; }
      let hits = [];
      try { hits = await api.pdfEdit(this.doc.id, 'balloon_search', { query: text, here: scope.value === 'here' }); } catch (e) { toast(e.message, 'error'); return; }
      if (mine !== seq) return;
      if (!hits.length) { out.replaceChildren(h('p', { class: 'bl-hint', text: 'Nothing found.' })); return; }
      out.replaceChildren(...hits.map((x) => {
        const where = x.here ? 'This print' : `${x.part || x.path.split(/[\\/]/).pop()}${x.rev ? ` rev ${x.rev}` : ''}${x.job ? ` · job ${x.job}` : ''}${x.missing ? ' · file moved or gone' : ''}`;
        const row = h('button', { class: `bl-hit${x.missing ? ' gone' : ''}`, type: 'button', title: x.path || '' },
          h('span', { class: `bl-hk ${x.kind}`, text: x.kind === 'issue' ? 'Issue' : 'Balloon' }),
          h('span', { class: 'bl-hl', text: x.label }),
          h('span', { class: 'bl-ht', text: x.text || '' }),
          h('span', { class: 'bl-hm', text: x.more || '' }),
          h('span', { class: 'bl-hw', text: where }));
        row.addEventListener('click', () => {
          if (x.here) {
            dlg.close();
            if (x.kind === 'char') { const c = this.data.chars.find((c) => String(c.label) === String(x.label)); if (c) { if (this.tab === 'issues') { this.tab = 'chars'; this._head(); this._grid(); } this.select(c.id, { toPage: true, toRow: true }); } }
            else { const i = (this.data.issues || []).find((i) => `#${i.n}` === x.label.split(' ')[0]); if (i) { this.tab = 'issues'; this.ishow = 'all'; this._head(); this._grid(); this.editIssue(i); } }
          } else if (!x.missing) { dlg.close(); this.v.app?.openPath(x.path); }
        });
        return row;
      }), hits.length >= 300 ? h('p', { class: 'bl-hint', text: 'The first 300: type more to narrow it.' }) : '');
    };
    let t = null;
    q.addEventListener('input', () => { clearTimeout(t); t = setTimeout(go, 250); });
    q.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') { clearTimeout(t); go(); } });
    scope.addEventListener('change', go);
    dlg = modal('Search', h('div', { class: 'pe-fprops bl-props' },
      h('div', { class: 'bl-sbar' }, q, scope), out,
      h('p', { class: 'bl-hint', text: 'A print is searchable across jobs once it has been saved with its balloons.' })), { width: 820 });
    go();
    setTimeout(() => q.focus(), 30);
  }

  // what was changed in the job's details, newest first (one field's, or all)
  _logList(field = null) {
    const label = Object.fromEntries(this.data.fields || []);
    const rows = (this.data.log || []).filter((x) => !field || x.field === field).slice().reverse();
    if (!rows.length) return h('p', { class: 'bl-hint', text: 'Nothing changed yet.' });
    return h('div', { class: 'bl-log' }, ...rows.map((x) => h('div', { class: 'bl-logi' },
      h('div', { class: 'bl-logh', text: x.field === 'status' ? `Status: ${STATUS_LABEL[x.old] || x.old} → ${STATUS_LABEL[x.new] || x.new}` : `${label[x.field] || x.field}: ${x.old || '(empty)'} → ${x.new || '(empty)'}` }),
      h('div', { class: 'bl-logw', text: `${when(x.at)}${x.who ? ` · ${x.who}` : ''}` }),
      h('div', { class: 'bl-logn', text: x.note || '' }))));
  }

  // Job…: the job's details, and what was changed in them
  job() {
    const was = this.data.info || {};
    const row = (label, el, mark) => h('label', { class: 'pe-frow' }, h('span', { text: label }), mark ? h('span', { class: 'bl-withmark' }, el, mark) : el);
    const hist = h('div', { class: 'bl-hist' });
    const showLog = (k) => { hist.replaceChildren(h('div', { class: 'bl-histh' }, h('b', { text: k ? `${Object.fromEntries(this.data.fields)[k]}: changes` : 'All changes' }), k ? h('button', { class: 'bl-link', text: 'Show all', onclick: () => showLog(null) }) : ''), this._logList(k)); };
    const inputs = this._infoInputs(was, showLog);
    if ((this.data.log || []).length) showLog(null);
    let dlg = null;
    const ok = async () => {
      const info = { parts: was.parts };
      for (const [k, , el] of inputs) if (el.value.trim()) info[k] = el.value.trim();
      dlg.close();
      await this._saveInfo(info);
    };
    dlg = modal('Job details', h('div', { class: 'pe-fprops bl-props' },
      h('div', { class: 'bl-sidline' }, h('span', { text: 'Sheet ID' }), h('b', { text: this.data.sid || '(given when first saved)' }), this.data.from ? h('span', { class: 'bl-hint', text: `carried over from ${this.data.from}` }) : ''),
      h('div', { class: 'bl-two' }, ...inputs.map(([, label, el, mark]) => row(label, el, mark))),
      hist,
      h('p', { class: 'bl-hint', text: 'Kept with the balloons in the print, and written on the report. A detail changed once it was filled in needs a change note: ✎ beside it shows what it was, who changed it, when and why.' }),
      h('div', { class: 'pe-pop-foot' },
        h('span', { class: 'pv-grow' }),
        h('button', { class: 'btn', text: 'Cancel', onclick: () => dlg.close() }),
        h('button', { class: 'btn primary', text: 'Save', onclick: ok }))), { width: 780 });
    for (const [, , el] of inputs) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') ok(); e.stopPropagation(); });
    setTimeout(() => inputs[0]?.[2].focus(), 30);
  }

  // Report…: what the report says about the job (kept with the list in the PDF), then where to save the workbook
  report() {
    if (!this.data.chars.length) { toast('There are no balloons to report yet.', 'info'); return; }
    const was = this.data.info || {}, doc = this.doc;
    const row = (label, el) => h('label', { class: 'pe-frow' }, h('span', { text: label }), el);
    const mine = { org: 'bl:org', supplier: 'bl:supplier' }; // (who we are: the same on every job, so kept on this computer)
    const inputs = this._infoInputs(was, () => this.job());
    const parts = h('input', { type: 'number', min: 1, max: 50, step: 1, value: Math.max(was.parts || 5, (this.data.samples || []).length),
      title: 'How many parts will be inspected: the report gets a results column for each one\n(the inspection sheet has them in fives)' });
    const layout = h('select', {}, ...(this.data.layouts || []).map(([k, label]) => h('option', { value: k, text: label, selected: k === kept('bl:layout') })));
    const footer = h('textarea', { rows: 2, spellcheck: 'false', placeholder: 'Your form number, a policy note…',
      title: 'Lines for the bottom of the inspection sheet. Remembered on this computer for every report.' });
    footer.value = kept('bl:footer');
    // what else the PDF has: set fresh each time (the logo is remembered on this computer)
    const check = (label, on, tip) => { const box = h('input', { type: 'checkbox' }); box.checked = on; return [box, h('label', { class: 'bl-pcheck', title: tip }, box, label)]; };
    const [headBox, headEl] = check('Header and printed line', true, "A line across the top of every page: part, revision, job, sheet id and status;\nand along the bottom when it was printed, by whom, and the app's version");
    const nIssues = (this.data.issues || []).filter((i) => !i.hidden).length, nPhotos = (this.data.photos || []).length;
    const [issueBox, issueEl] = check(`Production issues${nIssues ? ` (${nIssues})` : ''}`, false, 'The production issues not hidden, on a page of their own');
    issueBox.disabled = !nIssues;
    const photoSel = h('select', { disabled: !nPhotos, title: 'The photos with their markup, each saying what it is of' },
      ...[['', 'No photos'], ['small', 'Photos: small'], ['medium', 'Photos: medium'], ['large', 'Photos: large']].map(([k, label]) => h('option', { value: k, text: nPhotos && k ? `${label} (${nPhotos})` : label })));
    let logo = kept('bl:logo');
    const logoName = h('span', { class: 'bl-hint', text: logo ? 'Logo chosen' : 'No logo' });
    const logoFile = h('input', { type: 'file', accept: 'image/*', hidden: true });
    logoFile.addEventListener('change', () => {
      const f = logoFile.files[0];
      if (!f) return;
      const r = new FileReader();
      r.onload = () => { logo = String(r.result); keep('bl:logo', logo); logoName.textContent = f.name; };
      r.readAsDataURL(f);
    });
    const logoRow = h('span', { class: 'bl-logo' }, h('button', { class: 'btn', type: 'button', text: 'Logo…', title: "A picture for the top left of the PDF's first page. Remembered on this computer.", onclick: () => logoFile.click() }),
      h('button', { class: 'bl-link', type: 'button', text: 'None', onclick: () => { logo = ''; keep('bl:logo', ''); logoName.textContent = 'No logo'; } }), logoName, logoFile);
    let dlg = null;
    const ok = async () => {
      dlg.close();
      const info = { parts: Math.min(Math.max(parseInt(parts.value, 10) || 1, 1), 50) };
      for (const [k, , el] of inputs) if (el.value.trim()) info[k] = el.value.trim();
      keep('bl:layout', layout.value);
      keep('bl:footer', footer.value);
      for (const [k, key] of Object.entries(mine)) if (info[k]) keep(key, info[k]);
      if (!await this._saveInfo(info)) return;
      const name = `${info.part || doc.name.replace(/\.pdf$/i, '')} inspection report.xlsx`;
      const r = await api.saveXlsxDialog(name, 'Save Inspection Report As').catch((e) => { toast(e.message, 'error'); return null; });
      if (!r?.path || this.doc !== doc) return;
      try {
        const printing = { header: headBox.checked, issues: issueBox.checked, photos: photoSel.value || null, logo: logo || null };
        const done = await api.pdfEdit(doc.id, 'balloon_report', { path: r.path, parts: info.parts, layout: layout.value, footer: footer.value, printing });
        this.ed._saved(`Inspection report saved: ${done.count} characteristic${done.count === 1 ? '' : 's'}, room for ${done.parts} part${done.parts === 1 ? '' : 's'}. The sheet is beside it as a PDF.`, done.path);
      } catch (e) { toast(e.message, 'error'); }
    };
    dlg = modal('Inspection report', h('div', { class: 'pe-fprops bl-props' },
      h('div', { class: 'bl-two' }, ...inputs.map(([, label, el]) => row(label, el)), row('Parts to inspect', parts)),
      row('Layout', layout), row('Footer', footer),
      h('div', { class: 'pe-frow' }, h('span', { text: 'The PDF' }), h('div', { class: 'bl-print' }, headEl, issueEl, photoSel, logoRow)),
      h('p', { class: 'bl-hint', text: 'An Excel workbook: each balloon with its description, gage, nominal and limits, and a column for each part. What the parts measured (the Results tab) is written in under each part; a result outside its limits is red. The first article layout adds AS9102 Forms 1, 2 and 3. The inspection sheet is saved as a PDF too, beside the workbook under the same name. The job details are kept with the balloons in the print.' }),
      h('div', { class: 'pe-pop-foot' },
        h('span', { class: 'pv-grow' }),
        h('button', { class: 'btn', text: 'Cancel', onclick: () => dlg.close() }),
        h('button', { class: 'btn primary', text: 'Save report…', onclick: ok }))), { width: 780 });
    footer.addEventListener('keydown', (e) => e.stopPropagation());
    for (const el of [parts, ...inputs.map((i) => i[2])]) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') ok(); e.stopPropagation(); });
    setTimeout(() => inputs[0]?.[2].focus(), 30);
  }

  remove(id) {
    if (this.sel === id) this.sel = null;
    this.run('balloon_delete', { ids: [id] });
  }

  /** Another thing to check on the same callout: a new balloon under this one's number, and its details to fill in. */
  async addSub(c) {
    const r = await this.run('balloon_sub', { id: c.id });
    const made = this.char(r?.result?.ids?.[0]);
    if (made) { this.select(made.id, { toRow: true }); this.edit(made); }
  }

  select(id, { toPage = false, toRow = false } = {}) {
    this.sel = id;
    this.layout();
    for (const tr of this.wrap.querySelectorAll('tr[data-id]')) {
      const on = +tr.dataset.id === id;
      tr.classList.toggle('on', on);
      if (on && toRow) tr.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
    if (toPage) this.els.get(id)?.scrollIntoView({ block: 'center', inline: 'center' });
    this._row();
  }

  // ================================================================== the keyboard
  _key(e) {
    if (!this.on || !this.doc || this.v.el.hidden || typing(e.target) || document.querySelector('.modal-back')) return;
    const stop = () => { e.preventDefault(); e.stopImmediatePropagation(); };
    if (e.key === 'Escape' && (this.adding || this.sel !== null)) {
      if (this.adding) this._adding(false); else this.select(null);
      e.stopImmediatePropagation();
      return;
    }
    if ((e.key === 'Delete' || e.key === 'Backspace') && this.sel !== null && !this.ed.sel && !this.ed.fsel) {
      this.remove(this.sel);
      stop();
      return;
    }
    if (!this.dock.contains(document.activeElement)) return; // the rest is the list's, while it has the keyboard
    const results = this.tab === 'results';
    const rows = results ? this.data.chars : this._shown(), i = rows.findIndex((c) => c.id === this.sel);
    if (results && (e.key === 'Enter' || e.key === 'F2') && i >= 0) { // the selected row's first part still to measure
      const r = this._rrows().find((x) => x.c.id === this.sel), parts = this.data.samples || [];
      const p = parts.find((x) => !(this.data.results[r.key] || {})[x.id]) || parts[0];
      if (p) this._editResult(r.key, p.id);
      stop();
    } else if (results && e.key === ' ') {
      stop();
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      const to = rows[i < 0 ? 0 : i + (e.key === 'ArrowDown' ? 1 : -1)];
      if (to) this.select(to.id, { toPage: true, toRow: true });
      stop();
    } else if ((e.key === 'Enter' || e.key === 'F2') && i >= 0) {
      this._editCell(rows[i], COLS.find((x) => x.k === this.col && x.edit) || COLS.find((x) => x.k === 'text'));
      stop();
    } else if (e.key === ' ' && i >= 0) {
      this.run('balloon_edit', { id: rows[i].id, reviewed: !rows[i].reviewed });
      stop();
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
    el.style.setProperty('--bl', c.color || '#d11212'); // (its view's color; after the place, which sets the whole style)
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
      el.title = `${c.label}: ${c.text || '(no requirement yet)'}${this._limits(c) ? `\n${this._limits(c)}` : ''}${multiplied(c) ? `\nMultiplied: ${c.label}.1 to ${c.label}.${c.count} in the list and the report` : ''}\nDrag to move, double-click to change, Delete to remove`;
      el.classList.toggle('on', this.sel === c.id);
      if (el.parentNode !== p.edit) p.edit.append(el);
      this._put(el, p, c, c.at);
      // its callout is marked on the print: orange until it's reviewed, then green; the selected one stands out
      // (a balloon dropped on bare paper has no callout: its box is only a place holder beside it)
      let rq = this.reqs.get(c.id);
      if (Math.abs(c.box[2] - 2 * c.r) < 0.01 && Math.abs(c.box[3] - 2 * c.r) < 0.01) { rq?.remove(); this.reqs.delete(c.id); continue; }
      if (!rq) { rq = h('div'); this.reqs.set(c.id, rq); }
      rq.className = `bl-req${c.reviewed ? ' ok' : ''}${this.sel === c.id ? ' on' : ''}`;
      rq.style.cssText = this.v._rectStyle(p, [c.box[0] - 1.5, c.box[1] - 1.5, c.box[2] + 3, c.box[3] + 3]);
      if (rq.parentNode !== p.marks) p.marks.append(rq);
    }
    for (const [id, el] of this.els) if (!live.has(id)) { el.remove(); this.els.delete(id); }
    for (const [id, el] of this.reqs) if (!live.has(id)) { el.remove(); this.reqs.delete(id); }
    const views = new Set();
    for (const vw of this.data.views || []) {
      const p = this.v.pages?.[vw.page];
      if (!p) continue;
      views.add(vw.id);
      let el = this.vels.get(vw.id);
      if (!el) {
        el = h('div', { class: 'bl-view' }, h('button', { class: 'bl-vname', onclick: (e) => { e.stopPropagation(); this.editView(el.view); } }));
        el.firstChild.addEventListener('pointerdown', (e) => e.stopPropagation());
        this.vels.set(vw.id, el);
      }
      el.view = vw;
      el.style.cssText = this.v._rectStyle(p, vw.rect);
      el.style.setProperty('--vc', vw.color);
      el.firstChild.textContent = `${vw.name}${vw.start ? ` · from ${vw.start}` : ''}`;
      el.firstChild.title = `${vw.name}: ${vw.count} balloon${vw.count === 1 ? '' : 's'}. Click to rename it, change its color or start number, or delete it.`;
      if (el.parentNode !== p.edit) p.edit.prepend(el);
    }
    for (const [id, el] of this.vels) if (!views.has(id)) { el.remove(); this.vels.delete(id); }
  }

  // ================================================================== views
  _viewsMenu(anchor) {
    const views = this.data.views || [];
    menu(anchor, [
      { label: 'Add view (drag a box round it)', action: () => this._adding('view') },
      views.length ? { sep: true } : null,
      ...views.map((vw) => ({ label: `${vw.name} (${vw.count})${vw.start ? `, from ${vw.start}` : ''}`, glyph: null, action: () => this.editView(vw) })),
      views.length ? { sep: true } : null,
      views.length ? { label: 'Renumber view by view…', action: () => this._renumberMenu(anchor) } : null,
    ]);
  }

  _renumberMenu(anchor) {
    const views = (this.data.views || []).length;
    menu(anchor, [
      { head: views ? 'Renumber, view by view' : 'Renumber' },
      ...ORDERS.map(([order, label, tip]) => ({ label: `${label}: ${tip.toLowerCase()}`, action: () => this.run('balloon_renumber', { order }) })),
    ]);
  }

  editView(vw) {
    const row = (label, el) => h('label', { class: 'pe-frow' }, h('span', { text: label }), el);
    const name = h('input', { type: 'text', spellcheck: 'false', value: vw.name });
    const color = h('input', { type: 'color', value: vw.color, class: 'bl-color' });
    const start = h('input', { type: 'number', min: 0, step: 1, value: vw.start ?? '', placeholder: 'Carry on from the view before',
      title: 'The number its first balloon gets when renumbered (if that is further on than the view before ends)' });
    const views = this.data.views, i = views.findIndex((x) => x.id === vw.id);
    let dlg = null;
    const ok = () => {
      dlg.close();
      const o = { id: vw.id };
      if (name.value.trim() && name.value.trim() !== vw.name) o.name = name.value.trim();
      if (color.value !== vw.color) o.color = color.value;
      if (String(start.value) !== String(vw.start ?? '')) o.start = start.value === '' ? 0 : +start.value;
      if (Object.keys(o).length > 1) this.run('balloon_view_edit', o);
    };
    dlg = modal(vw.name, h('div', { class: 'pe-fprops bl-props' },
      row('Name', name), row('Color', color), row('Start number', start),
      h('p', { class: 'bl-hint', text: `${vw.count} balloon${vw.count === 1 ? '' : 's'} in this view, on sheet ${vw.page + 1}. Its balloons are drawn in its color. Renumber numbers the views in their order here (${i + 1} of ${views.length}).` }),
      h('div', { class: 'pe-pop-foot' },
        h('button', { class: 'btn', text: 'Delete view', onclick: () => { dlg.close(); this.run('balloon_view_delete', { id: vw.id }); } }),
        h('button', { class: 'btn', text: '↑', title: 'Earlier in the order', disabled: i === 0, onclick: () => { dlg.close(); this.run('balloon_view_edit', { id: vw.id, move: -1 }); } }),
        h('button', { class: 'btn', text: '↓', title: 'Later in the order', disabled: i === views.length - 1, onclick: () => { dlg.close(); this.run('balloon_view_edit', { id: vw.id, move: 1 }); } }),
        h('span', { class: 'pv-grow' }),
        h('button', { class: 'btn', text: 'Cancel', onclick: () => dlg.close() }),
        h('button', { class: 'btn primary', text: 'OK', onclick: ok }))), { width: 420 });
    for (const el of [name, start]) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') ok(); e.stopPropagation(); });
    setTimeout(() => { name.focus(); name.select(); }, 30);
  }

  // a balloon is pressed: it's selected, and a drag moves it
  _down(e, el) {
    if (e.button !== 0 || this.adding) return;
    if (this.fixed) { e.stopPropagation(); this.select(el.char.id, { toRow: true }); return; }
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
    const view = this.adding === 'view';
    if (view) ghost.classList.add('bl-vghost');
    this.ed._drag(e, p, this.v._pagePoint(p, e), (a, b) => { ghost.style.cssText = this.v._rectStyle(p, rectOf(a, b)); }, async (a, b, moved) => {
      ghost.remove();
      this._adding(false);
      const rect = moved ? rectOf(a, b) : [a[0], a[1], 0, 0];
      if (view) {
        if (!moved) { toast('Drag a box round the view.', 'info'); return; }
        const r = await this.run('balloon_view_add', { page: p.i, rect });
        const made = r?.result?.views?.find((v) => v.id === r.result.view);
        if (made) toast(`${made.name}: ${made.count} balloon${made.count === 1 ? '' : 's'} in it. Click its name on the print to rename it or give it a start number.`, 'ok', 5000);
        return;
      }
      const r = await this.run('balloon_add', { page: p.i, rect }, 'Reading it…');
      const id = r?.result?.ids?.[0];
      if (id === undefined) return;
      this.select(id, { toRow: true });
      const c = this.char(id);
      if (c && !c.text) this.edit(c);
    });
  }

  // ================================================================== the mode's toolbar
  render() {
    if (!this.on) return;
    this._row();
    this._head();
    this._grid();
    this.layout();
  }

  _row() {
    if (!this.on) return;
    const n = this.data.chars.length, st = this.ed.state || {}, sel = this.sel === null ? null : this.char(this.sel);
    const b = (text, tip, run, o = {}) => h('button', { class: `pv-btn bl-tb${o.cls ? ` ${o.cls}` : ''}`, text, title: tip, disabled: !!o.off || (o.edits && this.fixed), onclick: run });
    const more = b('▾', 'Auto Balloon again, or remove all the balloons', () => this._autoMenu(more), { cls: 'bl-more', edits: true });
    const mult = b('Multiply ▾', 'A characteristic that applies in several places (4X) is inspected in each one:\nMultiply gives it a row for each place (3.1 to 3.4) in the list and the report, under its one balloon.\nDetach makes each place a balloon of its own. Reset puts it back to one row.', () => this._multMenu(mult), { off: !n, edits: true });
    const renumber = b('Renumber ▾', 'Number the balloons 1, 2, 3…, closing the gaps: in list order, by rows, by columns, or clockwise.\nWith views, view by view. Those sharing a number stay together.', () => this._renumberMenu(renumber), { off: !n, edits: true });
    this.viewBtn = b(`Views${(this.data.views || []).length ? ` (${this.data.views.length})` : ''} ▾`, "Boxes round the drawing's views: their balloons take the view's color,\nand Renumber goes view by view, each from its own start number", () => this._viewsMenu(this.viewBtn), { cls: this.adding === 'view' ? 'on' : '', edits: true });
    this.addBtn = b('Add', 'Balloon something by hand: drag a box around a callout on the print (its text is read),\nor click a spot for an empty balloon to fill in. Esc cancels.', () => this._adding(this.adding === 'balloon' ? false : 'balloon'), { cls: this.adding === 'balloon' ? 'on' : '', edits: true });
    this.row.replaceChildren(
      h('span', { class: 'bl-mode', text: 'Ballooning' }),
      (() => { const s = this.data.status || 'draft', sb = b(`${STATUS_LABEL[s]} ▾`, 'Draft: being ballooned. Released: its balloons and characteristics are fixed.\nSuperseded: by the next revision, and nothing in it changes.', () => this._statusMenu(sb), { cls: `bl-status s-${s}`, off: !n && s === 'draft' }); return sb; })(),
      (() => { const lb = b(this._roleText(), this._roleTip(), () => this._rolesMenu(lb), { cls: `bl-role${this.roles?.level ? ' open' : ''}` }); lb.hidden = !this.roles; return lb; })(),
      this.data.sid ? h('span', { class: 'bl-sid', text: this.data.sid, title: `This sheet's id: it stays the same whatever is edited.${this.data.from ? `\nCarried over from ${this.data.from}.` : ''}` }) : '',
      h('span', { class: 'pv-sep' }),
      b('Auto Balloon', 'Read the print and balloon what there is to inspect on it: dimensions and their tolerances, angles,\nchamfers, threads, finishes, feature control frames and notes. It asks which pages and what to balloon first.', () => this.auto(), { cls: 'bl-main', edits: true }),
      more,
      this.addBtn,
      b('Sub-balloon', "Another thing to check on the selected balloon's callout:\na new balloon under its number (2.1, 2.2…)", () => this.addSub(sel), { off: !sel, edits: true }),
      b('Edit…', "All of the selected balloon's details in one place (or double-click the balloon)", () => this.edit(sel), { off: !sel }),
      b('Delete', 'Remove the selected balloon (Delete)', () => this.remove(sel.id), { off: !sel, edits: true }),
      h('span', { class: 'pv-sep' }),
      renumber,
      this.viewBtn,
      mult,
      h('span', { class: 'pv-sep' }),
      b('Search…', 'Find characteristics and production issues by balloon number, dimension, description, gage or earlier fix:\non this print, or on every ballooned print saved on this computer', () => this.search(), {}),
      b('Job…', "The job's details: part, revision, customer, job number, lot… and what was changed, by whom and why.\nA detail changed once it was filled in needs a change note.", () => this.job(), { off: !n }),
      b('Report…', 'Write the inspection report as an Excel workbook and a PDF: the sheet to print and fill in, five parts to a table,\nor the list with Pass / Fail worked out from the results, with AS9102 Form 3', () => this.report(), { off: !n }),
      h('span', { class: 'pv-grow' }),
      b('Undo', 'Undo (Ctrl+Z)', () => this.ed.undo(), { off: !st.undo }),
      b('Redo', 'Redo (Ctrl+Y)', () => this.ed.redo(), { off: !st.redo }),
      b(st.dirty ? 'Save' : 'Saved', 'Save the print with its balloons and its list (Ctrl+S)', () => this.ed.save(), { cls: st.dirty ? 'pe-dirty' : '' }),
      h('span', { class: 'pv-sep' }),
      b('Exit Ballooning', 'Back to the PDF view and its tools. The balloons stay on the print.', () => this.toggle(), { cls: 'bl-exit' }),
    );
  }

  // ================================================================== the Bill of Characteristics
  _shown() {
    const f = this.filter;
    if (f.startsWith('tag:')) return this.data.chars.filter((c) => (c.tags || []).includes(f.slice(4)));
    return this.data.chars.filter((c) => (f === 'todo' ? !c.reviewed : f === 'done' ? !!c.reviewed : f === 'open' ? open(c) : true));
  }

  _head() {
    const d = this.data, n = d.chars.length;
    const show = h('select', { class: 'bl-show', title: 'Which characteristics the list shows' },
      ...FILTERS.map(([k, label]) => h('option', { value: k, text: label, selected: k === this.filter })),
      ...(d.tags?.length ? [h('optgroup', { label: 'Tagged' }, ...d.tags.map((t) => h('option', { value: `tag:${t}`, text: t, selected: `tag:${t}` === this.filter })))] : []));
    show.addEventListener('change', () => { this.filter = show.value; this._grid(); });
    const tols = h('div', { class: 'bl-tols', title: "The title block's tolerances by the number of decimals. A size with no tolerance of its own gets its limits\nfrom these. Read from the print: correct them here if they were read wrong." },
      h('span', { class: 'bl-tl', text: 'General tolerance ±' }),
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
    const tab = (id, label, tip) => h('button', { class: `bl-tab${this.tab === id ? ' on' : ''}`, text: label, title: tip,
      onclick: () => { if (this.tab !== id) { this.tab = id; this.wrap.scrollTop = 0; this.wrap.scrollLeft = 0; this._head(); this._grid(); } } });
    const tabs = h('div', { class: 'bl-tabs' },
      tab('chars', 'Bill of Characteristics', 'What there is to inspect: every balloon with its requirement and limits'),
      tab('results', 'Results', 'What each part measured: a column for each part inspected'),
      tab('issues', `Production Issues${(d.issues || []).filter(unresolved).length ? ` (${(d.issues || []).filter(unresolved).length} open)` : ''}`,
        'What has to be dialed in before the part can run, or while it does: each about a balloon,\nfixed by a machinist and resolved by a lead'));
    if (this.tab === 'issues') {
      const show = h('select', { class: 'bl-show', title: 'Which issues the list shows' },
        ...ISSUE_SHOW.map(([k, label]) => h('option', { value: k, text: label, selected: k === this.ishow })));
      show.addEventListener('change', () => { this.ishow = show.value; this._grid(); });
      const sel = this.sel === null ? null : this.char(this.sel);
      this.head.replaceChildren(tabs,
        h('button', { class: 'btn bl-hbtn', text: sel ? `+ Add issue on ${sel.label}` : '+ Add issue', title: 'Something to dial in: on the selected balloon, or on none', onclick: () => this.editIssue(null) }),
        h('label', { class: 'bl-showl' }, 'Show', show),
        h('span', { class: 'pv-grow' }),
        this._count());
      return;
    }
    if (this.tab === 'results') {
      const parts = d.samples || [];
      this.head.replaceChildren(tabs,
        h('button', { class: 'btn bl-hbtn', text: '+ Add part', title: 'Another part to inspect: a column for what it measures.\nDouble-click its heading to give it its serial number.', disabled: !n, onclick: () => this.addPart() }),
        h('button', { class: 'btn bl-hbtn', text: 'Sampling…', title: 'Which parts of the lot to inspect: every part, the first and last, 1 in N, or a share of them.\nA column is added for each.', disabled: !n, onclick: () => this.sampling() }),
        h('button', { class: 'btn bl-hbtn', text: 'Import…', title: "Results from a CMM's or a gage's export, or a spreadsheet: CSV, text or Excel (.xlsx),\nmatched to the balloons by their numbers", disabled: !n, onclick: () => this.importResults() }),
        parts.length ? h('button', { class: 'bl-link', text: 'New lot…', title: 'Take out every part and result, to inspect another lot against the same balloons', onclick: () => this.newLot() }) : '',
        h('span', { class: 'pv-grow' }),
        this._count());
      return;
    }
    this.head.replaceChildren(tabs,
      h('label', { class: 'bl-showl' }, 'Show', show),
      this.fixed ? h('span', { class: 'bl-locked', text: this.data.status === 'superseded' ? 'Superseded: read only' : 'Released: characteristics fixed', title: 'Back to draft (the status beside the sheet id) to change them' }) : tols,
      h('span', { class: 'pv-grow' }),
      this._count());
  }

  // what a cell says
  _cell(c, k) {
    const num = (v) => this._fmt(Math.abs(v), c.places, c.kind).replace(/\.$/, '');
    const signed = (v, plus) => (v == null ? '' : `${(v < 0) === plus ? '-' : '+'}${num(v)}`);
    switch (k) {
      case 'n': return String(c.label);
      case 'where': return c.where || '';
      case 'kind': return c.type || this.data.labels[c.kind] || c.kind;
      case 'count': return c.count > 1 ? `${c.count}x` : '';
      case 'nominal': return c.nominal == null ? '' : `${c.nominal < 0 ? '-' : ''}${num(c.nominal)}${c.kind === 'angle' ? '°' : ''}`;
      case 'plus': return signed(c.plus, true);
      case 'minus': return signed(c.minus, false); // (kept as how far below: .005 is -.005)
      case 'lo': case 'hi': return c[k] == null ? '' : `${c[k] < 0 ? '-' : ''}${num(c[k])}${c.kind === 'angle' ? '°' : ''}`;
      case 'tol': return { default: 'General', ref: 'Reference', basic: 'Basic' }[c.tol] || '';
      case 'tags': return (c.tags || []).join(', ');
      default: return c[k] || '';
    }
  }

  // what's typed into a cell, as the change to make (null: none)
  _change(c, k, value) {
    const s = value.trim();
    const f = parseFloat(s.replace(',', '.').replace(/[+°]/g, '')), num = Number.isFinite(f) ? f : null;
    switch (k) {
      case 'n': { const to = s.replace(',', '.'); return /^\d+(\.\d+)?$/.test(to) && to !== String(c.label) ? { n: to } : null; }
      case 'kind': return s && s !== c.kind ? { kind: s } : null;
      case 'tol': return { tol: s || 'auto' };
      case 'count': { const q = parseInt(s, 10) || 1; return q !== (c.count || 1) ? { count: q } : null; }
      case 'nominal': return num === null ? { nominal: null } : { nominal: num, places: decimals(s.replace(/[^\d.,]/g, '')) };
      case 'plus': return { plus: num };
      case 'minus': return num === null ? { minus: null } : { minus: s.startsWith('+') ? -Math.abs(num) : Math.abs(num), ...(c.plus == null ? { plus: 0 } : {}) };
      case 'lo': case 'hi': return { [k]: num, plus: null, minus: null }; // typed limits stand on their own
      default: return s !== (c[k] || '') ? { [k]: s } : null;
    }
  }

  _grid() {
    if (!this.on) return;
    if (this.tab === 'results') { this._resultsGrid(); return; }
    if (this.tab === 'issues') { this._issuesGrid(); return; }
    const d = this.data, rows = this._shown(), top = this.wrap.scrollTop, left = this.wrap.scrollLeft, had = this.dock.contains(document.activeElement);
    // a cell being typed into when the list is drawn again (the edit before it has just landed) is taken up where it was
    const live = this._editing;
    this._editing = null;
    if (live) {
      if (live.el.isConnected && !this._next) this._next = { id: live.id, k: live.k, typed: live.el.value };
      live.drop();
    }
    if (!d.chars.length) {
      this._next = null;
      this.wrap.replaceChildren(h('div', { class: 'bl-empty', text: this.busy ? 'Reading the print…' : 'No balloons on this print yet. Auto Balloon reads it; Add balloons something by hand.' }));
      return;
    }
    const all = h('input', { type: 'checkbox' });
    all.checked = rows.length > 0 && rows.every((c) => c.reviewed);
    all.addEventListener('change', () => this.run('balloon_reviewed', { ids: rows.map((c) => c.id), on: all.checked }));
    const head = h('tr', {}, ...COLS.map((col) => h('th', { title: col.tip || '' }, col.k === 'reviewed' ? h('label', { class: 'bl-allrev' }, all, col.head) : col.head)));
    const row = (c, place) => { // place: which of a multiplied characteristic's places this row is (0: it isn't multiplied)
      const tr = h('tr', { 'data-id': c.id, 'data-place': place, class: `${this.sel === c.id ? 'on' : ''}${place > 1 ? ' more' : ''}` });
      for (const col of COLS) {
        if (col.k === 'reviewed') {
          const box = h('input', { type: 'checkbox', title: 'Checked against the print', disabled: this.fixed });
          box.checked = !!c.reviewed;
          box.addEventListener('click', (e) => e.stopPropagation());
          box.addEventListener('dblclick', (e) => e.stopPropagation());
          box.addEventListener('change', () => this.run('balloon_edit', { id: c.id, reviewed: box.checked }));
          tr.append(h('td', { class: 'bl-c-rev' }, box));
          continue;
        }
        const text = !place ? this._cell(c, col.k) : col.k === 'n' ? `${c.label}.${place}` : col.k === 'count' ? `${place} of ${c.count}` : this._cell(c, col.k);
        const general = (c.tol === 'default' && ['plus', 'minus', 'lo', 'hi', 'tol'].includes(col.k)) || (bare(c) && ['nominal', 'tol'].includes(col.k));
        const td = h('td', { 'data-k': col.k, class: `${col.edit ? 'ed' : ''}${col.mono ? ' mono' : ''}${col.edit === 'num' ? ' mono r' : ''}${general ? ' def' : ''}`, title: text.length > 22 ? text : '' },
          col.k === 'n' ? h('span', { class: 'bl-nwrap' }, h('span', { class: 'bl-num', text }), (d.issues || []).some((i) => i.char === c.id && unresolved(i)) && place < 2 ? h('span', { class: 'bl-flag', text: '⚑', title: 'It has an open production issue' }) : '') : text);
        td.addEventListener('click', () => { this.col = col.k; });
        if (col.edit) td.addEventListener('dblclick', (e) => { e.stopPropagation(); this._editCell(c, col, null, tr); });
        tr.append(td);
      }
      tr.addEventListener('click', () => this.select(c.id, { toPage: true }));
      tr.addEventListener('dblclick', () => this.edit(c)); // (on a cell that isn't typed into)
      tr.addEventListener('contextmenu', (e) => this._rowMenu(e, c));
      return tr;
    };
    const trs = rows.flatMap((c) => (multiplied(c) ? Array.from({ length: c.count }, (_, k) => row(c, k + 1)) : [row(c, 0)]));
    const width = COLS.reduce((s, c) => s + c.w, 0);
    const table = h('table', { class: 'bl-grid', style: { width: `max(100%, ${width}px)` } },
      h('colgroup', {}, ...COLS.map((c) => h('col', { style: { width: `${c.w}px` } }))),
      h('thead', {}, head),
      h('tbody', {}, ...trs));
    if (rows.length) this.wrap.replaceChildren(table);
    else this.wrap.replaceChildren(table, h('div', { class: 'bl-empty', text: 'None of the characteristics are like that.' }));
    this.wrap.scrollTop = top;
    this.wrap.scrollLeft = left;
    if (had) this.wrap.focus({ preventScroll: true });
    this.head.querySelector('.bl-count')?.replaceWith(this._count());
    const next = this._next; // typing goes on in the cell Enter or Tab was headed for
    this._next = null;
    const c = next && this.char(next.id), col = next && COLS.find((x) => x.k === next.k);
    if (c && col) this._editCell(c, col, next.typed ?? null);
  }

  _count() {
    if (this.tab === 'issues') {
      const all = (this.data.issues || []).filter((i) => !i.hidden), open = all.filter(unresolved).length, fixed = all.filter((i) => i.status === 'fixed').length;
      return h('span', { class: `bl-count${open ? ' bad' : ''}`, text: all.length ? `${all.length} issue${all.length === 1 ? '' : 's'} · ${open} open${fixed ? ` · ${fixed} ready for lead` : ''}` : '' });
    }
    if (this.tab === 'results') {
      const rows = this._rrows(), parts = this.data.samples || [], res = this.data.results || {};
      let filled = 0, failed = 0;
      for (const r of rows) for (const p of parts) { const v = (res[r.key] || {})[p.id]; if (v) { filled++; if (judge(r.c, v) === false) failed++; } }
      return h('span', { class: `bl-count${failed ? ' bad' : ''}`, text: parts.length ? `${parts.length} part${parts.length === 1 ? '' : 's'} · ${filled} of ${rows.length * parts.length} results${failed ? ` · ${failed} failed` : ''}` : '' });
    }
    const d = this.data, n = d.chars.length, rev = d.chars.filter((c) => c.reviewed).length, bare = d.chars.filter(open).length, shown = this._shown().length;
    const each = d.chars.reduce((sum, c) => sum + (multiplied(c) ? c.count : 1), 0); // rows to inspect, a multiplied one's places each counted
    return h('span', { class: 'bl-count', text: n ? `${shown === n ? n : `${shown} of ${n}`} characteristic${n === 1 ? '' : 's'}${each > n ? ` (${each} rows)` : ''} · ${rev} reviewed${bare ? ` · ${bare} with no limits yet` : ''}` : '' });
  }

  // ================================================================== Results: what each part measured
  // the rows results are typed into: a characteristic, or each place of a multiplied one
  _rrows() {
    return this.data.chars.flatMap((c) => (multiplied(c)
      ? Array.from({ length: c.count }, (_, k) => ({ c, key: `${c.id}.${k + 1}`, label: `${c.label}.${k + 1}` }))
      : [{ c, key: String(c.id), label: String(c.label) }]));
  }

  async addPart() {
    const r = await this.run('balloon_part_add', {});
    const id = r?.result?.part, first = this._rrows()[0];
    if (id !== undefined && first && this.tab === 'results') this._editResult(first.key, id);
  }

  // results from another program's export: which columns are what, then in they go
  async importResults() {
    const doc = this.doc;
    const pick = await api.openFiles('results', 'Choose the results to import').catch((e) => { toast(e.message, 'error'); return null; });
    const path = pick?.files?.[0]?.path;
    if (!path || this.doc !== doc) return;
    let pre;
    try { pre = await api.pdfEdit(doc.id, 'balloon_import', { path, preview: true }); } catch (e) { toast(e.message, 'error'); return; }
    const rows = pre.rows, g = pre.guess, width = Math.max(0, ...rows.map((r) => r.length));
    if (!rows.length) { toast(`${pre.name} has nothing in it to import.`, 'error'); return; }
    const labels = new Set(this._rrows().map((r) => r.label));
    const name = (head, c) => (head !== null && rows[head]?.[c] ? `${String.fromCharCode(65 + (c % 26))}: ${rows[head][c]}` : `Column ${String.fromCharCode(65 + (c % 26))}`);
    const bare = (s) => { const m = /^\s*(?:#|no\.?|nr\.?|dim(?:ension)?|char(?:acteristic)?|balloon|item|feat(?:ure)?|bln|ch)\s*[#:.\-_ ]?\s*0*(\d{1,4}(?:\.\d{1,2}){0,2})\s*$/i.exec(s || '') || /^\s*0*(\d{1,4}(?:\.\d{1,2})?)\s*$/.exec(s || ''); return m ? m[1] : ''; };
    const parts = this.data.samples || [];
    const st = { head: g.head, key: g.key ?? 0, values: new Set(g.values || []), part: g.part ?? null, long: g.part !== null && g.part !== undefined,
      into: parts.find((p) => !Object.values(this.data.results || {}).some((r) => r[p.id]))?.id ?? '' }; // (the first part with nothing measured yet)
    const sel = (opts, now, change) => {
      const el = h('select', {}, ...opts.map(([v, label]) => h('option', { value: String(v), text: label, selected: String(v) === String(now) })));
      el.addEventListener('change', () => change(el.value));
      return el;
    };
    const body = h('div', { class: 'bl-imp' });
    let dlg = null;
    const matched = () => rows.filter((r, i) => i !== st.head && labels.has(bare(r[st.key]))).length;
    const draw = () => {
      const cols = Array.from({ length: width }, (_, c) => c);
      const headSel = sel([['', 'None'], ...rows.slice(0, 15).map((r, i) => [i, `Row ${i + 1}: ${r.filter(Boolean).slice(0, 4).join(', ').slice(0, 50)}`])], st.head ?? '', (v) => { st.head = v === '' ? null : +v; draw(); });
      const keySel = sel(cols.map((c) => [c, name(st.head, c)]), st.key, (v) => { st.key = +v; st.values.delete(st.key); draw(); });
      const shape = sel([['wide', 'A column for each part'], ['long', 'A row for each measurement, the part in a column']], st.long ? 'long' : 'wide', (v) => {
        st.long = v === 'long';
        if (st.long && st.part === null) st.part = cols.find((c) => c !== st.key && !st.values.has(c)) ?? null;
        draw();
      });
      const partSel = sel(cols.filter((c) => c !== st.key).map((c) => [c, name(st.head, c)]), st.part ?? '', (v) => { st.part = +v; draw(); });
      const valueSel = sel(cols.filter((c) => c !== st.key && c !== st.part).map((c) => [c, name(st.head, c)]), [...st.values][0] ?? '', (v) => { st.values = new Set([+v]); draw(); });
      const ticks = h('div', { class: 'bl-impcols' }, ...cols.filter((c) => c !== st.key).map((c) => {
        const box = h('input', { type: 'checkbox' });
        box.checked = st.values.has(c);
        box.addEventListener('change', () => { if (box.checked) st.values.add(c); else st.values.delete(c); draw(); });
        return h('label', { class: 'bl-tick' }, box, name(st.head, c));
      }));
      const row = (label, el) => h('label', { class: 'pe-frow' }, h('span', { text: label }), el);
      const one = !st.long && st.values.size === 1;
      const intoSel = sel([['', `A new part, named ${name(st.head, [...st.values][0] ?? 0).replace(/^[A-Z]+: /, '')}`], ...parts.map((p) => [p.id, `Part # ${p.name}`])], st.into,
        (v) => { st.into = v; });
      const look = (c) => (c === st.key ? 'k' : st.long && c === st.part ? 'p' : st.values.has(c) ? 'v' : '');
      const preview = h('div', { class: 'bl-impwrap' }, h('table', { class: 'bl-imptab' },
        h('tbody', {}, ...rows.slice(0, 14).map((r, i) => h('tr', { class: i === st.head ? 'head' : labels.has(bare(r[st.key])) ? 'hit' : '' },
          ...Array.from({ length: width }, (_, c) => h('td', { class: look(c), text: r[c] || '' })))))));
      const n = matched();
      body.replaceChildren(...[
        h('p', { class: 'bl-hint', text: `${pre.name}: ${pre.count} row${pre.count === 1 ? '' : 's'}. The rows are matched to the balloons by their numbers (5, #5, DIM 5, Char 2.1 all name balloon 5 or 2.1).` }),
        row('Heading row', headSel), row('Balloon numbers', keySel), row('Layout', shape),
        st.long ? row('Part (serial number)', partSel) : null,
        st.long ? row('Measurement', valueSel) : row('Measurements, a part each', ticks),
        one && parts.length ? row('Into part', intoSel) : null,
        preview,
        h('p', { class: `bl-hint${n ? '' : ' bl-warn'}`, text: n ? `${n} row${n === 1 ? '' : 's'} match a balloon on this print.` : 'No row matches a balloon: choose the column with the balloon numbers.' }),
        h('div', { class: 'pe-pop-foot' },
          h('span', { class: 'pv-grow' }),
          h('button', { class: 'btn', text: 'Cancel', onclick: () => dlg.close() }),
          h('button', { class: 'btn primary', text: 'Import', disabled: !n || !st.values.size || (st.long && st.part === null), onclick: go }))].filter(Boolean));
    };
    const go = async () => {
      dlg.close();
      const into = !st.long && st.values.size === 1 && st.into !== '' ? +st.into : null;
      const r = await this.run('balloon_import', { path, head: st.head, key: st.key, values: [...st.values], part: st.long ? st.part : null, into }, 'Importing…');
      const res = r?.result;
      if (!res) return;
      if (this.tab !== 'results') { this.tab = 'results'; this._head(); this._grid(); }
      const miss = res.unmatched_count ? ` ${res.unmatched_count} row${res.unmatched_count === 1 ? '' : 's'} named no balloon here (${res.unmatched.slice(0, 6).join(', ')}${res.unmatched_count > 6 ? '…' : ''}).` : '';
      toast(`${res.imported} result${res.imported === 1 ? '' : 's'} imported for ${res.parts} part${res.parts === 1 ? '' : 's'}.${miss}`, res.unmatched_count ? 'info' : 'ok', 7000);
    };
    dlg = modal('Import results', body, { width: 760 });
    draw();
  }

  // which parts of the lot to inspect, by the inspection frequency: a column for each
  sampling() {
    const row = (label, el) => h('label', { class: 'pe-frow' }, h('span', { text: label }), el);
    let saved = {};
    try { saved = JSON.parse(kept('bl:sample', '{}')) || {}; } catch { saved = {}; }
    const lot = h('input', { type: 'number', min: 1, step: 1, value: saved.lot || 25 });
    const how = h('select', {}, ...[['every', 'Every part'], ['ends', 'The first and the last'], ['thirds', 'The first, the middle one and the last'],
      ['one_in', '1 in N'], ['percent', 'A percentage of the lot']].map(([k, label]) => h('option', { value: k, text: label, selected: k === (saved.how || 'one_in') })));
    const n = h('input', { type: 'number', min: 1, step: 1, value: saved.n || 5 });
    const last = h('input', { type: 'checkbox' });
    last.checked = saved.last !== false;
    const nRow = row('N', n), lastRow = h('label', { class: 'bl-tick' }, last, 'And the last part too');
    const which = h('p', { class: 'bl-hint' });
    const pick = () => {
      const L = Math.max(parseInt(lot.value, 10) || 0, 0), k = how.value, N = +n.value;
      nRow.hidden = !['one_in', 'percent'].includes(k);
      nRow.firstChild.textContent = k === 'percent' ? 'Percent' : '1 in';
      lastRow.hidden = k !== 'one_in';
      if (L < 1) return [];
      let out = [];
      if (k === 'every') out = Array.from({ length: L }, (_, i) => i + 1);
      else if (k === 'ends') out = [1, L];
      else if (k === 'thirds') out = [1, Math.floor((L + 1) / 2), L];
      else if (k === 'one_in' && N >= 1) { for (let i = 1; i <= L; i += N) out.push(i); if (last.checked) out.push(L); }
      else if (k === 'percent' && N > 0 && N <= 100) {
        const c = Math.min(Math.max(Math.ceil((L * N) / 100), 1), L);
        out = c === 1 ? [1] : Array.from({ length: c }, (_, i) => Math.round(1 + (i * (L - 1)) / (c - 1)));
      }
      return [...new Set(out)].sort((a, b) => a - b);
    };
    const show = () => {
      const p = pick();
      which.textContent = p.length ? `${p.length} part${p.length === 1 ? '' : 's'} to inspect: ${p.map((x) => `#${x}`).join(', ')}${p.length > 50 ? '. The report holds up to 50: sample fewer.' : ''}` : 'Say how many parts are in the lot.';
    };
    for (const el of [lot, how, n, last]) { el.addEventListener('input', show); el.addEventListener('change', show); }
    let dlg = null;
    const ok = async () => {
      const p = pick();
      if (!p.length || p.length > 50) { show(); return; }
      dlg.close();
      const o = { lot: +lot.value, how: how.value, n: +n.value, last: last.checked };
      keep('bl:sample', JSON.stringify(o));
      const r = await this.run('balloon_sample', o);
      if (r?.result) toast(`${r.result.added} part${r.result.added === 1 ? '' : 's'} added to inspect. Double-click a part's heading for its serial number.`, 'ok', 5000);
    };
    dlg = modal('Sampling', h('div', { class: 'pe-fprops bl-props' },
      row('Parts in the lot', lot), row('Inspect', how), nRow, lastRow, which,
      h('p', { class: 'bl-hint', text: 'A part is added to the Results for each, named by its place in the lot (#1 is the first made), and the inspection sheet\'s Inspection Frequency says how they were chosen.' }),
      h('div', { class: 'pe-pop-foot' }, h('span', { class: 'pv-grow' }),
        h('button', { class: 'btn', text: 'Cancel', onclick: () => dlg.close() }),
        h('button', { class: 'btn primary', text: 'Add the parts', onclick: ok }))), { width: 440 });
    for (const el of [lot, n]) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') ok(); e.stopPropagation(); });
    show();
  }

  async newLot() {
    const parts = (this.data.samples || []).length;
    if (!await this.ed._confirm('New lot', `Take out the ${parts} part${parts === 1 ? '' : 's'} and everything they measured, to inspect another lot against the same balloons? Write the report first if this lot's is still needed.`, 'Start over')) return;
    this.run('balloon_results_clear', {});
  }

  _partMenu(e, p, th) {
    e.preventDefault();
    menu(null, [
      { label: 'Rename… (its serial number)', action: () => this._renamePart(p, th) },
      { sep: true },
      { label: 'Delete this part', action: () => this.removePart(p) },
    ], { at: { x: e.clientX, y: e.clientY } });
  }

  async removePart(p) {
    const has = Object.values(this.data.results || {}).filter((r) => r[p.id]).length;
    if (has && !await this.ed._confirm('Delete part', `Take out part ${p.name} with the ${has} result${has === 1 ? '' : 's'} measured on it?`, 'Delete')) return;
    this.run('balloon_part_delete', { id: p.id });
  }

  _renamePart(p, th) {
    const el = h('input', { class: 'bl-in', type: 'text', spellcheck: 'false', value: p.name, title: "The part's serial number, or what it's called" });
    th.replaceChildren(el);
    el.focus();
    el.select();
    let done = false;
    const finish = (save) => {
      if (done) return;
      done = true;
      const name = el.value.trim();
      if (save && name && name !== p.name) this.run('balloon_part_edit', { id: p.id, name }); else this._grid();
    };
    el.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') finish(true); else if (e.key === 'Escape') finish(false); });
    el.addEventListener('blur', () => finish(true));
    el.addEventListener('click', (e) => e.stopPropagation());
    el.addEventListener('dblclick', (e) => e.stopPropagation());
  }

  _resultsGrid() {
    const d = this.data, rows = this._rrows(), parts = d.samples || [], res = d.results || {};
    const top = this.wrap.scrollTop, left = this.wrap.scrollLeft, had = this.dock.contains(document.activeElement);
    const live = this._rediting; // (typing in a cell when the list is drawn again: taken up where it was)
    this._rediting = null;
    if (live) {
      if (live.el.isConnected && !this._rnext) this._rnext = { key: live.key, part: live.part, typed: live.el.value };
      live.drop();
    }
    this.head.querySelector('.bl-count')?.replaceWith(this._count());
    if (!d.chars.length || !parts.length) {
      this._rnext = null;
      this.wrap.replaceChildren(h('div', { class: 'bl-empty' },
        !d.chars.length ? 'No balloons on this print yet: results are measured against them.' : 'No part has been inspected yet. ',
        d.chars.length ? h('button', { class: 'btn', text: 'Add the first part', onclick: () => this.addPart() }) : null));
      return;
    }
    const lim = (c, k) => (c[k] == null ? '' : this._cell(c, k));
    const spc = parts.length >= 2; // (the spread is worth showing from two parts)
    const head = h('tr', {},
      h('th', { text: 'Dim #' }), h('th', { text: 'Characteristic' }), h('th', { text: 'Lower Limit' }), h('th', { text: 'Upper Limit' }),
      ...parts.map((p) => {
        const th = h('th', { class: 'bl-part', title: `Part ${p.name}\nDouble-click to rename it (its serial number); right-click for more` }, h('span', { text: `Part # ${p.name}` }));
        th.addEventListener('dblclick', () => this._renamePart(p, th));
        th.addEventListener('contextmenu', (e) => this._partMenu(e, p, th));
        return th;
      }),
      h('th', { text: 'Status', title: 'Fail: a result is outside its limits. Pass: every part is in.\nRecorded: every part has a result, with nothing to hold it against.' }),
      ...(spc ? [h('th', { text: 'Mean' }), h('th', { text: 'Range' }), h('th', { text: 'Cpk', title: 'Process capability: how far the mean is from the nearer limit, in three standard deviations.\n1.33 or more is the usual aim. Worked out from two or more measurements.' })] : []));
    const trs = rows.map((r) => {
      const c = r.c, mine = res[r.key] || {};
      const said = parts.map((p) => mine[p.id] || ''), ok = said.map((v) => judge(c, v)), filled = said.filter(Boolean).length;
      const status = ok.includes(false) ? 'Fail' : !filled ? '' : filled < parts.length ? `${filled} of ${parts.length}` : ok.every((x) => x === true) ? 'Pass' : 'Recorded';
      const what = `${c.desc ? `${c.desc}   ` : ''}${c.text || (c.desc ? '' : '(no requirement yet)')}`;
      const tr = h('tr', { 'data-id': c.id, 'data-key': r.key, class: this.sel === c.id ? 'on' : '' },
        h('td', {}, h('span', { class: 'bl-num', text: r.label })),
        h('td', { class: 'mono', title: what.length > 26 ? what : '' }, c.desc ? h('b', { class: 'bl-desc', text: c.desc }) : null, c.text || (c.desc ? '' : '(no requirement yet)')),
        h('td', { class: `mono r${c.tol === 'default' ? ' def' : ''}`, text: lim(c, 'lo') }), h('td', { class: `mono r${c.tol === 'default' ? ' def' : ''}`, text: lim(c, 'hi') }),
        ...parts.map((p, j) => {
          const td = h('td', { 'data-part': p.id, class: `bl-res mono${ok[j] === true ? ' ok' : ok[j] === false ? ' bad' : ''}`, text: said[j] });
          td.addEventListener('click', (e) => { e.stopPropagation(); this._editResult(r.key, p.id); });
          return td;
        }),
        h('td', { class: `bl-status${status === 'Fail' ? ' bad' : status === 'Pass' ? ' ok' : ''}`, text: status }),
        ...(spc ? this._statCells(c, said) : []));
      tr.addEventListener('click', () => this.select(c.id, { toPage: true }));
      tr.addEventListener('dblclick', () => this.edit(c));
      return tr;
    });
    const widths = [58, 260, 84, 84, ...parts.map(() => 104), 86, ...(spc ? [84, 76, 64] : [])];
    this.wrap.replaceChildren(h('table', { class: 'bl-grid bl-results', style: { width: `${widths.reduce((s, w) => s + w, 0)}px` } },
      h('colgroup', {}, ...widths.map((w) => h('col', { style: { width: `${w}px` } }))), h('thead', {}, head), h('tbody', {}, ...trs)));
    this.wrap.scrollTop = top;
    this.wrap.scrollLeft = left;
    if (had) this.wrap.focus({ preventScroll: true });
    const next = this._rnext;
    this._rnext = null;
    if (next) this._editResult(next.key, next.part, next.typed ?? null);
  }

  _statCells(c, said) {
    const s = stats(c, said);
    if (!s) return [h('td'), h('td'), h('td')];
    const f = (v) => this._fmt(v, Math.max((c.places || 0) + 1, 4), c.kind).replace(/\.$/, '');
    const tip = `${s.n} measurements\nMean ${f(s.mean)}   Min ${f(s.min)}   Max ${f(s.max)}\nRange ${f(s.range)}   Std dev ${f(s.sd)}\nCp ${s.cp == null ? '–' : s.cp.toFixed(2)}   Cpk ${s.cpk == null ? '–' : s.cpk.toFixed(2)}`;
    return [h('td', { class: 'mono r', text: f(s.mean), title: tip }), h('td', { class: 'mono r', text: f(s.range), title: tip }),
      h('td', { class: `mono r bl-cpk${s.cpk == null ? '' : s.cpk >= 1.33 ? ' ok' : ' bad'}`, text: s.cpk == null ? '–' : s.cpk.toFixed(2), title: tip })];
  }

  // a result is typed in: Enter goes on down the part's column (and on to the next part at its foot), Tab along the row
  _editResult(key, part, typed = null) {
    const td = this.wrap.querySelector(`tr[data-key="${key}"] td[data-part="${part}"]`), row = this._rrows().find((r) => r.key === key);
    if (!td || !row) return;
    if (this.sel !== row.c.id) this.select(row.c.id, { toPage: true }); // (its balloon comes into view: what to measure next)
    const was = (this.data.results[key] || {})[part] || '';
    const el = h('input', { class: 'bl-in', type: 'text', spellcheck: 'false', title: 'A measurement, or P / F (Pass, Fail) for what isn\'t measured' });
    el.value = typed ?? was;
    td.replaceChildren(el);
    td.classList.add('editing');
    td.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    el.focus({ preventScroll: true });
    if (typed === null) el.select();
    let done = false;
    this._rediting = { key, part, el, drop: () => { done = true; } };
    const finish = (save, next = null) => {
      if (done) return;
      done = true;
      if (this._rediting?.el === el) this._rediting = null;
      this._rnext = next;
      if (save && el.value.trim() !== was) this.run('balloon_result', { key, part, value: el.value }).then((r) => { if (!r) this._grid(); });
      else this._grid();
    };
    el.addEventListener('keydown', (e) => {
      e.stopPropagation();
      const go = (dy, dx) => { e.preventDefault(); finish(true, this._rstep(key, part, dy, dx)); };
      if (e.key === 'Enter') go(e.shiftKey ? -1 : 1, 0);
      else if (e.key === 'ArrowDown') go(1, 0);
      else if (e.key === 'ArrowUp') go(-1, 0);
      else if (e.key === 'Tab') go(0, e.shiftKey ? -1 : 1);
      else if (e.key === 'Escape') { e.preventDefault(); finish(false); this.wrap.focus({ preventScroll: true }); }
    });
    el.addEventListener('blur', () => finish(true));
    el.addEventListener('click', (e) => e.stopPropagation());
    el.addEventListener('dblclick', (e) => e.stopPropagation());
  }

  // the cell to go on to: down the part's column and on to the top of the next part, or along the row and on to the next row
  _rstep(key, part, dy, dx) {
    const rows = this._rrows(), parts = this.data.samples || [];
    let i = rows.findIndex((r) => r.key === key) + dy, j = parts.findIndex((p) => p.id === part) + dx;
    if (i >= rows.length) { i = 0; j++; } else if (i < 0) { i = rows.length - 1; j--; }
    if (j >= parts.length) { j = 0; i++; } else if (j < 0) { j = parts.length - 1; i--; }
    return rows[i] && parts[j] && (dy || dx) && !(dy && (j < 0 || j >= parts.length)) ? { key: rows[i].key, part: parts[j].id } : null;
  }

  _rowMenu(e, c) {
    e.preventDefault();
    this.select(c.id);
    menu(null, [
      { label: 'Edit…', action: () => this.edit(c) },
      { label: 'Add sub-balloon', action: () => this.addSub(c) },
      c.count > 1 && !c.mult ? { label: `Multiply (${c.count} rows)`, action: () => this.multiply([c.id], true) } : null,
      multiplied(c) ? { label: `Detach (${c.count} balloons)`, action: () => this.detach([c.id]) } : null,
      multiplied(c) ? { label: 'Reset to one row', action: () => this.multiply([c.id], false) } : null,
      { label: c.reviewed ? 'Mark as not reviewed' : 'Mark as reviewed', action: () => this.run('balloon_edit', { id: c.id, reviewed: !c.reviewed }) },
      { label: 'Add production issue…', action: () => this.editIssue(null) },
      { label: 'Tags', sub: () => (this.data.tags || []).map((t) => ({ label: t, check: (c.tags || []).includes(t), action: () => this.run('balloon_tag', { ids: [c.id], tag: t, on: !(c.tags || []).includes(t) }) })) },
      { sep: true },
      { label: 'Delete', kb: 'Del', action: () => this.remove(c.id) },
    ], { at: { x: e.clientX, y: e.clientY } });
  }

  // a characteristic's inspection tags, ticked on and off where it's shown (the list stays open to tick several)
  _tagMenu(c, anchor) {
    const on = new Set(c.tags || []);
    const items = (this.data.tags || []).map((t) => {
      const box = h('input', { type: 'checkbox' });
      box.checked = on.has(t);
      box.addEventListener('change', () => {
        if (box.checked) on.add(t); else on.delete(t);
        this.run('balloon_tag', { ids: [c.id], tag: t, on: box.checked });
      });
      return { el: h('label', { class: 'mi bl-tagi' }, box, h('span', { text: t })) };
    });
    menu(anchor, [{ head: `Tags for ${c.label}` }, ...items], { force: true });
  }

  // a cell is typed into in place: Enter goes on to the one below, Tab to the next one along, Esc leaves it as it was
  _editCell(c, col, typed = null, tr = null) {
    const td = (tr?.isConnected ? tr : this.wrap).querySelector(`${tr?.isConnected ? '' : `tr[data-id="${c.id}"] `}td[data-k="${col.k}"]`);
    if (!td || !col.edit) return;
    if (this.fixed) { this._fixedSay(); return; }
    if (this.sel !== c.id) this.select(c.id, { toRow: true });
    this.col = col.k;
    if (col.edit === 'tags') { this._tagMenu(c, td); return; }
    let el;
    if (col.edit === 'select') {
      const [opts, now] = col.k === 'tol' ? [TOL_TYPES, bare(c) ? c.tol : ''] : [Object.entries(this.data.labels), c.kind];
      el = h('select', { class: 'bl-in' }, ...opts.map(([k, label]) => h('option', { value: k, text: label, selected: k === now })));
    } else {
      el = h('input', { class: 'bl-in', type: 'text', spellcheck: 'false' });
      el.value = col.k === 'count' ? String(c.count || 1) : this._cell(c, col.k).replace(/°$/, '');
    }
    const was = el.value;
    if (typed !== null) el.value = typed;
    td.replaceChildren(el);
    td.classList.add('editing');
    td.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    el.focus({ preventScroll: true });
    if (typed === null) el.select?.();
    let done = false;
    this._editing = { id: c.id, k: col.k, el, drop: () => { done = true; } };
    const finish = (save, next = null) => {
      if (done) return;
      done = true;
      if (this._editing?.el === el) this._editing = null;
      const o = save && el.value !== was ? this._change(c, col.k, el.value) : null;
      this._next = next;
      if (o) this.run('balloon_edit', { id: c.id, ...o }).then((r) => { if (!r) this._grid(); });
      else this._grid();
    };
    el.addEventListener('keydown', (e) => {
      e.stopPropagation();
      if (e.key === 'Enter') { e.preventDefault(); finish(true, this._step(c, col, 1, 0)); }
      else if (e.key === 'Escape') { e.preventDefault(); finish(false); this.wrap.focus({ preventScroll: true }); }
      else if (e.key === 'Tab') { e.preventDefault(); finish(true, this._step(c, col, 0, e.shiftKey ? -1 : 1)); }
    });
    el.addEventListener('blur', () => finish(true));
    el.addEventListener('click', (e) => e.stopPropagation());
    el.addEventListener('dblclick', (e) => e.stopPropagation());
    if (col.edit === 'select') el.addEventListener('change', () => finish(true));
  }

  // the cell to go on to from this one: down a row, or along to the next one that's typed into
  _step(c, col, dy, dx) {
    const rows = this._shown(), i = rows.findIndex((x) => x.id === c.id);
    if (dy) return rows[i + dy] ? { id: rows[i + dy].id, k: col.k } : null;
    const cols = COLS.filter((x) => x.edit && x.edit !== 'tags'), j = cols.findIndex((x) => x.k === col.k) + dx;
    if (cols[j]) return { id: c.id, k: cols[j].k };
    return rows[i + dx] ? { id: rows[i + dx].id, k: cols[dx > 0 ? 0 : cols.length - 1].k } : null;
  }

  // the bar along the list's top edge is dragged to make it taller or shorter
  _gripDown(e) {
    if (e.button !== 0) return;
    e.preventDefault();
    const y0 = e.clientY, h0 = this.dock.offsetHeight, most = Math.max(this.v.el.clientHeight - 200, 110);
    this.grip.setPointerCapture(e.pointerId);
    const move = (m) => { this.dock.style.height = `${Math.min(Math.max(h0 + y0 - m.clientY, 110), most)}px`; };
    const up = () => {
      this.grip.removeEventListener('pointermove', move);
      this.grip.removeEventListener('pointerup', up);
      keep('bl:dock', String(this.dock.offsetHeight));
      this.v._resized();
    };
    this.grip.addEventListener('pointermove', move);
    this.grip.addEventListener('pointerup', up);
  }

  // ================================================================== Production Issues
  _ishown() {
    const f = this.ishow, all = this.data.issues || [];
    return all.filter((i) => (f === 'hidden' ? i.hidden && !i.delete : f === 'delete' ? !!i.delete : f === 'all' ? !i.hidden : f === 'resolved' ? !i.hidden && i.status === 'resolved' : unresolved(i)));
  }

  _issuesGrid() {
    const rows = this._ishown(), top = this.wrap.scrollTop;
    if (!rows.length) {
      const none = { open: 'No open issues.', all: 'No issues yet.', resolved: 'None resolved yet.', hidden: 'None hidden.', delete: 'None waiting to be deleted.' }[this.ishow];
      this.wrap.replaceChildren(h('div', { class: 'bl-empty', text: `${none} + Add issue starts one: on the selected balloon, or on none.` }));
      return;
    }
    const cols = [['#', 44], ['Balloon', 70], ['Title', 230], ['Tags', 200], ['Status', 210], ['Job', 80], ['Added', 190], ['Notes', 300]];
    const table = h('table', { class: 'bl-grid bl-issues', style: { width: `max(100%, ${cols.reduce((s, c) => s + c[1], 0)}px)` } },
      h('colgroup', {}, ...cols.map(([, w]) => h('col', { style: { width: `${w}px` } }))),
      h('thead', {}, h('tr', {}, ...cols.map(([t]) => h('th', { text: t })))),
      h('tbody', {}, ...rows.map((i) => {
        const tr = h('tr', { 'data-issue': i.id, class: `${i.status === 'resolved' ? 'done' : ''}${i.status === 'fixed' ? ' ready' : ''}${i.hidden ? ' hid' : ''}` },
          h('td', { text: `#${i.n}` }),
          h('td', {}, i.label ? h('span', { class: `bl-num${i.gone ? ' gone' : ''}`, text: i.label, title: i.gone ? 'That balloon has been removed' : '' }) : ''),
          h('td', { text: `${i.title || '(no title)'}${(() => { const k = (this.data.photos || []).filter((p) => p.on === 'issue' && p.of === i.id).length; return k ? `  · ${k} photo${k === 1 ? '' : 's'}` : ''; })()}` }),
          h('td', { text: (i.tags || []).join(', ') }),
          h('td', { class: 'bl-ist', text: issueStatus(i) }),
          h('td', { text: i.job || '' }),
          h('td', { text: `${when(i.at)}${i.by ? ` · ${i.by}` : ''}` }),
          h('td', { text: (i.notes || '').split('\n')[0], title: i.notes || '' }));
        tr.addEventListener('click', () => { if (i.char && !i.gone) this.select(i.char, { toPage: true }); });
        tr.addEventListener('dblclick', () => this.editIssue(i));
        tr.addEventListener('contextmenu', (e) => { e.preventDefault(); menu(null, this._issueActs(i, true), { at: { x: e.clientX, y: e.clientY } }); });
        return tr;
      })));
    this.wrap.replaceChildren(table);
    this.wrap.scrollTop = top;
    this.head.querySelector('.bl-count')?.replaceWith(this._count());
  }

  // a line of text asked for (null: cancelled)
  _ask(title, label, okText, hint = '', type = 'text') {
    return new Promise((done) => {
      const inp = h('input', { type, spellcheck: 'true', autocomplete: 'off' });
      let dlg = null, answered = false;
      const answer = (v) => { if (answered) return; answered = true; dlg.close(); done(v); };
      const ok = () => { const v = inp.value.trim(); if (v) answer(v); else toast(`${label} is needed.`, 'info'); };
      inp.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') ok(); });
      dlg = modal(title, h('div', { class: 'pe-fprops bl-props' },
        hint ? h('p', { class: 'bl-hint', text: hint }) : '',
        h('label', { class: 'pe-frow' }, h('span', { text: label }), inp),
        h('div', { class: 'pe-pop-foot' }, h('span', { class: 'pv-grow' }),
          h('button', { class: 'btn', text: 'Cancel', onclick: () => answer(null) }),
          h('button', { class: 'btn primary', text: okText, onclick: ok }))), { width: 520 });
      const close = dlg.close.bind(dlg);
      dlg.close = () => { close(); if (!answered) { answered = true; done(null); } };
      setTimeout(() => inp.focus(), 30);
    });
  }

  // what can be done with an issue now, as menu items (or buttons)
  _issueActs(i, withEdit = false) {
    const act = (a, o = {}) => this.run('balloon_issue_act', { id: i.id, act: a, ...o });
    const out = [];
    if (withEdit) out.push({ label: 'Open…', action: () => this.editIssue(i) });
    if (!i.hidden) {
      if (i.status === 'open') out.push({ label: 'Fixed, ready for lead', action: () => act('fixed') });
      if (i.status !== 'resolved') {
        out.push({ label: 'Resolve: machinist fix', action: () => this._lead(() => act('resolve', { route: 'machinist' })) });
        out.push({ label: 'Resolve: move to troubleshooting', action: () => this._lead(() => act('resolve', { route: 'troubleshooting' })) });
      }
      if (i.status !== 'open') out.push({ label: 'Reopen', action: () => this._lead(() => act('reopen')) });
      out.push({ sep: true });
      out.push({ label: 'Hide', action: () => act('hide') });
    } else if (!i.delete) out.push({ label: 'Show again', action: () => act('show') });
    if (i.delete) {
      out.push({ label: 'Switch to hide', action: () => act('keep') });
      out.push({ label: 'Delete permanently…', action: async () => {
        if (await this._asLead() && await this._confirmDelete(i)) this._lead(() => act('purge'));
      } });
    } else {
      out.push({ label: 'Delete…', action: async () => {
        const reason = await this._ask('Delete issue', 'Reason', 'Delete', "It's hidden now, and waits to be deleted for good. Switch to hide takes the request back.");
        if (reason) act('delete', { reason });
      } });
    }
    return out;
  }

  _confirmDelete(i) {
    return new Promise((done) => {
      let dlg = null, answered = false;
      const answer = (v) => { if (answered) return; answered = true; dlg.close(); done(v); };
      dlg = modal('Delete permanently', h('div', { class: 'pe-fprops bl-props' },
        h('p', { text: `Issue #${i.n}, "${i.title || 'no title'}", is taken out of the list for good (asked by ${i.delete?.who || 'someone'}: ${i.delete?.reason || ''}). Undo can still bring it back until the print is closed.` }),
        h('div', { class: 'pe-pop-foot' }, h('span', { class: 'pv-grow' }),
          h('button', { class: 'btn', text: 'Cancel', onclick: () => answer(false) }),
          h('button', { class: 'btn primary', text: 'Delete permanently', onclick: () => answer(true) }))), { width: 520 });
      const close = dlg.close.bind(dlg);
      dlg.close = () => { close(); if (!answered) { answered = true; done(false); } };
    });
  }

  // one issue (or a new one: i null), with what can be done with it and its history
  editIssue(i) {
    const d = this.data, sel = this.sel === null ? null : this.char(this.sel);
    const row = (label, el) => h('label', { class: 'pe-frow' }, h('span', { text: label }), el);
    const balloon = h('select', {}, h('option', { value: '', text: '(none)' }),
      ...d.chars.map((c) => h('option', { value: String(c.id), text: `${c.label}  ${c.text || ''}`.slice(0, 60), selected: i ? c.id === i.char : sel?.id === c.id })));
    const title = h('input', { type: 'text', spellcheck: 'true', value: i?.title || '', placeholder: 'What has to be dialed in' });
    const job = h('input', { type: 'text', spellcheck: 'false', value: i ? i.job || '' : (d.info?.job || '') });
    const notes = h('textarea', { rows: 4, spellcheck: 'true' });
    notes.value = i?.notes || '';
    const tagBoxes = (d.issueTags || []).map((t) => { const box = h('input', { type: 'checkbox' }); box.checked = (i?.tags || []).includes(t); return [t, box]; });
    let dlg = null;
    const fields = () => ({ char: balloon.value === '' ? null : Number(balloon.value), title: title.value.trim(), notes: notes.value.trim(), job: job.value.trim(),
      tags: tagBoxes.filter(([, b]) => b.checked).map(([t]) => t) });
    const save = async () => {
      const o = fields();
      if (!i && !o.title) { toast('Give the issue a title.', 'info'); return; }
      dlg.close();
      if (!i) {
        const r = await this.run('balloon_issue_add', o);
        if (r && this.tab !== 'issues') { this.tab = 'issues'; this._head(); this._grid(); }
        return;
      }
      const ch = {};
      if (o.char !== (i.char ?? null)) ch.char = o.char;
      for (const k of ['title', 'notes', 'job']) if (o[k] !== (i[k] || '')) ch[k] = o[k];
      if (o.tags.join('|') !== (i.tags || []).join('|')) ch.tags = o.tags;
      if (Object.keys(ch).length) await this.run('balloon_issue_edit', { id: i.id, ...ch });
    };
    const acts = i ? this._issueActs(i).filter((a) => !a.sep).map((a) => h('button', { class: 'btn', text: a.label, onclick: async () => { await save(); a.action(); } })) : [];
    dlg = modal(i ? `Production issue #${i.n}` : 'New production issue', h('div', { class: 'pe-fprops bl-props' },
      i ? h('div', { class: 'bl-sidline' }, h('span', { text: 'Status' }), h('b', { text: issueStatus(i) }), i.hidden && !i.delete ? h('span', { class: 'bl-hint', text: '(hidden)' }) : '') : '',
      row('Balloon', balloon), row('Title', title),
      h('div', { class: 'pe-frow' }, h('span', { text: 'Tags' }), h('div', { class: 'bl-tagbox' }, ...tagBoxes.map(([t, box]) => h('label', {}, box, t)))),
      row('Notes', notes), row('Job number', job),
      i ? h('div', { class: 'pe-frow' }, h('span', { text: 'Photos' }), photoStrip(this, 'issue', i.id)) : h('p', { class: 'bl-hint', text: 'Photos go on once the issue is added.' }),
      acts.length ? h('div', { class: 'bl-acts' }, ...acts) : '',
      i ? h('div', { class: 'bl-hist' }, h('div', { class: 'bl-histh' }, h('b', { text: 'History' })),
        h('div', { class: 'bl-log' }, ...i.history.slice().reverse().map((x) => h('div', { class: 'bl-logi' },
          h('div', { class: 'bl-logh', text: x.what }), h('div', { class: 'bl-logw', text: `${when(x.at)}${x.who ? ` · ${x.who}` : ''}` }))))) : '',
      h('div', { class: 'pe-pop-foot' },
        h('span', { class: 'pv-grow' }),
        h('button', { class: 'btn', text: 'Cancel', onclick: () => dlg.close() }),
        h('button', { class: 'btn primary', text: i ? 'Save' : 'Add issue', onclick: save }))), { width: 700 });
    for (const el of [title, job]) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') save(); e.stopPropagation(); });
    notes.addEventListener('keydown', (e) => e.stopPropagation());
    setTimeout(() => title.focus(), 30);
  }

  // ================================================================== one characteristic's dialog
  edit(c) {
    const d = this.data;
    const row = (label, el) => h('label', { class: 'pe-frow' }, h('span', { text: label }), el);
    const text = (v, ph = '') => h('input', { type: 'text', spellcheck: 'false', value: v ?? '', placeholder: ph });
    const num = (v) => text(v === null || v === undefined ? '' : this._fmt(v, c.places, c.kind).replace(/\.$/, ''));
    const n = text(c.label), req = text(c.text, 'As written on the print'), qty = text(c.count || 1);
    n.title = 'Its place in the list: 4 makes it the fourth. 4.2 puts it second under number 4, for one callout with several things to check.';
    const desc = text(c.desc, 'What it is: Overall Length, Cross Hole Diameter…'), gage = text(c.gage, 'Calipers, Height Gage, Gage Pin…'), note = text(c.note);
    const kind = h('select', {}, ...Object.entries(d.labels).map(([k, label]) => h('option', { value: k, text: label, selected: k === c.kind })));
    const type = h('select', { title: 'Reference and Basic sizes have no limits' }, ...TOL_TYPES.map(([k, label]) => h('option', { value: k, text: label, selected: k === (bare(c) ? c.tol : '') })));
    const f = { nominal: num(c.nominal), plus: num(c.plus), minus: num(c.minus), lo: num(c.lo), hi: num(c.hi) };
    const was = Object.fromEntries(Object.entries(f).map(([k, el]) => [k, el.value]));
    const tagBoxes = (d.tags || []).map((t) => { const box = h('input', { type: 'checkbox' }); box.checked = (c.tags || []).includes(t); return [t, box]; });
    let dlg = null;
    const ok = () => {
      dlg.close();
      const o = { id: c.id };
      if (kind.value !== c.kind) o.kind = kind.value;
      if (req.value.trim() !== (c.text || '')) o.text = req.value.trim();
      if ((parseInt(qty.value, 10) || 1) !== (c.count || 1)) o.count = parseInt(qty.value, 10) || 1;
      if (desc.value.trim() !== (c.desc || '')) o.desc = desc.value.trim();
      if (gage.value.trim() !== (c.gage || '')) o.gage = gage.value.trim();
      if (note.value.trim() !== (c.note || '')) o.note = note.value.trim();
      for (const [k, el] of Object.entries(f)) {
        if (el.value.trim() === was[k]) continue;
        const v = parseFloat(el.value.replace(',', '.'));
        o[k] = Number.isFinite(v) ? v : null;
        if (k === 'nominal' && Number.isFinite(v)) o.places = decimals(el.value.trim());
      }
      const to = n.value.trim().replace(',', '.');
      if (/^\d+(\.\d+)?$/.test(to) && to !== String(c.label)) o.n = to;
      if (type.value !== (bare(c) ? c.tol : '')) o.tol = type.value || 'auto';
      const tags = tagBoxes.filter(([, box]) => box.checked).map(([t]) => t);
      if (tags.join('|') !== (c.tags || []).join('|')) o.tags = tags;
      if (Object.keys(o).length > 1) this.run('balloon_edit', o);
    };
    dlg = modal(`Balloon ${c.label}`, h('div', { class: 'pe-fprops bl-props' },
      row('Number', n), row('Type', kind), row('Requirement', req), row('Description', desc), row('Gage', gage), row('Quantity', qty),
      h('div', { class: 'bl-nums' }, row('Nominal', f.nominal), row('+ Tolerance', f.plus), row('− Tolerance', f.minus), row('Lower limit', f.lo), row('Upper limit', f.hi),
        row('Tolerance type', type)),
      row('Note', note),
      h('div', { class: 'pe-frow' }, h('span', { text: 'Photos' }), photoStrip(this, 'char', c.id)),
      h('div', { class: 'pe-frow' }, h('span', { text: 'Tags' }), h('div', { class: 'bl-tagbox' }, ...tagBoxes.map(([t, box]) => h('label', {}, box, t)))),
      h('p', { class: 'bl-hint', text: 'Limits follow the nominal and its tolerance. With no tolerance here, they come from the title block\'s. Type the limits themselves for a size given as limits.' }),
      h('div', { class: 'pe-pop-foot' },
        h('button', { class: 'btn', text: 'Delete balloon', onclick: () => { dlg.close(); this.remove(c.id); } }),
        h('button', { class: 'btn', text: 'Add sub-balloon', title: `Another thing to check on the same callout: a new balloon under this number (${c.n}.1, ${c.n}.2…).\nChanges typed here are not kept.`, onclick: () => { dlg.close(); this.addSub(c); } }),
        h('span', { class: 'pv-grow' }),
        h('button', { class: 'btn', text: 'Cancel', onclick: () => dlg.close() }),
        h('button', { class: 'btn primary', text: 'OK', onclick: ok }))), { width: 440 });
    for (const el of [n, req, desc, gage, note, qty, ...Object.values(f)]) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') ok(); e.stopPropagation(); });
    setTimeout(() => { req.focus(); req.select(); }, 30);
  }
}
