// Acrobat's tools on the PDF page view: comments and markups, filling in forms and signing, editing the pages'
// own text and pictures, organizing pages, and redacting. The document's worker makes every change with MuPDF
// (kernel/pdfedit.py) and draws the pages again; this draws only what's being worked on over them: the selected
// comment's handles, the form's fields to type in, and shapes while they're dragged out.
// Places are in the page's points as shown (the page view's _pagePoint and _rectStyle), whatever the view's turn.
import { api } from './api.js';
import { h, toast, menu, modal, closeMenus, copyText } from './ui.js';
import { PRODUCT } from './consts.js';

const POINT = 96 / 72;
const I = (d) => `<svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
const ICON = {
  select: I('<path d="M5 3l10 6-4.5 1.3L13 15l-2 1-2.4-4.7L5 14z"/>'),
  note: I('<path d="M3.5 4h13v9.5H9L5.5 16.5v-3h-2z"/>'),
  text: I('<rect x="3" y="4" width="14" height="12" rx="1"/><path d="M7 8h6M10 8v5"/>'),
  typewriter: I('<path d="M5 5h10M10 5v10"/><path d="M3 17.5h14" stroke-dasharray="2 2"/>'),
  highlight: I('<path d="M3 17h14" stroke="#e8b800" stroke-width="3"/><path d="M6.5 13l5.5-9 3 2-5.5 9h-3z"/>'),
  underline: I('<path d="M6 3.5v5.5a4 4 0 008 0V3.5M4.5 16.5h11"/>'),
  strikeout: I('<path d="M3.5 10h13M13.5 6.2C13 4.7 11.7 3.8 10 3.8 8 3.8 6.5 4.9 6.5 6.6M6.5 13.6c.5 1.5 1.9 2.6 3.5 2.6 2 0 3.6-1.1 3.6-2.9"/>'),
  squiggly: I('<path d="M3 15l2-2 2 2 2-2 2 2 2-2 2 2 2-2M7 11V4h6"/>'),
  pen: I('<path d="M3 16c3-1 2.2-5 5-6s3 3 7.5-2"/><path d="M14 3.5l2.5 2.5"/>'),
  rect: I('<rect x="3.5" y="5" width="13" height="10" rx="1"/>'),
  ellipse: I('<ellipse cx="10" cy="10" rx="7" ry="5"/>'),
  cloud: I('<path d="M5.5 15.5a2.6 2.6 0 01-.3-5.2 3.4 3.4 0 016.5-1.6 2.9 2.9 0 013.9 2.7 2.1 2.1 0 01-.6 4.1z"/>'),
  line: I('<path d="M4 16L16 4"/>'),
  arrow: I('<path d="M4 16L16 4M9.5 4H16v6.5"/>'),
  stamp: I('<path d="M8 3h4v5.5l2.5 2V13h-9v-2.5l2.5-2zM4.5 16h11"/>'),
  check: I('<path d="M4 10.5l4 4 8-9"/>'),
  cross: I('<path d="M5 5l10 10M15 5L5 15"/>'),
  dot: '<svg viewBox="0 0 20 20" width="18" height="18"><circle cx="10" cy="10" r="3.5" fill="currentColor"/></svg>',
  date: I('<rect x="3.5" y="5" width="13" height="11" rx="1"/><path d="M3.5 8.5h13M7 3v3.5M13 3v3.5"/>'),
  sign: I('<path d="M3 13.5c2-6 4.2-8.2 5-6.2s-2 6.2.2 6.2 3-5 5-4 .8 3 3.8 2M3 17h14"/>'),
  flatten: I('<path d="M3 13l7 3.5 7-3.5M3 9.5L10 6l7 3.5-7 3.5z"/>'),
  editText: I('<path d="M3.5 5h8M7.5 5v11"/><path d="M11.5 16.5l.8-2.8 4.5-4.5 2 2-4.5 4.5z"/>'),
  addText: I('<path d="M3.5 5h9M8 5v11M14.5 12v6M11.5 15h6"/>'),
  editImage: I('<rect x="2.5" y="4" width="15" height="12" rx="1"/><path d="M2.5 13l4-4 3 3 2-2 6 6"/><circle cx="13" cy="8" r="1.3"/>'),
  addImage: I('<rect x="2.5" y="4" width="11" height="9" rx="1"/><path d="M2.5 11l3-3 3 3M15.5 11.5v6M12.5 14.5h6"/>'),
  crop: I('<path d="M6 2.5V14h11.5M2.5 6H14v11.5"/>'),
  redact: I('<rect x="3" y="7" width="14" height="6" fill="currentColor"/>'),
  redactText: I('<path d="M3 6.5h14"/><rect x="3" y="10" width="14" height="5" fill="currentColor"/>'),
  undo: I('<path d="M7.5 5L4 8.5 7.5 12"/><path d="M4 8.5h8a4 4 0 010 8H9"/>'),
  redo: I('<path d="M12.5 5L16 8.5 12.5 12"/><path d="M16 8.5H8a4 4 0 000 8h3"/>'),
  save: I('<path d="M4 3.5h10l2.5 2.5v10.5H4z"/><path d="M7 3.5v4h6v-4M7 16.5v-5h6v5"/>'),
  comments: I('<path d="M3 4h10v7H7.5L4.5 13.5V11H3zM14.5 7.5H17v7h-1.5v2.5L12.5 14.5H8.5V13"/>'),
};
ICON.trash = I('<path d="M4.5 6h11M8 6V4h4v2M6 6l.7 10h6.6L14 6M8.5 8.5v5M11.5 8.5v5"/>');
ICON.copy = I('<rect x="7" y="7" width="9" height="9" rx="1"/><path d="M13 7V4.5H4.5V13H7"/>');
// one key picks a comment tool, as in Acrobat (R turns the pages, so the rectangle is B for box)
const KEYS = { v: 'select', n: 'note', t: 'text', h: 'highlight', u: 'underline', k: 'strikeout', d: 'pen', b: 'rect', e: 'ellipse', c: 'cloud', l: 'line', a: 'arrow' };
const KEY_OF = Object.fromEntries(Object.entries(KEYS).map(([k, v]) => [v, k.toUpperCase()]));
const QUICK = ['#e02020', '#ffd400', '#2bb24c', '#2858cf', '#000000']; // the colors on a selected comment's own bar
const PLACE = { stamp: [160, 52], sign: [150, 50], initials: [60, 36], addImage: [150, 100] }; // placed by a click: points
const CLONABLE = new Set(['ink', 'line', 'polygon', 'polyline', 'highlight', 'underline', 'strikeout', 'squiggly', 'rect', 'ellipse', 'text', 'note']);
Object.assign(ICON, {
  fText: I('<rect x="2.5" y="6" width="15" height="8" rx="1"/><path d="M5.5 8.5v3M4.5 8.5h2M4.5 11.5h2"/>'),
  fMulti: I('<rect x="2.5" y="3.5" width="15" height="13" rx="1"/><path d="M5 7h10M5 10h10M5 13h6"/>'),
  fCheck: I('<rect x="4" y="4" width="12" height="12" rx="1.5"/><path d="M7 10.2l2.2 2.3L13.2 7.6"/>'),
  fCombo: I('<rect x="2.5" y="6" width="15" height="8" rx="1"/><path d="M12 6v8M13.6 9.3l1.2 1.4 1.2-1.4"/>'),
  fProps: I('<path d="M4 6h7M14 6h2M4 10h2M9 10h7M4 14h9M16 14h0"/><circle cx="12.5" cy="6" r="1.5"/><circle cx="7.5" cy="10" r="1.5"/><circle cx="14.5" cy="14" r="1.5"/>'),
  fDelete: I('<path d="M4.5 6h11M8 6V4.5h4V6M6 6l.7 9.5h6.6L14 6M8.5 8.5v5M11.5 8.5v5"/>'),
});
const SETS = [
  { id: 'comment', label: 'Comment', tools: ['select', 'note', 'text', 'highlight', 'underline', 'strikeout', 'squiggly', '|', 'pen', 'rect', 'ellipse', 'cloud', 'line', 'arrow', 'stamp'] },
  { id: 'fill', label: 'Fill & Sign', tools: ['select', 'typewriter', 'check', 'cross', 'dot', 'date', '|', 'sign', 'initials', '|', 'flatten'] },
  { id: 'form', label: 'Prepare Form', tools: ['select', 'formAuto', '|', 'fText', 'fMulti', 'fCheck', 'fCombo', '|', 'fProps', 'fDelete', 'formClear'] },
  { id: 'edit', label: 'Edit', tools: ['select', 'editText', 'addText', 'editImage', 'addImage'] },
  { id: 'pages', label: 'Pages', tools: [] },
  { id: 'redact', label: 'Redact', tools: ['select', 'redactText', 'redact', 'redactFind', 'strikeText', '|', 'redactApply', 'scrub'] },
];
const TOOLS = {
  select: { label: 'Select', tip: 'Drag across text to select it (Ctrl+C copies). Click a comment to select it: drag it to move it, its handles to size it, double-click to edit it. Drag bare paper to pan.' },
  note: { label: 'Sticky note', tip: 'Click to add a note' },
  text: { label: 'Text box', tip: 'Drag (or click) to add a text box' },
  typewriter: { label: 'Add text', tip: 'Click and type: fill in a form that has no fields', icon: 'typewriter' },
  highlight: { label: 'Highlight', tip: 'Drag across text to highlight it', markup: true },
  underline: { label: 'Underline', tip: 'Drag across text to underline it', markup: true },
  strikeout: { label: 'Strikethrough', tip: 'Drag across text to strike it out', markup: true },
  squiggly: { label: 'Squiggly underline', tip: 'Drag across text to mark it', markup: true },
  pen: { label: 'Draw', tip: 'Draw freehand' },
  rect: { label: 'Rectangle', tip: 'Drag to draw a rectangle' },
  ellipse: { label: 'Oval', tip: 'Drag to draw an oval' },
  cloud: { label: 'Cloud', tip: 'Drag to draw a revision cloud' },
  line: { label: 'Line', tip: 'Drag to draw a line' },
  arrow: { label: 'Arrow', tip: 'Drag to draw an arrow' },
  stamp: { label: 'Stamp', tip: 'Choose a stamp, then click or drag where it goes', menu: true },
  check: { label: 'Check mark', tip: 'Click to add a check mark' },
  cross: { label: 'Cross', tip: 'Click to add a cross' },
  dot: { label: 'Dot', tip: 'Click to add a dot' },
  date: { label: 'Date', tip: "Click to add today's date" },
  sign: { label: 'Sign', tip: 'Add your signature: draw or type it once, then click where it goes', menu: true },
  initials: { label: 'Initials', tip: 'Add your initials', icon: 'sign', menu: true },
  flatten: { label: 'Flatten', tip: 'Make comments, signatures and filled-in fields part of the pages, so nobody can change them', action: true },
  editText: { label: 'Edit text', tip: "Click a line of the page's own text to change it" },
  addText: { label: 'Add text', tip: 'Click to put new words into the page itself (not a comment)' },
  editImage: { label: 'Edit pictures', tip: 'Click a picture to select it: drag to move it, its handles to size it, Delete to remove it' },
  addImage: { label: 'Add picture', tip: 'Choose a picture, then click or drag where it goes' },
  formAuto: { label: 'Detect fields', tip: 'Make this fillable: find the blanks (lines, boxes, table cells, check boxes) and put a field on each', action: true, text: true, icon: 'fText' },
  fText: { label: 'Text field', tip: 'Drag (or click) where a line of typing goes' },
  fMulti: { label: 'Text box of several lines', tip: 'Drag (or click) where several lines of typing go' },
  fCheck: { label: 'Check box', tip: 'Click where a box to tick goes' },
  fCombo: { label: 'Drop-down list', tip: 'Drag (or click) where a list of choices goes, then double-click it to set the choices' },
  fProps: { label: 'Field properties', tip: "The selected field's name, tip, text size, choices, required or read-only (or double-click the field)", action: true },
  fDelete: { label: 'Delete field', tip: 'Take out the selected field (Delete)', action: true },
  formClear: { label: 'Remove all fields', tip: 'Take every field out of the document', action: true, text: true },
  crop: { label: 'Crop', tip: 'Drag the part of the page to keep' },
  redactText: { label: 'Mark text', tip: 'Drag across text to mark it for redaction' },
  redact: { label: 'Mark area', tip: 'Drag a box to mark it for redaction' },
  redactFind: { label: 'Mark found', tip: 'Mark every place the Find box finds', action: true, icon: 'redactText' },
  strikeText: { label: 'Strike through', tip: 'Drag across text to put a single line through it (the words stay readable)', icon: 'strikeout' },
  redactApply: { label: 'Apply', tip: 'Take everything marked out of the pages for good, and make strike-throughs part of the page', action: true, text: true },
  scrub: { label: 'Remove hidden info', tip: "Take out the document's details, attachments, scripts, hidden text and comments", action: true, text: true },
};
// tools that place one thing, then hand back to Select (the rest stay on, for marking up a run of things)
const ONE_OFF = new Set(['note', 'text', 'rect', 'ellipse', 'cloud', 'line', 'arrow', 'stamp', 'fText', 'fMulti', 'fCheck', 'fCombo']);
const FIELD_TOOLS = { fText: ['text', 150, 18], fMulti: ['text', 220, 60], fCheck: ['checkbox', 12, 12], fCombo: ['combo', 120, 18] };
const segDist = (p, a, b) => { // from a point to a line segment
  const dx = b[0] - a[0], dy = b[1] - a[1], L = dx * dx + dy * dy;
  const t = L ? clamp(((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L, 0, 1) : 0;
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
};
const COLORS = ['#e02020', '#f08a00', '#ffd400', '#2bb24c', '#1f9bd7', '#2858cf', '#8b3fd9', '#e84d9c', '#000000', '#6b7280', '#ffffff'];
const KIND_LABEL = { note: 'Note', text: 'Text', highlight: 'Highlight', underline: 'Underline', strikeout: 'Strikethrough',
  squiggly: 'Squiggly', rect: 'Rectangle', ellipse: 'Oval', line: 'Line', ink: 'Drawing', polygon: 'Polygon', polyline: 'Polyline',
  stamp: 'Stamp', redact: 'Redaction', caret: 'Insert', file: 'Attachment' };
const STAMP_LABEL = { Approved: 'Approved', NotApproved: 'Not Approved', Draft: 'Draft', Final: 'Final', ForComment: 'For Comment',
  Confidential: 'Confidential', Experimental: 'Experimental', AsIs: 'As Is', Expired: 'Expired', Departmental: 'Departmental',
  ForPublicRelease: 'For Public Release', NotForPublicRelease: 'Not For Public Release', Sold: 'Sold', TopSecret: 'Top Secret' };
const DEFAULT_STYLE = { colors: { highlight: '#ffd400', underline: '#2bb24c', strikeout: '#e02020', squiggly: '#e02020', note: '#ffd400',
  text: '#000000', typewriter: '#000000', pen: '#e02020', rect: '#e02020', ellipse: '#e02020', cloud: '#e02020', line: '#e02020',
  arrow: '#e02020', check: '#000000', cross: '#000000', dot: '#000000', date: '#000000', addText: '#000000' },
width: 1.5, opacity: 1, fontsize: 12 };
const CHECK = [[0.1, 0.55], [0.4, 0.85], [0.9, 0.15]];
const CROSS = [[[0.15, 0.15], [0.85, 0.85]], [[0.85, 0.15], [0.15, 0.85]]];
const clamp = (x, a, b) => Math.min(Math.max(x, a), b);
const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
const keep = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage off */ } };
const rectOf = (a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1])];
const inRect = (r, [x, y], pad = 0) => x >= r[0] - pad && x <= r[0] + r[2] + pad && y >= r[1] - pad && y <= r[1] + r[3] + pad;

function pdfDate(s) {
  const m = /D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?/.exec(s || '');
  if (!m) return '';
  const d = new Date(+m[1], (+m[2] || 1) - 1, +m[3] || 1, +m[4] || 0, +m[5] || 0);
  return d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

export class PdfEditor {
  constructor(view) {
    this.v = view;
    this.doc = null;
    this.set = load('pe:set', 'comment');
    this.tool = 'select';
    this.style = { ...DEFAULT_STYLE, ...load('pe:style', {}), colors: { ...DEFAULT_STYLE.colors, ...(load('pe:style', {}).colors || {}) } };
    this.sel = null; // {type: 'annot' | 'image', page, id, rect, a}
    this.annots = [];
    this.fields = [];
    this.images = {};
    this.words = {}; // page -> word boxes as shown, for the Select tool (null while asked for)
    this.fieldEls = new Map();
    this.picked = new Set(); // thumbnails picked for the Pages tools
    this.row = h('div', { class: 'pe-row', hidden: true });
    view.el.insertBefore(this.row, view.body);
    this.panel = h('div', { class: 'pe-panel', hidden: true });
    view.body.append(this.panel);
    this.showPanel = load('pe:panel', false);
    view.scroller.addEventListener('dblclick', (e) => this._dbl(e));
    view.scroller.addEventListener('pointermove', (e) => this._hover(e));
    view.scroller.addEventListener('contextmenu', (e) => this._context(e));
    view.scroller.addEventListener('scroll', () => this._prefetch());
    view.scroller.addEventListener('pointerleave', () => { this._follow?.remove(); this._setHover(null); });
    document.addEventListener('keyup', (e) => { if (e.key === ' ') this._hand(false); });
    window.addEventListener('blur', () => this._hand(false));
    const show = view._showSelection.bind(view); // selected text gets its bar of things to do with it
    view._showSelection = () => { show(); this._textBar(); };
  }

  get editable() { return !!this.doc && !this.doc.meta.pdf.picture; }

  // ================================================================== opening and closing
  async open(doc) {
    this.doc = doc;
    this.sel = null;
    this.annots = [];
    this.fields = [];
    this.images = {};
    this.words = {};
    this._wordsAsked = {};
    this.fieldEls.clear();
    this.picked.clear();
    this.tool = 'select';
    this.row.hidden = !this.editable;
    this.panel.hidden = !this.editable || !this.showPanel;
    if (!this.editable) return;
    this._bar();
    this._ready = (async () => {
      try {
        this.state = await this._ask('state');
        this.doc.pdfDirty = this.state.dirty;
        await this.refresh();
        this._bar();
      } catch (e) { console.warn('PDF editor:', e.message); }
    })();
    await this._ready;
  }

  close() {
    this._endInline(false);
    this._pop?.remove();
    this.doc = null;
    this.sel = null;
    this.row.hidden = true;
    this.panel.hidden = true;
    this.panel.replaceChildren();
    this.fieldEls.clear();
  }

  // the view was laid out again (zoom, resize, new pages): what's drawn over the pages follows
  layout() {
    if (!this.editable) return;
    this._drawFields();
    this._drawSel();
    if (this.inline) this._placeInline();
  }

  // ================================================================== talking to the worker
  _ask(op, args = {}) { return api.pdfEdit(this.doc.id, op, args); }

  // edits go to the worker one at a time, in the order they're made (a save waits for the edits before it)
  run(op, args = {}, busyText) {
    const go = (this._q || Promise.resolve()).then(() => this._run(op, args, busyText));
    this._q = go.catch(() => {});
    return go;
  }

  async _run(op, args = {}, busyText) {
    if (!this.doc) return null;
    const doc = this.doc;
    const slow = busyText ? setTimeout(() => toast(busyText, 'info', 4000), 600) : null;
    try {
      const r = await this._ask(op, args);
      if (this.doc === doc && r?.state) await this._applied(r);
      // as Acrobat: a comment placed one at a time is left selected, back on the Select tool, to move or change
      if (this.doc === doc && op === 'annot_add' && r?.result?.id && ONE_OFF.has(this.tool) && this.locked !== this.tool) {
        const a = this.annots.find((x) => x.id === r.result.id && x.page === args.page);
        this.setTool('select');
        if (a) this.select({ type: 'annot', page: a.page, id: a.id, rect: a.rect, a });
      }
      return r;
    } catch (e) {
      toast(e.message, 'error');
      return null;
    } finally { clearTimeout(slow); }
  }

  async _applied(r) {
    this.state = r.state;
    this.doc.pdfDirty = r.state.dirty;
    this.images = {};
    if (r.text || r.structure) { this.words = {}; this._wordsAsked = {}; }
    if (r.structure) { this.picked.clear(); this.v.reloadPages(r.pages); }
    else if (r.changed === null) this.v.redraw(null);
    else if (r.changed?.length) this.v.redraw(r.changed);
    if (r.text && !r.structure) { this.v.hints.close(); this.v.hints.open(this.doc); this.v._clearFind(); }
    await this.refresh();
    this._bar();
    this.v.balloons?.changed(r); // the inspection list is in the PDF too: an edit or an undo may have changed it
    this.v.app?.shell?.renderDocTabs();
  }

  async refresh() {
    if (!this.editable) return;
    const doc = this.doc;
    const [annots, fields] = await Promise.all([this._ask('annots'), this.state?.fields ? this._ask('fields') : []]);
    if (this.doc !== doc) return;
    this.annots = annots;
    this.fields = fields;
    if (this.sel?.type === 'annot') {
      const a = annots.find((x) => x.id === this.sel.id && x.page === this.sel.page);
      this.sel = a ? { type: 'annot', page: a.page, id: a.id, rect: a.rect, a } : null;
      this._fetchImg(this.sel);
    }
    this._drawFields();
    this._drawSel();
    this._prefetch();
    if (this.showPanel) this._renderPanel();
  }

  // ================================================================== the toolbar
  _btn(id, opts = {}) {
    const t = TOOLS[id] || {};
    const lockable = !opts.run && ONE_OFF.has(id) && id !== 'stamp';
    const b = h('button', { class: `pv-btn pe-tool${this.tool === id ? ' on' : ''}${this.locked === id && this.tool === id ? ' lock' : ''}${opts.cls ? ` ${opts.cls}` : ''}`,
      title: `${opts.label || t.label}${!opts.run && KEY_OF[id] ? ` (${KEY_OF[id]})` : ''}${t.tip ? `\n${t.tip}` : ''}${lockable ? '\nDouble-click to keep it on for several.' : ''}`,
      html: `${ICON[opts.icon || t.icon || id] || ''}${opts.text || t.text ? `<span>${opts.label || t.label}</span>` : ''}` });
    b.addEventListener('click', () => (opts.run ? opts.run(b) : this._pick(id, b)));
    if (lockable) b.addEventListener('dblclick', () => { this.locked = id; this.setTool(id, null, true); });
    return b;
  }

  _bar() {
    if (!this.editable) return;
    const tabs = h('div', { class: 'pe-sets' }, ...SETS.map((s) => h('button', { class: `pe-set${s.id === this.set ? ' on' : ''}`, text: s.label,
      onclick: () => { this.set = s.id; this.fsel = null; keep('pe:set', s.id); this.setTool('select'); if (s.id === 'pages') this._sideOn(); } })));
    const set = SETS.find((s) => s.id === this.set) || SETS[0];
    const tools = set.id === 'pages' ? this._pagesTools() : set.tools.map((id) => (id === '|' ? h('span', { class: 'pv-sep' }) : this._btn(id)));
    if (set.id === 'redact') { // what a redaction leaves behind
      const fill = load('pe:redact', 'black');
      const b = h('button', { class: 'pv-btn', title: 'What an applied redaction leaves on the page', text: `Fill: ${fill === 'white' ? 'White' : 'Black'} ▾` });
      b.addEventListener('click', () => menu(b, [['black', 'Black: shows that something was removed'], ['white', 'White: leaves blank paper']].map(([c, label]) => (
        { label, check: c === fill, action: () => { keep('pe:redact', c); this._bar(); } }))));
      tools.splice(5, 0, b, h('span', { class: 'pv-sep' }));
    }
    const st = this.state || {};
    const right = [
      ...this._props(),
      h('span', { class: 'pv-grow' }),
      this._btn('comments', { label: `Comments${this.annots.length ? ` (${this._top().length})` : ''}`, text: true, cls: this.showPanel ? 'on' : '', run: () => this.togglePanel() }),
      h('span', { class: 'pv-sep' }),
      this._btn('undo', { label: 'Undo (Ctrl+Z)', run: () => this.undo() }),
      this._btn('redo', { label: 'Redo (Ctrl+Y)', run: () => this.redo() }),
      this._btn('save', { label: st.dirty ? 'Save (Ctrl+S)' : 'Saved', text: true, cls: st.dirty ? 'pe-dirty' : '', run: () => this.save() }),
      h('button', { class: 'pv-btn', text: 'Save As…', title: 'Save a copy somewhere else (Ctrl+Shift+S): it becomes the open document', onclick: () => this.saveAs() }),
    ];
    this.row.replaceChildren(tabs, h('span', { class: 'pv-sep' }), ...tools, ...right);
    const [u, r] = this.row.querySelectorAll('.pe-tool[title^="Undo"], .pe-tool[title^="Redo"]');
    if (u) u.disabled = !st.undo;
    if (r) r.disabled = !st.redo;
  }

  // color, line width, opacity and text size: for the selected comment, or the next one drawn
  _props() {
    const sel = this.sel?.type === 'annot' ? this.sel.a : null;
    const kind = sel ? (sel.kind === 'ink' ? 'pen' : sel.kind === 'line' && sel.arrow ? 'arrow' : sel.kind) : this.tool;
    const colorable = sel ? !['stamp', 'redact', 'file'].includes(sel.kind) : DEFAULT_STYLE.colors[this.tool] !== undefined;
    if (!colorable) return [];
    const color = sel ? (sel.kind === 'text' ? sel.textColor : sel.color) || '#000000' : this.style.colors[kind] || '#000000';
    const out = [h('span', { class: 'pv-sep' })];
    const sw = h('button', { class: 'pv-btn pe-swatch', title: 'Color' }, h('span', { style: { background: color } }));
    sw.addEventListener('click', () => {
      const grid = h('div', { class: 'pe-colors' }, ...COLORS.map((c) => h('button', { class: `pe-c${c === color ? ' on' : ''}`, style: { background: c }, title: c,
        onclick: () => { closeMenus(); this._setStyle(sel, kind, sel?.kind === 'text' ? { textColor: c } : { color: c }); } })));
      menu(sw, [{ el: grid }]);
    });
    out.push(sw);
    const lined = sel ? ['rect', 'ellipse', 'line', 'ink', 'polygon', 'polyline'].includes(sel.kind) : ['pen', 'rect', 'ellipse', 'cloud', 'line', 'arrow'].includes(this.tool);
    if (lined) {
      const w = sel ? sel.width : this.style.width;
      const b = h('button', { class: 'pv-btn', title: 'Line width', text: `${w > 0 ? w : 1} pt ▾` });
      b.addEventListener('click', () => menu(b, [0.5, 1, 1.5, 2, 3, 4, 6, 8].map((x) => ({ label: `${x} pt`, check: x === w, action: () => this._setStyle(sel, kind, { width: x }) }))));
      out.push(b);
    }
    const sized = sel ? sel.kind === 'text' : ['text', 'typewriter', 'date', 'addText'].includes(this.tool);
    if (sized) {
      const fs = sel ? sel.fontsize : this.style.fontsize;
      const b = h('button', { class: 'pv-btn', title: 'Text size', text: `${fs} pt ▾` });
      b.addEventListener('click', () => menu(b, [8, 9, 10, 11, 12, 14, 16, 18, 24, 32, 48].map((x) => ({ label: `${x} pt`, check: x === fs, action: () => this._setStyle(sel, kind, { fontsize: x }) }))));
      out.push(b);
    }
    if (sel || !['typewriter', 'date', 'addText', 'check', 'cross', 'dot'].includes(this.tool)) {
      const op = sel ? sel.opacity : this.style.opacity;
      const b = h('button', { class: 'pv-btn', title: 'Opacity', text: `${Math.round(op * 100)}% ▾` });
      b.addEventListener('click', () => menu(b, [1, 0.8, 0.6, 0.4, 0.2].map((x) => ({ label: `${x * 100}%`, check: Math.abs(x - op) < 0.01, action: () => this._setStyle(sel, kind, { opacity: x }) }))));
      out.push(b);
    }
    return out;
  }

  _setStyle(sel, kind, change) {
    if (sel) { this.run('annot_set', { page: sel.page, id: sel.id, ...change }); return; }
    if (change.color || change.textColor) this.style.colors[kind] = change.color || change.textColor;
    if (change.width) this.style.width = change.width;
    if (change.opacity) this.style.opacity = change.opacity;
    if (change.fontsize) this.style.fontsize = change.fontsize;
    keep('pe:style', this.style);
    this._bar();
  }

  // a tool button: pick the tool, or do what it does
  async _pick(id, b) {
    const t = TOOLS[id];
    if (id === 'stamp') { this._stampMenu(b); return; }
    if (id === 'sign' || id === 'initials') { this._signMenu(b, id); return; }
    if (id === 'flatten') { this._flatten(); return; }
    if (id === 'redactFind') { this._redactFound(); return; }
    if (id === 'redactApply') { this._redactApply(); return; }
    if (id === 'scrub') { this._scrub(); return; }
    if (id === 'formAuto') { this._formAuto(b); return; }
    if (id === 'formClear') { this._formClear(); return; }
    if (id === 'fProps' || id === 'fDelete') {
      const f = this._fselField();
      if (!f) { toast('Click a field first.', 'info'); return; }
      if (id === 'fProps') this._fieldProps(f); else this._fieldDelete();
      return;
    }
    if (id === 'addImage') {
      const r = await api.openFiles('image', 'Choose a picture to add').catch((e) => { toast(e.message, 'error'); return null; });
      if (!r?.files?.length) return;
      this.setTool('addImage', { image: r.files[0].data });
      return;
    }
    if (t?.markup && this.v.selection?.rects?.length) { // text already selected: mark it at once
      const s = this.v.selection;
      await this.run('annot_add', { page: s.page, kind: id, rects: s.rects, text: s.text, color: this.style.colors[id], opacity: this.style.opacity });
      this.v.selection = null;
      this.v._showSelection();
      return;
    }
    this.setTool(this.tool === id && id !== 'select' ? 'select' : id);
  }

  setTool(id, payload = null, lock = false) {
    this._endInline(true);
    if (!lock) this.locked = null;
    this._follow?.remove();
    this._follow = null;
    this._setHover(null);
    this.tool = id;
    this.payload = payload;
    this._drawFields(); // (fields are boxes to arrange under Prepare Form, and to type into everywhere else)
    if (id !== 'select') this.select(null);
    this.v.scroller.classList.toggle('pe-drawing', id !== 'select');
    this.v.scroller.dataset.tool = id;
    this._bar();
    this._textBar();
    this.v.app?.status?.();
    if (id === 'editImage') this._loadImages();
  }

  // what the status bar says while a tool is on
  hint() {
    if (!this.editable || this.tool === 'select') return null;
    const t = TOOLS[this.tool];
    return t ? `<b>${t.label}</b> · ${t.tip}${this.locked === this.tool ? ' · stays on' : ''} · Esc when done · hold Space to pan` : null;
  }

  _hand(on) {
    if (!!this.space === on) return;
    this.space = on;
    this.v.scroller.classList.toggle('pe-hand', on);
  }

  async _clone(page, id, to) {
    const r = await this.run('annot_clone', { page, id, to });
    const a = r?.result && this.annots.find((x) => x.id === r.result.id && x.page === r.result.page);
    if (!a) return;
    if (this.clip) this.clip = { doc: this.doc.id, page: a.page, id: a.id }; // the next paste steps on from this one
    this.setTool('select');
    this.select({ type: 'annot', page: a.page, id: a.id, rect: a.rect, a });
  }

  // ================================================================== keys
  key(e) {
    if (!this.editable) return false;
    const ctrl = e.ctrlKey || e.metaKey, lk = e.key.toLowerCase();
    const done = () => { e.preventDefault(); e.stopPropagation(); return true; };
    if (ctrl && lk === 's') { if (e.shiftKey) this.saveAs(); else this.save(); return done(); }
    const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '') || document.activeElement?.isContentEditable;
    if (typing) return false;
    if (ctrl && lk === 'a') { this._selectPage(this.v.current || 0); return done(); }
    if (e.key === ' ') { this._hand(true); return done(); } // held: drag pans, whatever tool is on
    const comment = this.sel?.type === 'annot' ? this.sel : null;
    if (ctrl && lk === 'c' && comment && !this.v.selection?.text) {
      if (!CLONABLE.has(comment.a.kind)) { toast("That kind of comment can't be copied: place a new one instead.", 'info'); return done(); }
      this.clip = { doc: this.doc.id, page: comment.page, id: comment.id };
      toast('Copied. Ctrl+V pastes it on the page in view.', 'info', 1800);
      return done();
    }
    if (ctrl && lk === 'v' && this.clip?.doc === this.doc.id) { this._clone(this.clip.page, this.clip.id, this.v.current || 0); return done(); }
    if (ctrl && lk === 'd' && comment) { this._clone(comment.page, comment.id, comment.page); return done(); }
    if (!ctrl && !e.altKey && e.key.length === 1 && KEYS[lk] && !this.v.balloons?.on) { // (in Ballooning mode this toolbar is put away)
      if (this.set !== 'comment') { this.set = 'comment'; keep('pe:set', 'comment'); }
      if (KEYS[lk] === 'select') this.setTool('select'); else this._pick(KEYS[lk]);
      return done();
    }
    if (ctrl && lk === 'z' && !e.shiftKey) { this.undo(); return done(); }
    if (ctrl && (lk === 'y' || (lk === 'z' && e.shiftKey))) { this.redo(); return done(); }
    if ((e.key === 'Delete' || e.key === 'Backspace') && this.set === 'form' && this._fselField()) { this._fieldDelete(); return done(); }
    if ((e.key === 'Delete' || e.key === 'Backspace') && this.sel) { this.deleteSel(); return done(); }
    if ((e.key === 'Delete') && this.set === 'pages' && this.picked.size) { this._pagesDelete(); return done(); }
    if (e.key === 'Escape') {
      if (this.tool !== 'select') { this.setTool('select'); return done(); }
      if (this.sel) { this.select(null); return done(); }
      if (this.fsel) { this.fsel = null; this._drawFields(); return done(); }
      if (this.v.selection) { this.v.selection = null; this.v._showSelection(); return done(); }
      return false;
    }
    if (this.sel && e.key.startsWith('Arrow') && !ctrl) { // nudge the selected comment or picture: moved at once, saved once it stops
      const d = e.shiftKey ? 10 : 1, s = this.sel, r = [...s.rect];
      if (e.key === 'ArrowLeft') r[0] -= d; else if (e.key === 'ArrowRight') r[0] += d; else if (e.key === 'ArrowUp') r[1] -= d; else r[1] += d;
      s.rect = this._onPage(this.v.pages[s.page], r);
      this._drawSel();
      clearTimeout(this._nudge);
      this._nudge = setTimeout(() => { if (this.sel === s) this._commitRect(s.rect); }, 400);
      return done();
    }
    return false;
  }

  // ================================================================== the mouse on the pages
  down(e) {
    if (!this.editable) return false;
    if (e.target.closest('.pe-field, .pe-fbox, .pe-inline, .pe-bar')) return true; // theirs: focus, typing, ticking, their buttons
    if (e.button !== 0) return false;
    if (this.space) return false; // Space held: the page view pans
    if (this.inline) { this._endInline(true); if (this.tool === 'select') return true; }
    const handle = e.target.closest('.pe-h');
    if (handle && this.sel) {
      e.preventDefault();
      if (handle.dataset.pt !== undefined) this._pointDrag(e, +handle.dataset.pt);
      else this._sizeDrag(e, +handle.dataset.mx, +handle.dataset.my);
      return true;
    }
    const box = e.target.closest('.pv-pagebox');
    if (!box) { if (this.tool === 'select') this.select(null); return false; }
    const p = this.v.pages[+box.dataset.page], pt = this.v._pagePoint(p, e), tool = this.tool;
    this.v.scroller.focus({ preventScroll: true });
    if (this.fsel && !FIELD_TOOLS[tool]) { this.fsel = null; this._drawFields(); }
    if (tool === 'select') {
      // as Acrobat: a comment is grabbed, a drag across words selects them, a drag over bare paper pans
      if (e.shiftKey) return false;
      const a = this._hitAnnot(p.i, pt);
      if (a) {
        e.preventDefault();
        this.select({ type: 'annot', page: p.i, id: a.id, rect: a.rect, a });
        this._moveDrag(e, p, pt);
        return true;
      }
      this.select(null);
      if (!this._onWord(p.i, pt)) return false;
      e.preventDefault();
      this.v.selection = null;
      this.v._showSelection();
      this._selecting = true; // (its bar waits for the drag to end)
      this.v._selectDrag(p, e, () => { this._selecting = false; this._textBar(); });
      return true;
    }
    e.preventDefault();
    if (tool === 'typewriter') { // Add text on words it added before: change them, as Acrobat's Fill & Sign does
      const hit = this._hitAnnot(p.i, pt);
      if (hit?.kind === 'text') { this._editAnnotText(hit); return true; }
    }
    if (ONE_OFF.has(tool)) { // clicking a comment with a tool that adds one: take that comment instead of adding another
      const hit = this._hitAnnot(p.i, pt);
      if (hit) {
        this.setTool('select');
        this.select({ type: 'annot', page: p.i, id: hit.id, rect: hit.rect, a: hit });
        this._moveDrag(e, p, pt);
        return true;
      }
    }
    const t = TOOLS[tool] || {};
    if (tool === 'redactText') { // on a form field: the whole field, and what's filled into it
      const f = this.fields.find((x) => x.page === p.i && inRect(x.rect, pt));
      if (f) { this.run('annot_add', { page: p.i, kind: 'redact', rects: [f.rect] }); return true; }
    }
    if (FIELD_TOOLS[tool]) { this._fieldDrag(e, p, pt); return true; }
    if (t.markup || tool === 'redactText' || tool === 'strikeText') {
      this.v._selectDrag(p, e, async (s) => {
        if (!s?.rects?.length || s.page !== p.i) return;
        if (tool === 'redactText') await this.run('annot_add', { page: p.i, kind: 'redact', rects: s.rects });
        else if (tool === 'strikeText') await this.run('annot_add', { page: p.i, kind: 'strike', rects: s.rects, text: s.text });
        else await this.run('annot_add', { page: p.i, kind: tool, rects: s.rects, text: s.text, color: this.style.colors[tool], opacity: this.style.opacity });
        this.v.selection = null;
        this.v._showSelection();
      });
      return true;
    }
    if (tool === 'editImage') { this._imageDown(e, p, pt); return true; }
    if (tool === 'editText') { this._editTextAt(p, pt); return true; }
    if (tool === 'pen') { this._penDrag(e, p, pt); return true; }
    if (['note', 'typewriter', 'check', 'cross', 'dot', 'date', 'addText'].includes(tool)) { this._click(p, pt); return true; }
    // everything else is dragged out (a click makes one of a standard size)
    this._shapeDrag(e, p, pt);
    return true;
  }

  // is a point on one of a page's words? (the boxes come from the worker once, on the first look)
  _onWord(page, pt) {
    const w = this.words[page];
    if (w === undefined) this._wordsFor(page);
    return !!w && w.some((r) => inRect(r, pt, 1.5));
  }

  // the words of the pages in view, asked for ahead, so the first drag across text already selects
  _prefetch() {
    if (!this.editable || !this.v.pages?.length || this.v.el.hidden) return;
    for (const p of this.v._visible()) this._wordsFor(p.i);
  }

  _wordsFor(page) {
    if (this.words[page]) return Promise.resolve(this.words[page]);
    if (!this.editable) return Promise.resolve([]);
    this._wordsAsked ||= {};
    if (this.words[page] === null && this._wordsAsked[page]) return this._wordsAsked[page];
    this.words[page] = null;
    const doc = this.doc;
    return (this._wordsAsked[page] = this._ask('words', { page }).then((r) => {
      if (this.doc === doc) this.words[page] = r;
      return r;
    }).catch(() => { delete this.words[page]; return []; }));
  }

  // the I-beam over words with the Select tool; a pointer over comments
  _hover(e) {
    const s = this.v.scroller;
    if (!this.editable || e.buttons) return;
    if (PLACE[this.tool]) { this._followAt(e); return; }
    if (this.tool !== 'select') return;
    const box = e.target.closest?.('.pv-pagebox');
    let cls = '', over = null;
    if (box && !e.target.closest('.pe-field, .pe-inline, .pe-h, .pe-bar')) {
      const p = this.v.pages[+box.dataset.page], pt = this.v._pagePoint(p, e);
      over = this._hitAnnot(p.i, pt);
      if (over) cls = 'pe-over-annot';
      else if (this._onWord(p.i, pt)) cls = 'pe-over-text';
    }
    this._setHover(over);
    if (s.dataset.over !== cls) {
      s.classList.remove('pe-over-annot', 'pe-over-text');
      if (cls) s.classList.add(cls);
      s.dataset.over = cls;
    }
  }

  // the comment under the pointer: outlined, with who wrote it and what it says
  _setHover(a) {
    const key = a ? `${a.page}:${a.id}` : '';
    if (key === (this._hov || '')) return;
    this._hov = key;
    this.v.sheet.querySelectorAll('.pe-hover').forEach((n) => n.remove());
    this.v.scroller.title = '';
    if (!a) return;
    const p = this.v.pages?.[a.page];
    if (!p) return;
    if (!(this.sel?.type === 'annot' && this.sel.id === a.id && this.sel.page === a.page)) p.edit.append(h('div', { class: 'pe-hover', style: this.v._rectStyle(p, a.rect) }));
    this.v.scroller.title = `${this._label(a)}${a.author ? ` · ${a.author}` : ''}${a.contents ? `\n${a.contents}` : ''}`;
  }

  // a signature, stamp or picture about to be placed rides under the pointer, at the size a click gives it
  _placeSize(tool) {
    const [w, hh] = PLACE[tool];
    return [w, this.payload?.aspect ? w / this.payload.aspect : hh];
  }

  _followAt(e) {
    const box = e.target.closest?.('.pv-pagebox');
    if (!box) { this._follow?.remove(); return; }
    const p = this.v.pages[+box.dataset.page], pt = this.v._pagePoint(p, e), [w, hh] = this._placeSize(this.tool);
    if (!this._follow) {
      this._follow = h('div', { class: 'pe-follow' });
      if (this.payload?.image) this._follow.append(h('img', { src: this.payload.image }));
      else this._follow.append(h('span', { text: STAMP_LABEL[this.payload?.stamp] || '' }));
    }
    if (this._follow.parentNode !== p.edit) p.edit.append(this._follow);
    this._follow.style.cssText = this.v._rectStyle(p, [pt[0], pt[1], w, hh]);
  }

  // is a point on a comment? A shape with no fill, a line or a drawing is only on its lines (as Acrobat), so the
  // words and paper inside a revision cloud can still be selected and panned
  _onAnnot(a, pt) {
    const tol = 4 + Math.max(a.width > 0 ? a.width : 1, 1);
    if (!inRect(a.rect, pt, tol)) return false;
    const [x, y, w, hh] = a.rect, thin = w < 3 * tol || hh < 3 * tol;
    if (a.kind === 'rect' && !a.fill) return thin || !inRect([x + tol, y + tol, w - 2 * tol, hh - 2 * tol], pt);
    if (a.kind === 'ellipse' && !a.fill) {
      if (thin) return true;
      const d = Math.hypot((pt[0] - x - w / 2) / (w / 2), (pt[1] - y - hh / 2) / (hh / 2));
      return Math.abs(d - 1) * Math.min(w, hh) / 2 <= tol;
    }
    if (a.kind === 'line' && a.points?.length >= 2) return segDist(pt, a.points[0], a.points[1]) <= tol;
    if (a.kind === 'ink' && a.points?.length) return a.points.some((s) => s.some((q, i) => (i ? segDist(pt, s[i - 1], q) : Math.hypot(pt[0] - q[0], pt[1] - q[1])) <= tol));
    if ((a.kind === 'polygon' || a.kind === 'polyline') && !a.fill && a.points?.length > 1) {
      const ring = a.kind === 'polygon' ? [...a.points, a.points[0]] : a.points;
      return ring.some((q, i) => i && segDist(pt, ring[i - 1], q) <= tol);
    }
    return true;
  }

  _hitAnnot(page, pt) {
    let best = null, area = Infinity;
    for (const a of this.annots) {
      if (a.page !== page || a.replyTo) continue;
      if (!this._onAnnot(a, pt)) continue;
      const ar = a.rect[2] * a.rect[3];
      if (ar < area) { best = a; area = ar; }
    }
    return best;
  }

  // follow a drag in page points: move(from, now), then up(from, now, moved)
  _drag(e, p, from, move, up) {
    let now = from, moved = false;
    const mv = (m) => {
      now = this.v._pagePoint(p, m);
      if (!moved && Math.hypot(m.clientX - e.clientX, m.clientY - e.clientY) < 3) return;
      moved = true;
      move?.(from, now);
    };
    const stop = (u) => {
      window.removeEventListener('pointermove', mv);
      window.removeEventListener('pointerup', stop);
      this._lastX = u.clientX;
      this._lastY = u.clientY;
      up(from, now, moved);
    };
    window.addEventListener('pointermove', mv);
    window.addEventListener('pointerup', stop);
  }

  // ------------------------------------------------------------------ drawing over a page
  // a point in the page's points to the page as shown (turned by the view), in points
  _view(p, [x, y]) {
    const W = p.info.w, H = p.info.h;
    switch (this.v.state.turns) {
      case 1: return [H - y, x];
      case 2: return [W - x, H - y];
      case 3: return [y, W - x];
      default: return [x, y];
    }
  }

  _ghost(p) {
    const [sw, sh] = this.v._size(p);
    p.edit.querySelector('.pe-ghost')?.remove();
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'pe-ghost');
    svg.setAttribute('viewBox', `0 0 ${sw} ${sh}`);
    svg.setAttribute('preserveAspectRatio', 'none');
    p.edit.append(svg);
    return svg;
  }

  _ghostShape(svg, p, kind, a, b, color) {
    const ns = 'http://www.w3.org/2000/svg';
    const el = (tag, attrs) => { const n = document.createElementNS(ns, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); return n; };
    const w = Math.max(this.style.width, 1);
    svg.replaceChildren();
    const A = this._view(p, a), B = this._view(p, b);
    const x = Math.min(A[0], B[0]), y = Math.min(A[1], B[1]), ww = Math.abs(A[0] - B[0]), hh = Math.abs(A[1] - B[1]);
    const common = { stroke: color, 'stroke-width': w, fill: 'none', 'vector-effect': 'non-scaling-stroke' };
    if (kind === 'ellipse') svg.append(el('ellipse', { cx: x + ww / 2, cy: y + hh / 2, rx: ww / 2, ry: hh / 2, ...common }));
    else if (kind === 'line' || kind === 'arrow') svg.append(el('line', { x1: A[0], y1: A[1], x2: B[0], y2: B[1], ...common }));
    else if (kind === 'redact') svg.append(el('rect', { x, y, width: ww, height: hh, fill: 'rgba(0,0,0,.25)', stroke: '#c00', 'stroke-width': 1, 'vector-effect': 'non-scaling-stroke' }));
    else if (kind === 'crop') svg.append(el('rect', { x, y, width: ww, height: hh, fill: 'rgba(40,110,240,.08)', stroke: '#2a6ff0', 'stroke-dasharray': '5 4', 'stroke-width': 1.5, 'vector-effect': 'non-scaling-stroke' }));
    else svg.append(el('rect', { x, y, width: ww, height: hh, ...common, 'stroke-dasharray': kind === 'cloud' ? '3 2' : 'none' }));
  }

  _shapeDrag(e, p, from) {
    const tool = this.tool, svg = this._ghost(p), color = this.style.colors[tool] || '#e02020';
    this._drag(e, p, from, (a, b) => this._ghostShape(svg, p, tool === 'redact' || tool === 'crop' ? tool : tool, a, b, color), async (a, b, moved) => {
      svg.remove();
      let r = rectOf(a, b);
      const sized = { text: [200, 40], stamp: [160, 52], sign: [150, 50], initials: [60, 36], addImage: [150, 100], rect: [60, 40], ellipse: [60, 40], cloud: [80, 50] }[tool];
      if (!moved || r[2] < 4 || r[3] < 4) {
        if (tool === 'line' || tool === 'arrow' || tool === 'redact' || tool === 'crop' || !sized) return;
        r = [a[0], a[1], ...sized];
        if (['sign', 'initials', 'addImage', 'stamp'].includes(tool) && this.payload?.aspect) r[3] = r[2] / this.payload.aspect;
      } else if (['sign', 'initials', 'addImage'].includes(tool) && this.payload?.aspect) r[3] = r[2] / this.payload.aspect;
      const st = this.style, color = st.colors[tool];
      if (tool === 'line' || tool === 'arrow') await this.run('annot_add', { page: p.i, kind: tool, points: [a, b], color, width: st.width, opacity: st.opacity });
      else if (['rect', 'ellipse', 'cloud'].includes(tool)) await this.run('annot_add', { page: p.i, kind: tool, rect: r, color, width: st.width, opacity: st.opacity });
      else if (tool === 'text') this._typeInto(p, r, { kind: 'text', fill: '#fff9c4' });
      else if (tool === 'stamp') await this.run('annot_add', { page: p.i, kind: 'stamp', rect: r, ...(this.payload?.image ? { image: this.payload.image } : { stamp: this.payload?.stamp || 'Approved' }), opacity: st.opacity });
      else if (tool === 'sign' || tool === 'initials') { await this.run('annot_add', { page: p.i, kind: 'stamp', rect: r, image: this.payload.image, subject: tool === 'sign' ? 'Signature' : 'Initials' }); this.setTool('select'); }
      else if (tool === 'addImage') { await this.run('image_add', { page: p.i, rect: r, image: this.payload.image }); this.setTool('editImage'); }
      else if (tool === 'redact') await this.run('annot_add', { page: p.i, kind: 'redact', rects: [r] });
      else if (tool === 'crop') this._cropAsk(p, r);
    });
  }

  _penDrag(e, p, from) {
    const svg = this._ghost(p), pts = [from], color = this.style.colors.pen;
    const ns = 'http://www.w3.org/2000/svg', line = document.createElementNS(ns, 'polyline');
    Object.entries({ fill: 'none', stroke: color, 'stroke-width': Math.max(this.style.width, 1), 'vector-effect': 'non-scaling-stroke', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }).forEach(([k, v]) => line.setAttribute(k, v));
    svg.append(line);
    this._drag(e, p, from, (a, b) => {
      pts.push(b);
      line.setAttribute('points', pts.map((q) => this._view(p, q).join(',')).join(' '));
    }, async (a, b, moved) => {
      if (!moved || pts.length < 2) { svg.remove(); return; }
      await this.run('annot_add', { page: p.i, kind: 'ink', points: [pts], color, width: this.style.width, opacity: this.style.opacity });
      svg.remove();
    });
  }

  // a click with the note, check, cross, dot, date and text tools
  async _click(p, pt) {
    const st = this.style, tool = this.tool, color = st.colors[tool];
    if (tool === 'note') {
      this._popup(p, [pt[0], pt[1], 0, 0], '', async (text) => {
        if (text.trim()) await this.run('annot_add', { page: p.i, kind: 'note', at: pt, contents: text, color });
      }, 'Note');
    } else if (tool === 'check' || tool === 'cross' || tool === 'dot') {
      const s = 12;
      const at = (q) => [pt[0] - s / 2 + q[0] * s, pt[1] - s / 2 + q[1] * s];
      if (tool === 'dot') {
        await this.run('annot_add', { page: p.i, kind: 'ellipse', rect: [pt[0] - 3, pt[1] - 3, 6, 6], color, fill: color, width: 0.5, subject: 'Dot' });
      } else {
        const strokes = tool === 'check' ? [CHECK.map(at)] : CROSS.map((s2) => s2.map(at));
        await this.run('annot_add', { page: p.i, kind: 'ink', points: strokes, color, width: 1.8, subject: tool === 'check' ? 'Check' : 'Cross' });
      }
    } else if (tool === 'date') {
      const text = new Date().toLocaleDateString();
      await this.run('annot_add', { page: p.i, kind: 'text', rect: [pt[0], pt[1] - st.fontsize * 0.85, 0, 0], fit: true, text, fontsize: st.fontsize, textColor: color, subject: 'Date' });
    } else if (tool === 'typewriter') {
      this._typeInto(p, [pt[0], pt[1] - st.fontsize * 0.85, 0, 0], { kind: 'text', grow: true });
    } else if (tool === 'addText') {
      this._typeInto(p, [pt[0], pt[1] - st.fontsize * 0.85, 0, 0], { kind: 'content', grow: true });
    }
  }

  // a box just big enough for some words at a size (the 14 standard fonts run about half an em a letter)
  _fit(at, text, size) {
    const lines = String(text).split('\n');
    const w = Math.max(...lines.map((l) => l.length), 1) * size * 0.56 + 6, hh = lines.length * size * 1.25 + 4;
    return [at[0], at[1], w, hh];
  }

  // ------------------------------------------------------------------ typing on the page
  // a box to type in over the page; done(text) when it's left
  _inlineBox(p, rect, { value = '', size = 12, color = '#000', font = '', grow = false, fill = null, done }) {
    this._endInline(true);
    const ta = h('textarea', { class: 'pe-inline', spellcheck: 'true' });
    ta.value = value;
    ta.style.color = color;
    if (font) ta.style.font = font;
    if (fill) ta.style.background = fill;
    this.inline = { p, rect, ta, size, grow, done };
    p.edit.append(ta);
    this._placeInline();
    ta.addEventListener('keydown', (e) => {
      e.stopPropagation();
      if (e.key === 'Escape') { e.preventDefault(); this._endInline(false); }
      else if (e.key === 'Enter' && (e.ctrlKey || !grow)) { e.preventDefault(); this._endInline(true); }
    });
    ta.addEventListener('blur', () => setTimeout(() => { if (this.inline?.ta === ta) this._endInline(true); }, 0));
    setTimeout(() => { ta.focus(); ta.select(); }, 0);
  }

  _placeInline() {
    const { p, rect, ta, size, grow } = this.inline;
    const k = p.cssW / this.v._size(p)[0]; // css px per point
    ta.style.cssText += `;${this.v._rectStyle(p, rect.map((v, j) => (grow && j > 1 ? Math.max(v, 1) : v)))}`;
    ta.style.fontSize = `${size * k}px`;
    if (grow) { ta.style.width = ''; ta.style.height = ''; ta.style.minWidth = `${40 * k}px`; ta.classList.add('grow'); }
  }

  _endInline(commit) {
    const it = this.inline;
    if (!it) return;
    this.inline = null;
    it.ta.remove();
    if (commit) it.done(it.ta.value);
  }

  // type a text box, or words into the page itself
  _typeInto(p, rect, { kind, fill = null, grow = false }) {
    const st = this.style, size = st.fontsize, color = st.colors[kind === 'content' ? 'addText' : this.tool === 'typewriter' ? 'typewriter' : 'text'];
    this._inlineBox(p, rect, { size, color, grow, fill, font: `${size}px Helvetica, Arial, sans-serif`,
      done: async (text) => {
        if (!text.trim()) return;
        if (kind === 'content') {
          await this.run('text_add', { page: p.i, at: [rect[0], rect[1] + size * 0.85], text, size, color });
        } else {
          const r = grow ? this._fit([rect[0], rect[1]], text, size) : rect;
          await this.run('annot_add', { page: p.i, kind: 'text', rect: r, fit: grow, text, fontsize: size, textColor: color, fill, opacity: st.opacity,
            subject: this.tool === 'typewriter' ? 'Typewriter' : 'Text Box' });
        }
      } });
  }

  // a floating box for a comment's words (notes, and any comment double-clicked)
  _popup(p, rect, value, done, title) {
    this._pop?.remove();
    const r = p.el.getBoundingClientRect(), [sw, sh] = this.v._size(p);
    const at = this._view(p, [rect[0] + rect[2], rect[1]]);
    const x = clamp(r.left + at[0] / sw * r.width + 12, 8, innerWidth - 300), y = clamp(r.top + at[1] / sh * r.height, 60, innerHeight - 220);
    const ta = h('textarea', { class: 'pe-pop-text', placeholder: 'Type a comment' });
    ta.value = value;
    const pop = h('div', { class: 'pe-pop', style: { left: `${x}px`, top: `${y}px` } },
      h('div', { class: 'pe-pop-head', text: title }), ta,
      h('div', { class: 'pe-pop-foot' }, h('span', { class: 'pv-of', text: 'Ctrl+Enter' }),
        h('button', { class: 'btn', text: 'Cancel', onclick: () => pop.remove() }),
        h('button', { class: 'btn primary', text: 'OK', onclick: () => { pop.remove(); done(ta.value); } })));
    ta.addEventListener('keydown', (e) => {
      e.stopPropagation();
      if (e.key === 'Escape') pop.remove();
      if (e.key === 'Enter' && e.ctrlKey) { pop.remove(); done(ta.value); }
    });
    document.body.append(pop);
    this._pop = pop;
    setTimeout(() => ta.focus(), 0);
  }

  _dbl(e) {
    if (!this.editable || this.tool !== 'select') return;
    if (!this.sel || this.sel.type !== 'annot') { this._selectWord(e); return; }
    const a = this.sel.a, p = this.v.pages[a.page];
    if (a.kind === 'text') {
      this._editAnnotText(a);
    } else {
      this._popup(p, a.rect, a.contents, (text) => { if (text !== a.contents) this.run('annot_set', { page: a.page, id: a.id, contents: text }); }, this._label(a));
    }
  }

  _editAnnotText(a) {
    const p = this.v.pages[a.page];
    this._inlineBox(p, a.rect, { value: a.contents, size: a.fontsize, color: a.textColor, font: `${a.fontsize}px Helvetica, Arial, sans-serif`, fill: a.fill || '#ffffff',
      done: (text) => { if (text !== a.contents) this.run('annot_set', { page: a.page, id: a.id, text }); } });
  }

  // ------------------------------------------------------------------ selecting the page's own text
  async _selectSpan(page, a, b) {
    try {
      const r = await api.pdfSelect(this.doc.id, { page, ax: a[0], ay: a[1], bx: b[0], by: b[1] });
      if (!r.rects.length) return;
      this.v.selection = { page, ...r };
      this.v._showSelection();
    } catch { /* nothing there */ }
  }

  // Ctrl+A: every word on the page
  async _selectPage(page) {
    const w = await this._wordsFor(page);
    if (!w?.length) return;
    const mid = (r) => [r[0] + r[2] / 2, r[1] + r[3] / 2];
    await this._selectSpan(page, mid(w[0]), mid(w[w.length - 1]));
  }

  // a double-click on a word selects it
  _selectWord(e) {
    const box = e.target.closest?.('.pv-pagebox');
    if (!box) return;
    const p = this.v.pages[+box.dataset.page], pt = this.v._pagePoint(p, e);
    const w = (this.words[p.i] || []).find((r) => inRect(r, pt, 1.5));
    if (w) this._selectSpan(p.i, [w[0] + w[2] / 2, w[1] + w[3] / 2], [w[0] + w[2] / 2, w[1] + w[3] / 2]);
  }

  // right-click: what can be done to the selected words, or to a comment
  _context(e) {
    if (!this.editable) return;
    const box = e.target.closest?.('.pv-pagebox');
    if (!box || e.target.closest('.pe-field, .pe-inline')) return;
    e.preventDefault();
    const p = this.v.pages[+box.dataset.page], pt = this.v._pagePoint(p, e), at = { x: e.clientX, y: e.clientY };
    const s = this.v.selection;
    if (s?.page === p.i && s.rects.some((r) => inRect(r, pt, 2))) {
      const mark = (kind) => async () => {
        await this.run('annot_add', kind === 'redact' ? { page: s.page, kind, rects: s.rects }
          : { page: s.page, kind, rects: s.rects, text: s.text, color: this.style.colors[kind], opacity: this.style.opacity });
        this.v.selection = null;
        this.v._showSelection();
      };
      menu(null, [
        { label: 'Copy', kb: 'Ctrl+C', action: () => navigator.clipboard?.writeText(s.text).catch(() => document.execCommand('copy')) },
        { sep: true },
        { label: 'Highlight', action: mark('highlight') },
        { label: 'Underline', action: mark('underline') },
        { label: 'Strikethrough', action: mark('strikeout') },
        { label: 'Squiggly underline', action: mark('squiggly') },
        { sep: true },
        { label: 'Mark for redaction', action: mark('redact') },
      ], { at });
      return;
    }
    const a = this._hitAnnot(p.i, pt);
    if (!a) return;
    this.setTool('select');
    this.select({ type: 'annot', page: p.i, id: a.id, rect: a.rect, a });
    menu(null, [
      a.kind === 'text' ? { label: 'Edit text', action: () => this._editAnnotText(a) } : null,
      { label: a.contents ? 'Edit comment…' : 'Add a comment…', action: () => this._popup(p, a.rect, a.contents, (text) => { if (text !== a.contents) this.run('annot_set', { page: a.page, id: a.id, contents: text }); }, this._label(a)) },
      { label: 'Show in the comments list', action: () => { if (!this.showPanel) this.togglePanel(); this.select(this.sel); this.panel.querySelector('.pe-item.on')?.scrollIntoView({ block: 'nearest' }); } },
      { sep: true },
      { label: 'Delete', kb: 'Del', action: () => this.deleteSel() },
    ], { at });
  }

  // ------------------------------------------------------------------ selection, moving and sizing
  // a picture of the selected comment, to carry along when it's dragged
  _fetchImg(sel) {
    if (sel?.type !== 'annot' || this.v.state.turns !== 0 || !this.doc) return;
    const doc = this.doc;
    this._ask('annot_image', { page: sel.page, id: sel.id }).then((img) => { if (this.doc === doc && this.sel === sel) sel.img = img; }).catch(() => {});
  }

  select(sel) {
    this.sel = sel;
    this._fetchImg(sel);
    if (sel && this.v.selection) { this.v.selection = null; this.v._showSelection(); }
    this._drawSel();
    this._bar();
    this.panel.querySelectorAll('.pe-item').forEach((n) => n.classList.toggle('on', !!sel && +n.dataset.id === sel.id && +n.dataset.page === sel.page));
  }

  _drawSel() {
    this.v.sheet.querySelectorAll('.pe-sel, .pe-h').forEach((n) => n.remove());
    const s = this.sel;
    if (!s || !this.v.pages?.[s.page]) return;
    const p = this.v.pages[s.page], [x, y, w, hh] = s.rect;
    const thin = s.type === 'annot' && s.a.kind === 'line' && !s.moved; // a line shows its two ends, not a box
    const box = h('div', { class: `pe-sel${s.type === 'image' ? ' img' : ''}${thin ? ' thin' : ''}`, style: this.v._rectStyle(p, s.rect) });
    p.edit.append(box);
    this._setHover(null);
    if (s.type === 'annot') box.append(this._annotBar(s, p));
    const fixed = s.type === 'annot' && s.a.kind === 'note';
    if (fixed) return;
    if (s.type === 'annot' && s.a.kind === 'line' && s.a.points?.length === 2 && !s.moved) { // a line: a handle on each end
      s.a.points.forEach((q, i) => {
        const el = h('div', { class: 'pe-h pt', style: this.v._rectStyle(p, [q[0], q[1], 0, 0]) });
        el.dataset.pt = i;
        p.edit.append(el);
      });
      return;
    }
    for (const mx of [-1, 0, 1]) {
      for (const my of [-1, 0, 1]) {
        if (!mx && !my) continue;
        const px = x + (mx + 1) / 2 * w, py = y + (my + 1) / 2 * hh;
        const el = h('div', { class: 'pe-h', style: this.v._rectStyle(p, [px, py, 0, 0]) });
        el.dataset.mx = mx;
        el.dataset.my = my;
        p.edit.append(el);
      }
    }
  }

  // the bar that rides on a selected comment: quick colors, its words, duplicate, delete
  _annotBar(s, p) {
    const a = s.a, colorable = !['stamp', 'redact', 'file'].includes(a.kind), key = a.kind === 'text' ? 'textColor' : 'color';
    const btn = (icon, tip, run) => h('button', { class: 'pe-bb', title: tip, html: ICON[icon], onclick: (ev) => { ev.stopPropagation(); run(); } });
    const now = (a.kind === 'text' ? a.textColor : a.color) || '';
    const kids = [
      ...(colorable ? QUICK.map((c) => h('button', { class: `pe-bd${c === now ? ' on' : ''}`, style: { background: c }, title: 'Color',
        onclick: (ev) => { ev.stopPropagation(); this.run('annot_set', { page: s.page, id: s.id, [key]: c }); } })) : []),
      colorable ? h('span', { class: 'pe-bs' }) : null,
      a.kind === 'text' ? btn('editText', 'Edit the text (double-click)', () => this._editAnnotText(a))
        : btn('note', a.contents ? 'Edit the comment (double-click)' : 'Add a comment (double-click)', () => this._popup(p, a.rect, a.contents,
          (text) => { if (text !== a.contents) this.run('annot_set', { page: a.page, id: a.id, contents: text }); }, this._label(a))),
      CLONABLE.has(a.kind) ? btn('copy', 'Duplicate (Ctrl+D)', () => this._clone(s.page, s.id, s.page)) : null,
      btn('trash', 'Delete (Del)', () => this.deleteSel()),
    ].filter(Boolean);
    const turned = this.v.state.turns !== 0;
    const cls = `${!turned && s.rect[1] < 40 ? ' below' : ''}${!turned && s.rect[0] > p.info.w - 190 ? ' right' : ''}`;
    return h('div', { class: `pe-bar annot${cls}` }, h('div', { class: 'pe-bar-in' }, ...kids));
  }

  // the bar by selected text: copy it, mark it up, note it, redact it
  _textBar() {
    this.v.sheet?.querySelectorAll('.pe-bar.text').forEach((n) => n.remove());
    const s = this.v.selection;
    if (!this.editable || this._selecting || this.tool !== 'select' || !s?.rects?.length) return;
    const p = this.v.pages?.[s.page];
    if (!p) return;
    const mark = (kind, extra = {}) => async () => {
      await this.run('annot_add', kind === 'redact' ? { page: s.page, kind, rects: s.rects }
        : { page: s.page, kind, rects: s.rects, text: s.text, color: this.style.colors[kind], opacity: this.style.opacity, ...extra });
      this.v.selection = null;
      this.v._showSelection();
    };
    const btn = (icon, tip, run) => h('button', { class: 'pe-bb', title: tip, html: ICON[icon], onclick: (ev) => { ev.stopPropagation(); run(); } });
    const turned = this.v.state.turns !== 0;
    const r = turned ? s.rects[0] : s.rects.reduce((a, b) => (b[1] < a[1] ? b : a));
    const k = p.cssW / this.v._size(p)[0];
    const inner = h('div', { class: 'pe-bar-in' },
      btn('copy', 'Copy (Ctrl+C)', async () => { await copyText(s.text); toast('Copied.', 'ok', 1200); }),
      h('span', { class: 'pe-bs' }),
      btn('highlight', 'Highlight', mark('highlight')),
      btn('underline', 'Underline', mark('underline')),
      btn('strikeout', 'Strikethrough', mark('strikeout')),
      btn('note', 'Highlight with a note', () => this._popup(p, r, '', (text) => mark('highlight', text.trim() ? { contents: text } : {})(), 'Note on this text')),
      h('span', { class: 'pe-bs' }),
      btn('redactText', 'Mark for redaction', mark('redact')));
    if (!turned && r[1] < 40) { inner.style.bottom = 'auto'; inner.style.top = `${r[3] * k + 8}px`; }
    p.edit.append(h('div', { class: 'pe-bar text', style: this.v._rectStyle(p, [r[0], r[1], 0, 0]) }, inner));
  }

  // drag one end of a line
  _pointDrag(e, i) {
    const s = this.sel, p = this.v.pages[s.page], pts = s.a.points.map((q) => [...q]), svg = this._ghost(p);
    this._drag(e, p, this.v._pagePoint(p, e), (a, b) => {
      pts[i] = [clamp(b[0], 0, p.info.w), clamp(b[1], 0, p.info.h)];
      this._ghostShape(svg, p, 'line', pts[0], pts[1], s.a.color || '#e02020');
    }, async (a, b, moved) => {
      if (moved) {
        const res = await this.run('annot_set', { page: s.page, id: s.id, points: pts });
        const n = res?.result;
        if (n) this.select({ type: 'annot', page: s.page, id: n.id, rect: n.rect, a: { ...n, page: s.page } });
      }
      svg.remove();
    });
  }

  // while a comment is dragged its picture goes along, so it's plain where it will land
  _carry(box) {
    const s = this.sel;
    if (!box || box.classList.contains('moving')) return;
    box.classList.add('moving');
    if (s.img) box.prepend(h('img', { class: 'pe-carry', src: s.img }));
  }

  _moveDrag(e, p, from) {
    const r0 = [...this.sel.rect], box = p.edit.querySelector('.pe-sel');
    this._drag(e, p, from, (a, b) => {
      const r = this._onPage(p, [r0[0] + b[0] - a[0], r0[1] + b[1] - a[1], r0[2], r0[3]]);
      this._carry(box);
      this.sel.moved = true;
      this.sel.rect = r;
      if (box) box.style.cssText = this.v._rectStyle(p, r);
      p.edit.querySelectorAll('.pe-h').forEach((n) => n.remove());
    }, (a, b, moved) => {
      if (!moved) return;
      this._commitRect(this._onPage(p, [r0[0] + b[0] - a[0], r0[1] + b[1] - a[1], r0[2], r0[3]]));
    });
  }

  // a rectangle moved back onto its page (as shown, unturned by the view), so nothing is dragged out of sight
  _onPage(p, r) {
    const W = p.info.w, H = p.info.h;
    return [clamp(r[0], 0, Math.max(0, W - r[2])), clamp(r[1], 0, Math.max(0, H - r[3])), r[2], r[3]];
  }

  _sizeDrag(e, mx, my) {
    const s = this.sel, p = this.v.pages[s.page], r0 = [...s.rect], box = p.edit.querySelector('.pe-sel');
    const from = this.v._pagePoint(p, e);
    const keepShape = s.type === 'image' || (s.a?.kind === 'stamp');
    const calc = (b) => {
      let x0 = r0[0], y0 = r0[1], x1 = r0[0] + r0[2], y1 = r0[1] + r0[3];
      if (mx < 0) x0 = b[0]; if (mx > 0) x1 = b[0];
      if (my < 0) y0 = b[1]; if (my > 0) y1 = b[1];
      x0 = clamp(x0, 0, p.info.w); x1 = clamp(x1, 0, p.info.w); y0 = clamp(y0, 0, p.info.h); y1 = clamp(y1, 0, p.info.h);
      let r = rectOf([x0, y0], [x1, y1]);
      if (keepShape && mx && my && r0[2] && r0[3]) { // a corner keeps a picture's shape
        const k = Math.max(r[2] / r0[2], r[3] / r0[3]);
        const w = r0[2] * k, hh = r0[3] * k;
        r = [mx < 0 ? r0[0] + r0[2] - w : r0[0], my < 0 ? r0[1] + r0[3] - hh : r0[1], w, hh];
      }
      return [r[0], r[1], Math.max(r[2], 2), Math.max(r[3], 2)];
    };
    this._drag(e, p, from, (a, b) => {
      this._carry(box);
      s.rect = calc(b);
      if (box) box.style.cssText = this.v._rectStyle(p, s.rect);
      p.edit.querySelectorAll('.pe-h').forEach((n) => n.remove());
    }, (a, b, moved) => { if (moved) this._commitRect(calc(b)); else this._drawSel(); });
  }

  async _commitRect(r) {
    const s = this.sel;
    s.rect = r;
    this._drawSel();
    if (s.type === 'image') {
      const res = await this.run('image_set', { page: s.page, id: s.id, rect: r });
      if (res) this._reselectImage(s.page, r);
    } else {
      const res = await this.run('annot_set', { page: s.page, id: s.id, rect: r });
      const a = res?.result;
      if (a) this.select({ type: 'annot', page: s.page, id: a.id, rect: a.rect, a: { ...a, page: s.page } });
    }
  }

  async deleteSel() {
    const s = this.sel;
    if (!s) return;
    this.select(null);
    if (s.type === 'image') await this.run('image_delete', { page: s.page, id: s.id });
    else await this.run('annot_delete', { page: s.page, ids: [s.id] });
  }

  // ------------------------------------------------------------------ the pages' own text and pictures
  async _editTextAt(p, pt) {
    let line;
    try { line = await this._ask('text_at', { page: p.i, at: pt }); } catch (e) { toast(e.message, 'error'); return; }
    if (!line) { toast('There\'s no text there to edit. (A scanned page is a picture: use Add text and a white box instead.)', 'info'); return; }
    const family = line.mono ? 'Courier New, monospace' : line.serif ? 'Times New Roman, serif' : 'Helvetica, Arial, sans-serif';
    const font = `${line.italic ? 'italic ' : ''}${line.bold ? 'bold ' : ''}${line.size}px ${family}`;
    this._inlineBox(p, line.rect, { value: line.text, size: line.size, color: line.color, font, fill: '#ffffff', grow: false,
      done: (text) => {
        if (text === line.text) return;
        this.run('text_replace', { page: p.i, rect: line.rect, text, size: line.size, color: line.color, bold: line.bold, italic: line.italic, serif: line.serif, mono: line.mono });
      } });
    this.inline.ta.classList.add('pe-editline');
  }

  async _loadImages(page) {
    if (!this.editable) return;
    const pages = page == null ? this.v._visible().map((p) => p.i) : [page];
    for (const i of pages) {
      if (this.images[i]) continue;
      try { this.images[i] = await this._ask('images', { page: i }); } catch { this.images[i] = []; }
    }
  }

  async _imageDown(e, p, pt) {
    if (!this.images[p.i]) await this._loadImages(p.i);
    const hits = (this.images[p.i] || []).filter((im) => inRect(im.rect, pt)).sort((a, b) => a.rect[2] * a.rect[3] - b.rect[2] * b.rect[3]);
    if (!hits.length) { this.select(null); return; }
    const im = hits[0];
    if (this.sel?.type !== 'image' || this.sel.id !== im.id || this.sel.page !== p.i) this.select({ type: 'image', page: p.i, id: im.id, rect: im.rect });
    this._moveDrag(e, p, pt);
  }

  async _reselectImage(page, r) {
    await this._loadImages(page);
    const near = (this.images[page] || []).find((im) => Math.abs(im.rect[0] - r[0]) < 2 && Math.abs(im.rect[1] - r[1]) < 2);
    this.select(near ? { type: 'image', page, id: near.id, rect: near.rect } : null);
  }

  // ------------------------------------------------------------------ form fields
  _drawFields() {
    const live = new Set(), design = this.set === 'form';
    for (const f of this.fields) {
      const p = this.v.pages?.[f.page];
      if (!p || (!design && !['text', 'checkbox', 'radio', 'combo', 'list'].includes(f.kind))) continue;
      const key = `${design ? 'd' : 'f'}:${f.page}:${f.id}`;
      live.add(key);
      let el = this.fieldEls.get(key);
      if (!el) {
        el = design ? this._fieldBox(f) : this._fieldEl(f);
        this.fieldEls.set(key, el);
      }
      if (el.parentNode !== p.edit) p.edit.append(el);
      el.style.cssText = this.v._rectStyle(p, f.rect);
      if (design) { // a box to arrange: named, and marked when it's the one selected
        el.field = f;
        el.firstChild.textContent = f.name;
        el.title = `${f.name}\nDrag to move, the corner to size, double-click for its properties`;
        el.dataset.kind = f.kind;
        el.classList.toggle('on', this.fsel?.page === f.page && this.fsel?.id === f.id);
        continue;
      }
      const k = p.cssW / this.v._size(p)[0];
      if (f.kind === 'text' || f.kind === 'combo' || f.kind === 'list') el.style.fontSize = `${(f.fontsize || Math.min(f.rect[3] * 0.7, 12)) * k}px`;
      if (document.activeElement !== el && !el.timer) { // never under someone typing
        if (el.type === 'checkbox') el.checked = !!f.value && f.value !== 'Off';
        else el.value = f.value ?? '';
        el.sent = el.type === 'checkbox' ? el.checked : el.value;
      }
      el.field = f;
    }
    for (const [key, el] of this.fieldEls) if (!live.has(key)) { el.remove(); this.fieldEls.delete(key); }
  }

  _fieldEl(f) {
    let el;
    if (f.kind === 'checkbox' || f.kind === 'radio') el = h('input', { type: 'checkbox', class: `pe-field check${f.kind === 'radio' ? ' radio' : ''}` });
    else if (f.kind === 'combo' || f.kind === 'list') {
      el = h('select', { class: 'pe-field' }, ...['', ...f.options.map((o) => (Array.isArray(o) ? o[0] : o))].map((o) => h('option', { value: o, text: o })));
    } else el = f.multiline ? h('textarea', { class: 'pe-field' }) : h('input', { class: 'pe-field', type: 'text', spellcheck: 'false' });
    el.title = `${f.label || f.name}${f.required ? ' (required)' : ''}`;
    if (f.readonly) el.disabled = true;
    if (f.maxlen) el.maxLength = f.maxlen;
    el.addEventListener('keydown', (e) => e.stopPropagation());
    // typed words reach the PDF a moment after typing stops (and when the field is left, or before a save), so
    // nothing typed is lost to a save or a close, and the tab shows the change at once
    el.commit = () => {
      clearTimeout(el.timer);
      el.timer = null;
      const field = el.field, value = el.type === 'checkbox' ? el.checked : el.value;
      if (el.sent === value) return;
      el.sent = value;
      this.run('field_set', { page: field.page, id: field.id, value });
    };
    el.addEventListener('change', () => el.commit());
    if (el.type !== 'checkbox' && el.tagName !== 'SELECT') {
      el.addEventListener('input', () => {
        if (!this.doc.pdfDirty) { this.doc.pdfDirty = true; this.v.app?.shell?.renderDocTabs(); }
        clearTimeout(el.timer);
        el.timer = setTimeout(() => el.commit(), 700);
      });
    }
    el.sent = f.kind === 'checkbox' || f.kind === 'radio' ? !!f.value && f.value !== 'Off' : f.value ?? '';
    return el;
  }

  // ------------------------------------------------------------------ making a form (Prepare Form)
  _fselField() { return this.fsel ? this.fields.find((f) => f.page === this.fsel.page && f.id === this.fsel.id) : null; }

  _fieldBox() {
    const el = h('div', { class: 'pe-fbox' }, h('span', { class: 'pe-fname' }), h('i', { class: 'pe-fh' }));
    el.addEventListener('pointerdown', (e) => this._fieldDown(e, el));
    el.addEventListener('dblclick', (e) => { e.stopPropagation(); this._fieldProps(el.field); });
    return el;
  }

  // a field's box is pressed: it's selected, and a drag moves it (its corner sizes it)
  _fieldDown(e, el) {
    if (e.button !== 0) return;
    e.preventDefault();
    const f = el.field, p = this.v.pages[f.page], sizing = e.target.classList.contains('pe-fh'), r0 = [...f.rect];
    let r = r0;
    this.fsel = { page: f.page, id: f.id };
    this._drawFields();
    this._drag(e, p, this.v._pagePoint(p, e), (a, b) => {
      const dx = b[0] - a[0], dy = b[1] - a[1];
      r = sizing ? [r0[0], r0[1], Math.max(r0[2] + dx, 6), Math.max(r0[3] + dy, 6)] : this._onPage(p, [r0[0] + dx, r0[1] + dy, r0[2], r0[3]]);
      el.style.cssText = this.v._rectStyle(p, r);
    }, (a, b, moved) => { if (moved) this.run('field_edit', { page: f.page, id: f.id, rect: r }); });
  }

  // a new field is dragged out (a click makes one of a usual size)
  _fieldDrag(e, p, from) {
    const tool = this.tool, [kind, w, hh] = FIELD_TOOLS[tool], svg = this._ghost(p);
    this._drag(e, p, from, (a, b) => this._ghostShape(svg, p, 'crop', a, b), async (a, b, moved) => {
      svg.remove();
      let r = rectOf(a, b);
      if (!moved || r[2] < 5 || r[3] < 5) r = [a[0], a[1] - hh / 2, w, hh];
      if (kind === 'checkbox') { const s = Math.min(r[2], r[3]); r = [r[0], r[1], s, s]; }
      const keepOn = this.locked === tool;
      const res = await this.run('field_add', { page: p.i, kind, rect: this._onPage(p, r), multiline: tool === 'fMulti' });
      if (!res?.result?.id) return;
      this.fsel = { page: p.i, id: res.result.id };
      if (keepOn) this.setTool(tool, null, true); else this.setTool('select');
    });
  }

  _formAuto(b) {
    const go = async (pages) => {
      const r = await this.run('form_auto', pages ? { pages } : {}, 'Looking for the blanks…');
      if (!r) return;
      const n = r.result?.count || 0;
      toast(n ? `${n} field${n === 1 ? '' : 's'} added. Drag one to move it, its corner to size it, double-click to name it, Delete to remove it. Fill & Sign tries them out.`
        : 'No blanks found here. Draw the fields with the tools beside this one.', 'info', 8000);
    };
    if (this.v.pages.length < 2) { go(null); return; }
    menu(b, [{ label: 'On this page', action: () => go([this.v.current || 0]) }, { label: `On all ${this.v.pages.length} pages`, action: () => go(null) }]);
  }

  async _formClear() {
    if (!this.fields.length) { toast('There are no fields to remove.', 'info'); return; }
    if (!await this._confirm('Remove all fields', `Take all ${this.fields.length} fields out of the document, with whatever is filled into them?`, 'Remove')) return;
    this.fsel = null;
    this.run('field_delete', {});
  }

  _fieldDelete() {
    const f = this._fselField();
    if (!f) return;
    this.fsel = null;
    this.run('field_delete', { page: f.page, ids: [f.id] });
  }

  _fieldProps(f) {
    const row = (label, el) => h('label', { class: 'pe-frow' }, h('span', { text: label }), el);
    const tick = (el, label) => h('label', { class: 'pe-ftick' }, el, label);
    const name = h('input', { type: 'text', value: f.name, spellcheck: 'false' });
    const tip = h('input', { type: 'text', value: f.label && f.label !== f.name ? f.label : '', placeholder: 'Shown when the pointer is on the field' });
    const req = h('input', { type: 'checkbox', checked: f.required }), ro = h('input', { type: 'checkbox', checked: f.readonly });
    const texty = !['checkbox', 'radio', 'signature', 'button'].includes(f.kind);
    const multi = f.kind === 'text' ? h('input', { type: 'checkbox', checked: f.multiline }) : null;
    const size = texty ? h('select', {}, ...[0, 8, 9, 10, 11, 12, 14, 18].map((x) => h('option', { value: x, text: x ? `${x} pt` : 'Fit to the field', selected: Math.round(f.fontsize) === x }))) : null;
    const opts = ['combo', 'list'].includes(f.kind) ? h('textarea', { rows: 5, spellcheck: 'false' }) : null;
    if (opts) opts.value = f.options.map((o) => (Array.isArray(o) ? o[0] : o)).join('\n');
    let d = null;
    const ok = () => {
      d.close();
      const change = { page: f.page, id: f.id, name: name.value.trim() || f.name, label: tip.value.trim(), required: req.checked, readonly: ro.checked };
      if (multi) change.multiline = multi.checked;
      if (size) change.fontsize = +size.value;
      if (opts) change.options = opts.value.split('\n').map((x) => x.trim()).filter(Boolean);
      this.run('field_edit', change);
    };
    d = modal('Field Properties', h('div', { class: 'pe-fprops' },
      row('Name', name), row('Tip', tip), size && row('Text size', size), opts && row('Choices, one to a line', opts),
      h('div', { class: 'pe-fticks' }, tick(req, 'Required'), tick(ro, 'Read-only'), multi && tick(multi, 'Several lines')),
      h('div', { class: 'pe-pop-foot' },
        h('button', { class: 'btn', text: 'Delete field', onclick: () => { d.close(); this.fsel = { page: f.page, id: f.id }; this._fieldDelete(); } }),
        h('span', { class: 'pv-grow' }),
        h('button', { class: 'btn', text: 'Cancel', onclick: () => d.close() }),
        h('button', { class: 'btn primary', text: 'OK', onclick: ok }))), { width: 420 });
    for (const el of [name, tip]) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') ok(); });
    setTimeout(() => { name.focus(); name.select(); }, 30);
  }

  // ------------------------------------------------------------------ stamps and signatures
  _stampMenu(b) {
    const items = Object.entries(STAMP_LABEL).map(([id, label]) => ({ label, action: () => this.setTool('stamp', { stamp: id }) }));
    items.push({ sep: true }, { label: 'Picture as a stamp…', action: async () => {
      const r = await api.openFiles('image', 'Choose a picture to stamp with').catch(() => null);
      if (r?.files?.length) this.setTool('stamp', { image: r.files[0].data, aspect: await this._aspect(r.files[0].data) });
    } });
    menu(b, items);
  }

  _aspect(data) {
    return new Promise((res) => { const im = new Image(); im.onload = () => res(im.width / Math.max(im.height, 1)); im.onerror = () => res(3); im.src = data; });
  }

  _signMenu(b, kind) {
    const pref = kind === 'sign' ? 'pdfSignature' : 'pdfInitials', saved = this.v.app?.prefs?.[pref];
    const what = kind === 'sign' ? 'signature' : 'initials';
    const items = [];
    if (saved) items.push({ label: `Place my ${what}`, action: async () => this.setTool(kind, { image: saved, aspect: await this._aspect(saved) }) });
    items.push({ label: saved ? `Change my ${what}…` : `Add my ${what}…`, action: () => this._signDialog(kind) });
    if (saved) items.push({ sep: true }, { label: `Forget my ${what}`, action: () => this.v.app?.save({ [pref]: null }) });
    menu(b, items);
  }

  // draw or type a signature once; it's kept (on this computer only) to place again
  _signDialog(kind) {
    const pref = kind === 'sign' ? 'pdfSignature' : 'pdfInitials', what = kind === 'sign' ? 'signature' : 'initials';
    const c = h('canvas', { class: 'pe-pad', width: 920, height: 300 });
    const g = c.getContext('2d');
    let drawn = false;
    const clear = () => { g.clearRect(0, 0, c.width, c.height); drawn = false; };
    c.addEventListener('pointerdown', (e) => {
      c.setPointerCapture(e.pointerId);
      const r = c.getBoundingClientRect(), k = c.width / r.width;
      g.lineWidth = 5; g.lineCap = 'round'; g.lineJoin = 'round'; g.strokeStyle = '#0b1f5c';
      g.beginPath();
      g.moveTo((e.clientX - r.left) * k, (e.clientY - r.top) * k);
      const mv = (m) => { g.lineTo((m.clientX - r.left) * k, (m.clientY - r.top) * k); g.stroke(); drawn = true; };
      const up = () => { c.removeEventListener('pointermove', mv); c.removeEventListener('pointerup', up); };
      c.addEventListener('pointermove', mv);
      c.addEventListener('pointerup', up);
    });
    const typed = h('input', { class: 'pe-type', placeholder: `Or type your ${what}`, spellcheck: 'false' });
    typed.addEventListener('input', () => {
      clear();
      if (!typed.value.trim()) return;
      g.fillStyle = '#0b1f5c';
      let size = 150;
      do { g.font = `${size}px "Segoe Script", "Brush Script MT", cursive`; size -= 6; } while (g.measureText(typed.value).width > c.width - 40 && size > 20);
      g.textBaseline = 'middle';
      g.fillText(typed.value, 20, c.height / 2);
      drawn = true;
    });
    typed.addEventListener('keydown', (e) => e.stopPropagation());
    const d = modal(kind === 'sign' ? 'Your signature' : 'Your initials', h('div', { class: 'pe-sign' },
      h('p', { class: 'pv-of', text: `Draw your ${what} with the mouse or a pen, or type it. It's kept on this computer to place again.` }),
      c, typed,
      h('div', { class: 'pe-pop-foot' },
        h('button', { class: 'btn', text: 'Clear', onclick: () => { clear(); typed.value = ''; } }),
        h('button', { class: 'btn primary', text: 'Use it', onclick: async () => {
          if (!drawn) { toast(`Draw or type your ${what} first.`, 'info'); return; }
          const data = this._trim(c);
          d.close();
          this.v.app?.save({ [pref]: data });
          this.setTool(kind, { image: data, aspect: await this._aspect(data) });
          toast(`Click where your ${what} goes (or drag its size).`, 'info');
        } }))), { width: 520 });
  }

  _trim(c) { // just the ink, with a little margin
    const g = c.getContext('2d'), { width: w, height: hh } = c, px = g.getImageData(0, 0, w, hh).data;
    let x0 = w, y0 = hh, x1 = 0, y1 = 0;
    for (let y = 0; y < hh; y++) for (let x = 0; x < w; x++) if (px[(y * w + x) * 4 + 3] > 10) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
    const m = 8;
    x0 = Math.max(0, x0 - m); y0 = Math.max(0, y0 - m); x1 = Math.min(w - 1, x1 + m); y1 = Math.min(hh - 1, y1 + m);
    const out = h('canvas', { width: x1 - x0 + 1, height: y1 - y0 + 1 });
    out.getContext('2d').drawImage(c, x0, y0, out.width, out.height, 0, 0, out.width, out.height);
    return out.toDataURL('image/png');
  }

  async _flatten() {
    if (!await this._confirm('Flatten', 'Make every comment, signature and filled-in field part of the pages? Nobody will be able to change or remove them after this (until you undo). Balloons on a print stay balloons.', 'Flatten')) return;
    await this.run('flatten', {}, 'Flattening…');
  }

  // ------------------------------------------------------------------ redacting
  async _redactFound() {
    const hits = this.v.hits || [];
    if (!hits.length) { toast('Find the words first (the Find box, top right), then mark them.', 'info'); this.v.findIn.focus(); return; }
    const byPage = new Map();
    for (const hit of hits) byPage.set(hit.page, [...(byPage.get(hit.page) || []), ...hit.rects]);
    for (const [page, rects] of byPage) await this.run('annot_add', { page, kind: 'redact', rects });
    toast(`Marked ${hits.length} place${hits.length === 1 ? '' : 's'}. Check them, then Apply.`);
  }

  async _redactApply() {
    const n = this.annots.filter((a) => a.kind === 'redact').length;
    const k = this.annots.filter((a) => a.kind === 'strikeout' && a.subject === 'Strike through').length;
    if (!n && !k) { toast('Mark something first: Mark text, Mark area, Mark found or Strike through.', 'info'); return; }
    const s = (x) => (x === 1 ? '' : 's');
    const says = [n ? `Take everything under the ${n} redaction mark${s(n)} out of the pages for good: words, the parts of pictures and drawing they cover, and form fields with what's filled into them.` : '',
      k ? `Make the ${k} strike-through${s(k)} part of the page${n ? ` (the words under ${k === 1 ? 'it' : 'them'} stay)` : `, the words under ${k === 1 ? 'it' : 'them'} left readable`}.` : '',
      "It can't be undone in the saved file."].filter(Boolean).join(' ');
    if (!await this._confirm(n ? 'Apply redactions' : 'Apply strike-throughs', says, 'Apply')) return;
    const r = await this.run('redact_apply', { fill: load('pe:redact', 'black') }, n ? 'Redacting…' : 'Applying…');
    if (r) toast(`${n ? 'Redacted' : 'Struck through'}. Save to keep it (Save As keeps the original as it was).`);
  }

  async _scrub() {
    if (!await this._confirm('Remove hidden information', "Take out the document's details (author, title, keywords), attached files, scripts, hidden text, and leftover data? Comments stay.", 'Remove')) return;
    await this.run('scrub', {}, 'Cleaning…');
  }

  _confirm(title, text, yes) {
    return new Promise((res) => {
      let answered = false;
      const d = modal(title, h('div', { class: 'pe-confirm' }, h('p', { text }),
        h('div', { class: 'pe-pop-foot' },
          h('button', { class: 'btn', text: 'Cancel', onclick: () => { answered = true; d.close(); res(false); } }),
          h('button', { class: 'btn primary', text: yes, onclick: () => { answered = true; d.close(); res(true); } }))), { width: 440 });
      const close = d.onClose;
      d.onClose = () => { close?.(); if (!answered) res(false); };
    });
  }

  // ================================================================== pages
  _sideOn() { if (!this.v.state.side) this.v._toggleSide(); }

  _pagesTools() {
    const b = (label, tip, run, icon) => h('button', { class: 'pv-btn', title: tip, html: `${icon ? ICON[icon] || icon : ''}<span>${label}</span>`, onclick: run });
    const n = this.picked.size;
    return [
      h('span', { class: 'pv-of', text: n ? `${n} page${n > 1 ? 's' : ''} picked` : 'This page', title: 'Pick pages in the side bar (Ctrl+click or Shift+click for several); drag them there to move them, right-click for more' }),
      h('span', { class: 'pv-sep' }),
      b('⟲', 'Turn left', () => this.run('pages_rotate', { pages: this._which(), by: 270 })),
      b('⟳', 'Turn right', () => this.run('pages_rotate', { pages: this._which(), by: 90 })),
      b('Delete', 'Take the pages out', () => this._pagesDelete()),
      b('Duplicate', 'Copy the pages, each after itself', () => this.run('pages_duplicate', { pages: this._which() })),
      h('span', { class: 'pv-sep' }),
      b('Blank page', 'Add a blank page after', () => this.run('pages_blank', { at: Math.max(...this._which()) + 1 })),
      b('Insert…', 'Add the pages of PDFs or pictures after (combine files)', () => this._insertFiles(Math.max(...this._which()) + 1)),
      b('Replace…', "Swap the pages for another file's", () => this._replace()),
      h('span', { class: 'pv-sep' }),
      b('Extract…', 'Save the pages as a new PDF', () => this._extract()),
      b('Split…', 'Split the document into several PDFs', () => this._split()),
      h('span', { class: 'pv-sep' }),
      this._btn('crop'),
      b('Uncrop', 'Show the whole of the pages again', () => this.run('pages_uncrop', { pages: this._which() })),
    ];
  }

  _which() { return this.picked.size ? [...this.picked].sort((a, b) => a - b) : [this.v.current || 0]; }

  async _pagesDelete() {
    const pages = this._which();
    if (!await this._confirm('Delete pages', `Take out ${pages.length === 1 ? `page ${pages[0] + 1}` : `${pages.length} pages`}?`, 'Delete')) return;
    await this.run('pages_delete', { pages });
  }

  async _insertFiles(at) {
    const r = await api.openFiles('pdf', 'Choose PDFs or pictures to insert').catch((e) => { toast(e.message, 'error'); return null; });
    if (!r?.files?.length) return;
    const res = await this.run('pages_insert_file', { at, paths: r.files.map((f) => f.path) }, 'Inserting…');
    if (res) toast(`Added ${res.result.added} page${res.result.added === 1 ? '' : 's'}.`);
  }

  async _replace() {
    const r = await api.openFiles('pdf', 'Choose the file with the new pages').catch(() => null);
    if (!r?.files?.length) return;
    const res = await this.run('pages_replace', { pages: this._which(), path: r.files[0].path });
    if (res) toast(`Replaced ${res.result.replaced} page${res.result.replaced === 1 ? '' : 's'}.`);
  }

  async _extract() {
    const pages = this._which(), stem = this.doc.name.replace(/\.pdf$/i, '');
    const name = pages.length === 1 ? `${stem} (page ${pages[0] + 1}).pdf` : `${stem} (pages).pdf`;
    const r = await api.savePdfDialog(name, 'Extract pages to').catch(() => null);
    if (!r?.path) return;
    const res = await this.run('pages_extract', { pages, path: r.path });
    if (res) this._saved(`Saved ${pages.length} page${pages.length === 1 ? '' : 's'} to ${r.path.split(/[\\/]/).pop()}.`, r.path);
  }

  _saved(msg, path) {
    const t = toast(msg, 'ok', 6000);
    if (this.v.app?.native !== false) t.append(h('button', { class: 'btn', text: 'Show', onclick: () => api.reveal(path) }));
  }

  _split() {
    const every = h('input', { class: 'pe-num', type: 'number', min: '1', value: '1' });
    const ranges = h('input', { class: 'pe-type', placeholder: 'or ranges, such as 1-3, 4-9, 10-', spellcheck: 'false' });
    [every, ranges].forEach((i) => i.addEventListener('keydown', (e) => e.stopPropagation()));
    const d = modal('Split the document', h('div', { class: 'pe-confirm' },
      h('p', { text: `Saves the pieces next to ${this.doc.name}, as "name (pages 1-3).pdf" and so on. The document itself stays as it is.` }),
      h('label', { class: 'pe-line' }, 'Every ', every, ' pages'), ranges,
      h('div', { class: 'pe-pop-foot' },
        h('button', { class: 'btn', text: 'Cancel', onclick: () => d.close() }),
        h('button', { class: 'btn primary', text: 'Split', onclick: async () => {
          const n = this.v.pagesInfo.length;
          let args = { every: Math.max(1, parseInt(every.value, 10) || 1) };
          if (ranges.value.trim()) {
            const list = ranges.value.split(',').map((x) => x.trim()).filter(Boolean).map((x) => {
              const [a, b] = x.split('-');
              return [parseInt(a, 10) || 1, b === undefined ? parseInt(a, 10) : b === '' ? n : parseInt(b, 10)];
            });
            if (list.some(([a, b]) => !a || !b)) { toast('Write the ranges like 1-3, 4-9, 10-', 'error'); return; }
            args = { ranges: list };
          }
          d.close();
          try {
            const r = await this._ask('split', args);
            this._saved(`Saved ${r.paths.length} PDF${r.paths.length === 1 ? '' : 's'}.`, r.paths[0]);
          } catch (e) { toast(e.message, 'error'); }
        } }))), { width: 460 });
  }

  _cropAsk(p, r) {
    const pages = this.picked.size > 1 && this.picked.has(p.i) ? this._which() : [p.i];
    const all = [...this.v.pagesInfo.keys()];
    const box = p.edit.getBoundingClientRect();
    menu(null, [
      { label: pages.length > 1 ? `Crop the ${pages.length} picked pages` : 'Crop this page', action: () => this.run('pages_crop', { pages: [p.i, ...pages.filter((i) => i !== p.i)], rect: r }) },
      { label: 'Crop every page the same', action: () => this.run('pages_crop', { pages: [p.i, ...all.filter((i) => i !== p.i)], rect: r }) },
      { sep: true }, { label: 'Cancel', action: () => {} },
    ], { at: { x: clamp(this._lastX ?? box.left + 40, 4, innerWidth - 240), y: clamp(this._lastY ?? box.top + 40, 4, innerHeight - 120) } });
  }

  // the page view's thumbnails: pick (Ctrl/Shift+click), drag to move, right-click for page tools
  thumb(t, i) {
    if (!this.editable) return;
    t.draggable = true;
    t.classList.toggle('pick', this.picked.has(i));
    t.addEventListener('click', (e) => {
      if (e.ctrlKey || e.metaKey) { if (this.picked.has(i)) this.picked.delete(i); else this.picked.add(i); }
      else if (e.shiftKey && this.lastPick != null) { for (let k = Math.min(i, this.lastPick); k <= Math.max(i, this.lastPick); k++) this.picked.add(k); }
      else { this.picked.clear(); this.picked.add(i); }
      this.lastPick = i;
      this._pickedChanged();
    });
    t.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      if (!this.picked.has(i)) { this.picked.clear(); this.picked.add(i); this._pickedChanged(); }
      const pages = this._which(), one = pages.length === 1;
      menu(t, [
        { label: 'Turn right', action: () => this.run('pages_rotate', { pages, by: 90 }) },
        { label: 'Turn left', action: () => this.run('pages_rotate', { pages, by: 270 }) },
        { sep: true },
        { label: 'Insert a blank page before', action: () => this.run('pages_blank', { at: pages[0] }) },
        { label: 'Insert a blank page after', action: () => this.run('pages_blank', { at: pages[pages.length - 1] + 1 }) },
        { label: 'Insert files after…', action: () => this._insertFiles(pages[pages.length - 1] + 1) },
        { label: 'Replace…', action: () => this._replace() },
        { sep: true },
        { label: 'Duplicate', action: () => this.run('pages_duplicate', { pages }) },
        { label: 'Extract…', action: () => this._extract() },
        { label: one ? 'Delete page' : `Delete ${pages.length} pages`, action: () => this._pagesDelete() },
      ]);
    });
    t.addEventListener('dragstart', (e) => {
      if (!this.picked.has(i)) { this.picked.clear(); this.picked.add(i); this._pickedChanged(); }
      e.dataTransfer.setData('text/x-pages', JSON.stringify(this._which()));
      e.dataTransfer.effectAllowed = 'move';
    });
    t.addEventListener('dragover', (e) => {
      if (!e.dataTransfer.types.includes('text/x-pages')) return;
      e.preventDefault();
      const r = t.getBoundingClientRect(), after = e.clientY > r.top + r.height / 2;
      this.v.side.querySelectorAll('.drop-before, .drop-after').forEach((n) => n.classList.remove('drop-before', 'drop-after'));
      t.classList.add(after ? 'drop-after' : 'drop-before');
    });
    t.addEventListener('dragleave', () => t.classList.remove('drop-before', 'drop-after'));
    t.addEventListener('drop', (e) => {
      const raw = e.dataTransfer.getData('text/x-pages');
      t.classList.remove('drop-before', 'drop-after');
      if (!raw) return;
      e.preventDefault();
      const r = t.getBoundingClientRect(), to = e.clientY > r.top + r.height / 2 ? i + 1 : i;
      this.run('pages_move', { pages: JSON.parse(raw), to });
    });
  }

  _pickedChanged() {
    this.v.side.querySelectorAll('.pv-thumb').forEach((n) => n.classList.toggle('pick', this.picked.has(+n.dataset.page)));
    if (this.set === 'pages') this._bar();
  }

  // ================================================================== the comments list
  togglePanel() {
    this.showPanel = !this.showPanel;
    keep('pe:panel', this.showPanel);
    this.panel.hidden = !this.showPanel;
    if (this.showPanel) this._renderPanel();
    this._bar();
    this.v._resized();
  }

  _label(a) {
    if (a.clouds) return 'Cloud';
    if (a.kind === 'line' && a.arrow) return 'Arrow';
    if (a.subject && !/^(Image Stamp|Stamp)$/.test(a.subject)) return a.subject.replace(/([a-z])([A-Z])/g, '$1 $2');
    return KIND_LABEL[a.kind] || a.kind;
  }

  _top() { return this.annots.filter((a) => !a.replyTo && a.kind !== 'popup'); }

  _renderPanel() {
    const top = this._top(), replies = (id) => this.annots.filter((a) => a.replyTo === id);
    const head = h('div', { class: 'pe-ph' }, h('b', { text: `Comments (${top.length})` }), h('span', { class: 'pv-grow' }),
      h('button', { class: 'pv-btn', text: '×', title: 'Close', onclick: () => this.togglePanel() }));
    if (!top.length) { this.panel.replaceChildren(head, h('p', { class: 'pe-empty', text: 'No comments yet. Pick a tool from Comment to add one.' })); return; }
    const list = h('div', { class: 'pe-list' });
    let page = -1;
    for (const a of top) {
      if (a.page !== page) { page = a.page; list.append(h('div', { class: 'pe-pg', text: `Page ${this.v.pagesInfo[page]?.label || page + 1}` })); }
      const words = h('div', { class: 'pe-words', text: a.contents || '', contenteditable: 'plaintext-only', 'data-ph': 'Add a comment' });
      words.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); words.blur(); } });
      words.addEventListener('blur', () => { const t = words.textContent; if (t !== (a.contents || '')) this.run(a.kind === 'text' ? 'annot_set' : 'annot_set', { page: a.page, id: a.id, ...(a.kind === 'text' ? { text: t } : { contents: t }) }); });
      const reply = h('input', { class: 'pe-reply', placeholder: 'Reply…', spellcheck: 'true' });
      reply.addEventListener('keydown', (e) => {
        e.stopPropagation();
        if (e.key === 'Enter' && reply.value.trim()) this.run('annot_reply', { page: a.page, id: a.id, contents: reply.value.trim() });
      });
      const item = h('div', { class: `pe-item${this.sel?.id === a.id && this.sel?.page === a.page ? ' on' : ''}` },
        h('div', { class: 'pe-meta' }, h('span', { class: 'pe-dot', style: { background: a.color || a.textColor || '#999' } }),
          h('b', { text: this._label(a) }), h('span', { text: a.author || '' }), h('span', { class: 'pv-grow' }),
          h('span', { class: 'pv-of', text: pdfDate(a.date) }),
          h('button', { class: 'pe-del', title: 'Delete', text: '×', onclick: (e) => { e.stopPropagation(); this.run('annot_delete', { page: a.page, ids: [a.id] }); } })),
        words,
        ...replies(a.id).map((r) => h('div', { class: 'pe-replyrow' }, h('b', { text: r.author || '' }), h('span', { text: ` ${r.contents}` }),
          h('button', { class: 'pe-del', title: 'Delete the reply', text: '×', onclick: () => this.run('annot_delete', { page: r.page, ids: [r.id] }) }))),
        reply);
      item.dataset.id = a.id;
      item.dataset.page = a.page;
      item.addEventListener('click', (e) => {
        if (e.target.closest('.pe-words, .pe-reply, .pe-del')) return;
        this.setTool('select');
        this.select({ type: 'annot', page: a.page, id: a.id, rect: a.rect, a });
        const p = this.v.pages[a.page];
        p.edit.querySelector('.pe-sel')?.scrollIntoView({ block: 'center', inline: 'nearest' });
      });
      list.append(item);
    }
    this.panel.replaceChildren(head, list);
  }

  // ================================================================== undo, redo and saving
  undo() { if (this.state?.undo) this.run('undo'); }
  redo() { if (this.state?.redo) this.run('redo'); }

  // whatever is being typed (a field, a box on the page) goes in, and every edit lands, before saving
  async _settle() {
    for (const el of this.fieldEls.values()) if (el.timer || document.activeElement === el) { el.timer = null; el.commit(); }
    this._endInline(true);
    if (this._nudge) { clearTimeout(this._nudge); this._nudge = null; if (this.sel) this._commitRect(this.sel.rect); }
    await this._q;
  }

  async save() {
    if (!this.editable) return false;
    await this._ready;
    await this._settle();
    if (this.doc.meta.pdf.saveAs) return this.saveAs();
    if (!this.state?.dirty) { toast('No changes to save.', 'info'); return true; }
    const r = await this.run('save', {}, 'Saving…');
    if (r) toast(`Saved ${this.doc.name}.`);
    return !!r;
  }

  async saveAs() {
    if (!this.editable) return false;
    await this._ready;
    await this._settle();
    const r = await api.savePdfDialog(this.doc.name, 'Save PDF As').catch((e) => { toast(e.message, 'error'); return null; });
    if (!r?.path) return false;
    const res = await this.run('save', { path: r.path }, 'Saving…');
    if (!res) return false;
    this.doc.path = r.path;
    this.doc.name = r.path.split(/[\\/]/).pop();
    this.doc.meta.path = r.path;
    this.doc.meta.name = this.doc.name;
    this.doc.meta.pdf.saveAs = false;
    this.v.app?.shell?.renderDocTabs();
    if (this.v.app) { document.title = `${this.doc.name} - ${PRODUCT}`; api.title(document.title); }
    toast(`Saved as ${this.doc.name}.`);
    return true;
  }
}
