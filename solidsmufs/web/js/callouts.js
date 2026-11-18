// Print Callouts, a tab of the left panel: what the part's print (an open PDF) calls out, found on the 3D model by size
// (kernel/callouts.py). Clicking a callout selects its faces; where several places fit, the user steps through them
// and keeps the right one, or selects faces and uses those. A tolerance heat map colors each face by the tightest
// tolerance on it, and labels put the callouts on the model. What the user picked is kept per part and print.
import * as THREE from 'three';
import { api } from './api.js';
import { h, toast } from './ui.js';

// tolerance bands (total, inches) for the heat map, tightest first
export const BANDS = [
  { max: 0.0005, color: '#d7263d', label: '≤ .0005' },
  { max: 0.001, color: '#f46036', label: '≤ .001' },
  { max: 0.002, color: '#f2b33d', label: '≤ .002' },
  { max: 0.005, color: '#5fad56', label: '≤ .005' },
  { max: Infinity, color: '#4d9de0', label: 'looser' },
];
const UNTOLERANCED = '#c8ccd2';
const TAG = 'callouts';

const rgb = (hex) => { const c = new THREE.Color(hex); return [c.r, c.g, c.b]; };
const bandOf = (b) => BANDS.find((x) => b <= x.max + 1e-9);
const STATUS = { one: 'Found', choices: 'Pick one', none: 'Not found', skip: 'Not on a face', off: 'Left out', mine: 'Your faces' };

export class Callouts {
  constructor(app) {
    this.app = app;
    this.body = null;
  }

  get doc() { return this.app.active; }
  get viewer() { return this.app.viewer; }

  // the state of one part's callouts, kept with the document
  st(doc = this.doc) {
    return doc.callouts ||= { print: null, list: null, res: null, unit: null, picks: {}, heat: false, labels: false, busy: null, guess: undefined, open: null };
  }

  _storeKey(doc, st) { return `callouts:${doc.path}|${st.printPath || ''}`; }
  _loadPicks(doc, st) { try { st.picks = JSON.parse(localStorage.getItem(this._storeKey(doc, st)) || '{}') || {}; } catch { st.picks = {}; } }
  _savePicks(doc, st) { try { localStorage.setItem(this._storeKey(doc, st), JSON.stringify(st.picks)); } catch { /* storage off */ } }

  _prints() { return this.app.docs.filter((d) => d.path && /\.pdf$/i.test(d.path) && d !== this.doc && !(d.meta?.pdf?.picture)); }

  // ================================================================== what each callout is on now
  /** {faces, at, what, size} the callout i is on (the user's pick, or what was found), or null. */
  effective(st, i, depth = 0) {
    const c = st.list[i], r = st.res[i];
    const pick = st.picks[c.key];
    if (pick?.off) return null;
    if (pick?.faces?.length) return { faces: pick.faces, what: `${pick.faces.length} face${pick.faces.length > 1 ? 's' : ''} you chose`, mine: true };
    if (r.via != null && depth < 2) return this.effective(st, r.via, depth + 1);
    if (r.status === 'one') return r.choices[0];
    if (r.status === 'choices' && pick?.i != null) return r.choices[pick.i] || null;
    return null;
  }

  statusOf(st, i) {
    const c = st.list[i], r = st.res[i], pick = st.picks[c.key];
    if (pick?.off) return 'off';
    if (pick?.faces?.length) return 'mine';
    if (r.via != null) return this.effective(st, i) ? 'one' : st.res[r.via]?.status === 'choices' ? 'choices' : 'none';
    return r.status === 'choices' && pick?.i != null ? 'one' : r.status;
  }

  // ================================================================== the panel
  render(body) {
    this.body = body;
    const doc = this.doc;
    if (!doc?.meta?.bodies?.length || doc.meta.drawing || (doc.meta.pdf && doc.pdfMode === 'pages')) {
      body.replaceChildren(h('div', { class: 'pm-msg', text: 'Open a 3D part to find its print\'s callouts on it.' }));
      return;
    }
    const st = this.st(doc);
    if (st.guess === undefined) {
      st.guess = null;
      api.printGuess(doc.id).then((r) => { st.guess = r.paths || []; if (this.doc === doc) this.refresh(); }).catch(() => { st.guess = []; });
    }
    const prints = this._prints();
    if (!st.print || !this.app.docs.includes(st.print)) { // the print: one already open that's named like the part
      st.print = null;
      const stem = (p) => (p || '').split(/[\\/]/).pop().replace(/\.[^.]+$/, '').toLowerCase();
      const mine = stem(doc.path), head = mine.split(/[\s_]+|(?<=.{4})-/)[0]; // its part number: "2402232" of "2402232-1_REV_XA"
      const named = prints.find((d) => stem(d.path) === mine) || prints.find((d) => stem(d.path).startsWith(mine))
        || (head.length >= 3 ? prints.find((d) => stem(d.path).startsWith(head)) : null);
      if (named || prints.length === 1) this.choose(named || prints[0], false);
    }
    const sel = h('select', { class: 'inp co-print', title: 'The print (an open PDF) to read the callouts from' },
      h('option', { value: '', text: prints.length ? 'Choose the print…' : 'No PDF is open' }),
      ...prints.map((d) => h('option', { value: d.id, text: d.name, selected: st.print === d })));
    sel.addEventListener('change', () => this.choose(this.app.docs.find((d) => d.id === sel.value) || null));
    const openBtn = h('button', { class: 'btn', text: 'Open…', title: 'Open the print (a PDF)', onclick: () => this.openPrint() });
    const beside = (st.guess || []).filter((p) => !this.app.docs.some((d) => d.path && d.path.toLowerCase() === p.toLowerCase()));
    const head = h('div', { class: 'co-head' },
      h('div', { class: 'co-row' }, h('span', { class: 'co-lbl', text: 'Print' }), sel, openBtn),
      beside.length && !st.print ? h('div', { class: 'co-beside' }, h('span', { text: 'Beside the part:' }),
        ...beside.slice(0, 3).map((p) => h('button', { class: 'co-link', text: p.split(/[\\/]/).pop(), title: p, onclick: () => this.openPrint(p) }))) : null,
      st.print ? h('div', { class: 'co-row' },
        h('button', { class: 'btn', text: st.list ? 'Read again' : 'Read the print', disabled: !!st.busy, onclick: () => this.read(true) }),
        h('label', { class: 'co-check', title: 'Color each face by the tightest tolerance called out on it' },
          h('input', { type: 'checkbox', checked: st.heat, disabled: !st.list, onchange: (e) => { st.heat = e.target.checked; this.apply(); this.refresh(); } }), 'Heat map'),
        h('label', { class: 'co-check', title: 'Show the callouts on the model' },
          h('input', { type: 'checkbox', checked: st.labels, disabled: !st.list, onchange: (e) => { st.labels = e.target.checked; this.apply(); } }), 'Labels')) : null);
    const parts = [head];
    if (st.busy) parts.push(h('div', { class: 'pm-msg co-busy', text: st.busy }));
    if (st.error) parts.push(h('div', { class: 'pm-msg co-err', text: st.error }));
    if (st.heat && st.list) parts.push(this._legend());
    if (st.list) parts.push(this._list(doc, st));
    else if (st.print && !st.busy) parts.push(h('div', { class: 'pm-msg', text: 'Read the print to list what it calls out and find each one on the part.' }));
    else if (!st.print) parts.push(h('div', { class: 'pm-msg', text: 'Open the part\'s print (a PDF) to find what it calls out on the model: hole sizes, threads, radii, lengths, angles and chamfers.' }));
    body.replaceChildren(h('div', { class: 'co' }, ...parts));
    if (st.print && !st.list && !st.busy && !st.error && st.auto !== false) { st.auto = false; this.read(false); }
  }

  refresh() { if (this.app.manager.tab === 'callouts' && this.body) this.render(this.body); }

  _legend() {
    return h('div', { class: 'co-legend', title: 'Total tolerance band, in inches (a feature control frame: its zone)' },
      ...BANDS.map((b) => h('span', { class: 'co-key' }, h('i', { style: { background: b.color } }), b.label)),
      h('span', { class: 'co-key' }, h('i', { style: { background: UNTOLERANCED } }), 'none'));
  }

  _list(doc, st) {
    const counts = {};
    st.list.forEach((_, i) => { const s = this.statusOf(st, i); counts[s] = (counts[s] || 0) + 1; });
    const sum = h('div', { class: 'co-sum' }, `${st.list.length} callout${st.list.length === 1 ? '' : 's'}${st.ballooned ? ' (the print\'s balloons)' : ''}: `,
      ['one', 'mine', 'choices', 'none', 'off'].filter((k) => counts[k]).map((k) => `${counts[k]} ${STATUS[k].toLowerCase()}`).join(', ') || 'none on a face',
      st.unit ? ` · read in ${st.unit === 'in' ? 'inches' : 'mm'}` : '');
    const rows = st.list.map((c, i) => this._row(doc, st, c, i));
    return h('div', {}, sum, h('div', { class: 'co-list' }, ...rows));
  }

  _row(doc, st, c, i) {
    const r = st.res[i], s = this.statusOf(st, i), eff = this.effective(st, i);
    const band = r.band != null ? bandOf(r.band) : null;
    const pick = st.picks[c.key] || {};
    const row = h('div', { class: `co-item s-${s}${st.open === i ? ' open' : ''}` },
      h('span', { class: 'co-n', text: c.label, style: band ? { borderColor: band.color } : null }),
      h('span', { class: 'co-text', text: c.text || c.type || '' }),
      h('span', { class: `co-st s-${s}`, text: s === 'choices' ? `${r.total} places` : STATUS[s] }));
    row.addEventListener('click', () => {
      st.open = st.open === i ? null : i;
      if (eff) this.app.setSelection(eff.faces.map((f) => ({ kind: 'face', index: f })));
      else if (r.status === 'choices' && r.via == null) this.app.setSelection(r.choices[0].faces.map((f) => ({ kind: 'face', index: f })));
      this.refresh();
    });
    if (st.open !== i) return row;
    const more = [];
    const tol = c.lo != null && c.hi != null ? `${c.lo} – ${c.hi}` : c.tol === 'basic' ? 'basic' : c.tol === 'ref' ? 'reference' : null;
    more.push(h('div', { class: 'co-what' }, [c.type, tol, c.page != null ? `sheet ${c.page + 1}` : null].filter(Boolean).join(' · ')));
    if (eff) more.push(h('div', { class: 'co-what' }, eff.what));
    else if (r.status === 'none' || (r.via != null && !eff)) more.push(h('div', { class: 'co-what', text: r.via != null ? `On the size it's attached to (${st.list[r.via].label}), which isn't placed yet.` : 'Nothing on the part is that size. Select its faces and use them.' }));
    else if (r.status === 'skip') more.push(h('div', { class: 'co-what', text: 'A note or finish: not found by size. Select its faces and use them if you like.' }));
    if (r.status === 'choices' && r.via == null && !pick.faces && !pick.off) {
      const at = pick.i ?? 0;
      const step = (k) => (e) => {
        e.stopPropagation();
        const n = Math.min(r.choices.length, r.total);
        const next = ((st.picks[c.key]?.i ?? 0) + k + n) % n;
        st.picks[c.key] = { i: next };
        this._savePicks(doc, st);
        this.app.setSelection(r.choices[next].faces.map((f) => ({ kind: 'face', index: f })));
        this.apply();
        this.refresh();
      };
      more.push(h('div', { class: 'co-row co-choose' },
        h('button', { class: 'btn', text: '‹', title: 'The place before', onclick: step(-1) }),
        h('span', { text: `${at + 1} of ${Math.min(r.choices.length, r.total)}${r.total > r.choices.length ? ` (of ${r.total})` : ''}: ${r.choices[at].what}` }),
        h('button', { class: 'btn', text: '›', title: 'The next place', onclick: step(1) }),
        pick.i == null ? h('button', { class: 'btn co-use', text: 'Use this', title: 'This is the place: keep it', onclick: step(0) }) : null));
      if (pick.i == null) more.push(h('div', { class: 'co-what', text: 'Step to the right place and use it: what you choose is kept.' }));
    }
    const act = (label, title, fn) => h('button', { class: 'btn', text: label, title, onclick: (e) => { e.stopPropagation(); fn(); this._savePicks(doc, st); this.apply(); this.refresh(); } });
    const faces = (this.app.sel || []).filter((x) => x.kind === 'face').map((x) => x.index);
    more.push(h('div', { class: 'co-row co-acts' },
      act('Use selected faces', faces.length ? `Put this callout on the ${faces.length} selected face(s)` : 'Select faces on the model first', () => {
        if (!faces.length) { toast('Select the faces on the model first, then use them.', 'info'); return; }
        st.picks[c.key] = { faces };
      }),
      pick.off ? act('Put back', 'Show this callout again', () => { delete st.picks[c.key]; })
        : act('Leave out', 'Not on this part (or not wanted): no color, no label', () => { st.picks[c.key] = { off: true }; }),
      pick.faces || pick.i != null ? act('Reset', 'Forget what you chose for this callout', () => { delete st.picks[c.key]; }) : null));
    return h('div', { class: 'co-wrap' }, row, h('div', { class: 'co-more', onclick: (e) => e.stopPropagation() }, ...more));
  }

  selectionChanged() { if (this.doc?.callouts?.open != null) this.refresh(); }

  // ================================================================== the print
  choose(print, reread = true) {
    const doc = this.doc, st = this.st(doc);
    if (st.print === print) return;
    st.print = print;
    st.printPath = print?.path || null;
    st.list = st.res = st.error = null;
    st.auto = true;
    this._loadPicks(doc, st);
    this.apply();
    if (reread) this.refresh();
  }

  async openPrint(path = null) {
    const doc = this.doc;
    if (!path) {
      try { path = (await api.openFiles('pdfonly', 'Open the print'))?.files?.[0]?.path; } catch (e) { toast(e.message, 'error'); return; }
      if (!path) return;
    }
    await this.app.openPath(path);
    const print = this.app.docs.find((d) => d.path && d.path.toLowerCase() === path.toLowerCase());
    if (this.app.active !== doc && this.app.docs.includes(doc)) this.app.activate(doc); // stay on the part
    if (print) { this.st(doc).print = null; this.choose(print); }
    this.app.manager.show('callouts');
  }

  async read(again) {
    const doc = this.doc, st = this.st(doc), print = st.print;
    if (!print || st.busy) return;
    st.error = null;
    const say = (t) => { st.busy = t; if (this.doc === doc) this.refresh(); };
    try {
      say('Waiting for the print to open…');
      for (let k = 0; k < 600 && !(print.meta && print.state === 'ready'); k++) {
        if (!this.app.docs.includes(print) || print.state === 'error') throw new Error(`${print.name} didn't open.`);
        await new Promise((r) => setTimeout(r, 300));
      }
      say('Reading the print… (a scanned print is read by OCR, which can take a minute)');
      const read = await api.pdfEdit(print.id, 'callouts');
      say('Finding each callout on the part…');
      const found = await api.callouts(doc.id, read.callouts, read.unit);
      if (st.print !== print) return; // another print chosen meanwhile
      Object.assign(st, { list: read.callouts, res: found.results, unit: found.unit, ballooned: read.ballooned });
      if (again) toast(`Read ${read.callouts.length} callouts.`);
    } catch (e) {
      st.error = e.message;
    } finally {
      st.busy = null;
      if (this.doc === doc) { this.apply(); this.refresh(); }
    }
  }

  // ================================================================== on the model
  /** Puts the active part's heat map and labels on the viewer (again after it's drawn anew). */
  apply() {
    const v = this.viewer, doc = this.doc;
    v.removeKeptLabels(TAG);
    const st = doc?.callouts;
    if (!st?.list || !v.model || doc.meta !== v.model.meta) { v.setFaceTint(null); return; }
    if (st.heat) {
      const tight = new Map();
      st.list.forEach((c, i) => {
        const e = this.effective(st, i), b = st.res[i].band;
        if (!e || b == null) return;
        for (const f of e.faces) if (!tight.has(f) || b < tight.get(f)) tight.set(f, b);
      });
      const tint = new Map(), grey = rgb(UNTOLERANCED);
      for (let f = 0; f < v.model.nF; f++) tint.set(f, tight.has(f) ? rgb(bandOf(tight.get(f)).color) : grey);
      v.setFaceTint(tint);
    } else v.setFaceTint(null);
    if (st.labels) {
      st.list.forEach((c, i) => {
        const e = this.effective(st, i);
        if (!e) return;
        const at = e.at ? new THREE.Vector3(...e.at) : v.faceCenter(e.faces[0]);
        if (!at) return;
        const band = st.res[i].band != null ? bandOf(st.res[i].band) : null;
        const el = v.addKeptLabel(at, '', 'co-label', TAG);
        el.append(h('b', { text: c.label }), ' ', c.text || '');
        if (band) el.style.borderLeftColor = band.color;
        el.title = `${c.type || ''}: ${e.what}`;
        el.addEventListener('click', () => { st.open = i; this.app.manager.show('callouts'); this.app.setSelection(e.faces.map((f) => ({ kind: 'face', index: f }))); });
      });
    }
  }
}
