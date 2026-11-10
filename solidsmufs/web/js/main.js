// SolidSmurfs: a SolidWorks-style part viewer. The App owns documents, selection, preferences and
// the command table; the shell (menus, CommandManager, heads-up toolbar, status bar), the managers
// (FeatureManager / PropertyManager), dialogs and the task pane all work through it.
import * as THREE from 'three';
import { api } from './api.js';
import { hydrate } from './icons.js';
import { Units } from './units.js';
import { h, toast, closeMenus, modal } from './ui.js';
import { Viewer } from './viewer.js';
import { Shell } from './shell.js';
import { Manager } from './manager.js';
import { Pages } from './pages.js';
import { Tools } from './tools.js';
import { TaskPane } from './taskpane.js';
import { ViewSelector } from './viewselector.js';
import { PdfView } from './pdfview.js';
import { PRODUCT, STYLES, SCENES, escapeHtml, clean, mergeSel } from './consts.js';

const DEFAULTS = {
  theme: 'light', system: 'MMGS', decimals: null, mouse: 'sw', wheelReverse: false, scene: 'auto',
  style: 'shadedEdges', silhouettes: true, realView: true, viewCube: false, perspective: false, upAxis: 'y', quality: 'normal',
  cmTab: 'view', mgrWidth: 270, hoverHighlight: true, contextToolbar: true,
};

class App {
  constructor() {
    this.$ = (id) => document.getElementById(id);
    this._hello = api.hello(); // asked for now, so the answer is in by the time the interface is built
    hydrate();
    this.prefs = { ...DEFAULTS };
    this.units = new Units('MMGS');
    this.viewer = new Viewer(this.$('viewport'));
    this.pdf = new PdfView(this.$('viewport'), (mode) => this.setPdfMode(mode));
    this.viewer.formatLength = (mm) => this.units.len(mm); // labels drawn in the graphics area use the document units
    this.docs = [];
    this.active = null;
    this.sel = [];
    this.measuring = false;
    this.commands = this._commands();
    this.shell = new Shell(this);
    this.manager = new Manager(this);
    this.pages = new Pages(this);
    this.tools = new Tools(this);
    this.taskpane = new TaskPane(this);
    this.selector = new ViewSelector(this);
    this._wireViewer();
    this._wireKeys();
    this._wireDrop();
    this._wireSplitter();
    this.refreshAll();
    this.boot();
  }

  // ================================================================== startup & preferences
  async boot() {
    try {
      const hello = await this._hello;
      console.info(`[timing] page ready (${performance.now() | 0} ms after navigation)`);
      this.native = hello.native;
      this.formats = hello.formats || [];
      this.recent = hello.recent || [];
      this.prefs = { ...DEFAULTS, ...(hello.ui || {}) };
      if (hello.ui && !hello.ui.system && hello.ui.units) this.prefs.system = hello.ui.units === 'in' ? 'IPS' : 'MMGS';
      this.applyPrefs();
      for (const d of hello.docs || []) this.attach(d.id, d);
      if (!hello.docs?.length) this.viewer.release();
      this.refreshAll();
      if (hello.browse) this.browse(hello.browse); // a zip it was started with, holding several files
    } catch (e) {
      this.viewer.release();
      toast(`Can't reach the viewer service: ${e.message}`, 'error');
    }
  }

  applyPrefs() {
    const p = this.prefs;
    document.documentElement.dataset.theme = p.theme;
    this.viewer.setTheme(p.theme);
    this.units.setSystem(p.system, p.decimals);
    this.viewer.setUpAxis(p.upAxis);
    this.setScene(p.scene, false);
    this.viewer.showSilhouettes = p.silhouettes !== false;
    this.viewer.setRealView(p.realView !== false);
    this.viewer.setStyle(p.style);
    this.viewer.setPerspective(!!p.perspective);
    this.viewer.showCube = !!p.viewCube;
    this.viewer.mouseMode = p.mouse;
    this.viewer.wheelReverse = !!p.wheelReverse;
    this.applySpace();
    this.$('workspace').style.setProperty('--mgr-w', `${p.mgrWidth || 270}px`);
    this.shell.selectTab(p.cmTab || 'view', false);
    this.viewer.requestRender();
  }

  // SpaceMouse directions from Options: camera mode reverses everything, then each axis its own way
  applySpace() {
    const p = this.prefs, all = p.spaceCamera ? -1 : 1, rev = p.spaceReverse || [];
    this.viewer.spaceSigns = [0, 1, 2, 3, 4, 5].map((i) => all * (rev[i] ? -1 : 1));
  }

  save(patch) {
    Object.assign(this.prefs, patch);
    api.settings(patch).catch(() => {});
  }

  setScene(id, persist = true) {
    const s = SCENES.find((x) => x.id === id) || SCENES[0];
    if (s.night && this.prefs.theme === 'dark') this.viewer.setBackgroundColors(s.night, true);
    else this.viewer.setBackgroundColors(s.bg, !!s.dark);
    this.prefs.scene = s.id;
    if (persist) this.save({ scene: s.id });
  }

  setTheme(theme) {
    this.save({ theme });
    document.documentElement.dataset.theme = theme;
    this.viewer.setTheme(theme);
    this.setScene(this.prefs.scene, false);
    this.shell.refresh?.();
    this.refreshAll();
  }

  setSystem(system, decimals = null) {
    this.units.setSystem(system, decimals);
    this.save({ system, decimals });
    if (this.viewer.shownBox) this.viewer.showBox(this.viewer.shownBox); // its size labels in the new units
    this.refreshAll();
    this.tools.refresh();
  }

  refreshAll() {
    this.shell.refresh();
    this.manager.refresh();
    this.taskpane.refresh();
    this.renderEmpty();
    this.renderLoading();
    this.status();
  }

  // ================================================================== documents
  // the model on show: a PDF's pages aren't one, so the part tools stay out of their way
  get meta() {
    const m = this.active?.meta;
    return m && !(m.pdf && this.active.pdfMode === 'pages') ? m : null;
  }
  get isAssembly() { return !!this.meta && this.meta.bodies.some((b) => (b.path || []).length > 1); }

  async openDialog() {
    if (!this.native) {
      const inp = h('input', { type: 'file', accept: (this.formats || []).join(',') });
      inp.addEventListener('change', () => { if (inp.files[0]) this.upload(inp.files[0]); });
      inp.click();
      return;
    }
    try {
      const r = await api.openDialog();
      if (r.path) this.openPath(r.path);
    } catch (e) { toast(e.message, 'error'); }
  }

  async openPath(path) {
    const existing = this.docs.find((d) => d.path && d.path.toLowerCase() === path.toLowerCase() && d.state !== 'error');
    if (existing) { this.activate(existing); return; }
    try {
      const st = await api.open(path, this.prefs.quality);
      if (st.browse) { this.browse(st.browse); return; } // a zip of several files: pick one
      this.recent = [{ path, name: st.name }, ...(this.recent || []).filter((r) => r.path.toLowerCase() !== path.toLowerCase())].slice(0, 15);
      this.attach(st.id, st);
    } catch (e) { toast(e.message, 'error'); }
  }

  async upload(file) {
    try {
      const st = await api.upload(file);
      if (st.browse) this.browse(st.browse); else this.attach(st.id, st);
    } catch (e) { toast(e.message, 'error'); }
  }

  /** Show what's in a zip (or a folder) in the File Explorer, to pick a file from. */
  browse(path) {
    this.taskpane.path = path;
    this.taskpane.show('explorer');
    toast('This zip holds several files: pick one to open.');
  }

  attach(id, st = null) {
    if (this.docs.some((d) => d.id === id)) return;
    const doc = { id, name: st?.name || 'Opening…', path: st?.path, state: 'loading', stage: st?.stage || 'Starting', fraction: 0,
      meta: null, blob: null, material: null, savedViews: [], rev: 0 };
    this.docs.push(doc);
    this.activate(doc);
    this.poll(doc, st);
  }

  async poll(doc, known = null) {
    while (this.docs.includes(doc)) {
      let st = known; // the status we were handed (from hello or open) saves the first round trip
      known = null;
      if (!st) {
        try { st = await api.status(doc.id); } catch (e) { st = { state: 'error', error: e.message }; }
      }
      const was = doc.state;
      // ask for the model before drawing anything, so it downloads while the page is busy
      const fetching = st.state === 'ready' && (was !== 'ready' || st.rev !== doc.rev || !doc.meta)
        ? Promise.all([api.meta(doc.id), api.mesh(doc.id)]) : null;
      Object.assign(doc, { name: st.name || doc.name, path: st.path || doc.path, state: st.state, stage: st.stage, fraction: st.fraction,
        error: st.error, elapsed: st.elapsed, exact: st.exact });
      if (this.active === doc) this.renderLoading();
      this.shell.renderDocTabs();
      if (fetching) {
        doc.rev = st.rev;
        doc.envelope = null; doc.envelopeKey = null;
        try {
          const [meta, blob] = await fetching;
          doc.meta = meta;
          doc.blob = blob;
          if (!doc.materialSet) { // the file's material, as SolidWorks shows it, until the user picks another
            doc.materialSet = true;
            if (meta.material && !doc.material) doc.material = { ...meta.material, fromFile: true };
          }
          if (this.active === doc) this.show(doc);
          console.info(`[timing] ${doc.name} handed to the viewer`);
          if (!doc.noticed && meta.notices?.length) { // once per open, e.g. assembly parts that weren't found
            doc.noticed = true;
            toast(`${doc.name}: ${meta.notices.join(' ')}`, 'warn', 9000);
          }
          if (meta.pdf?.dwgSetup && !doc.offered) { doc.offered = true; this.offerDwgSetup(doc); }
        } catch (e) {
          doc.state = 'error';
          doc.error = e.message;
          if (this.active === doc) this.renderLoading();
        }
        this.shell.renderDocTabs();
      }
      if (st.state === 'error') return;
      if (st.state === 'password') { this.askPassword(doc, st.locked); return; }
      if (st.state === 'ready' && st.exact) { this.status(); this.envelope(doc); return; } // fully loaded, exact geometry ready
      await new Promise((r) => setTimeout(r, st.state === 'ready' ? 600 : 200));
    }
  }

  // a protected PDF: asked for here rather than reported as an error, as many times as it takes
  askPassword(doc, reason) {
    const wrong = /doesn't open/.test(reason || '');
    const input = h('input', { class: 'inp', type: 'password', autocomplete: 'off', spellcheck: 'false', 'aria-label': 'Password' });
    let answered = false;
    const submit = async () => {
      answered = true;
      dialog.close();
      try {
        const st = await api.unlock(doc.id, input.value);
        doc.state = st.state;
        this.poll(doc, st);
      } catch (e) {
        toast(e.message, 'error');
        this.closeDoc(doc);
      }
    };
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); submit(); } });
    const dialog = modal('Password required', h('div', { class: 'pdf-pass' },
      h('p', { text: `"${doc.name}" is protected. Enter its password to open it.` }),
      wrong ? h('p', { class: 'pdf-pass-wrong', role: 'alert', text: "That password didn't work. Try again." }) : null,
      input,
      h('div', { class: 'pdf-pass-foot' },
        h('button', { class: 'btn', onclick: () => dialog.close(), text: 'Cancel' }),
        h('button', { class: 'btn primary', onclick: submit, text: 'Open' }))), { width: 400, icon: 'open' });
    const closed = dialog.onClose;
    dialog.onClose = () => { closed?.(); if (!answered) this.closeDoc(doc); };
    input.focus();
  }

  activate(doc) {
    if (this.active && this.active !== doc && this.active.meta?.bodies.length) this.active.view = this.viewer.rig.state();
    this.active = doc;
    this.tools.closeDocDialogs();
    this.pages.close(false);
    if (doc.meta) this.show(doc);
    else {
      this.$('workspace').classList.remove('pdf-doc');
      this.pdf.close();
      this.viewer.clear();
      this.sel = [];
      this.refreshAll();
    }
    this.shell.renderDocTabs();
  }

  show(doc) {
    this.sel = [];
    this.viewer.setSection(null);
    this.viewer.setAnalysis(null);
    const hasModel = doc.meta.bodies.length > 0;
    if (hasModel) this.viewer.setModel(doc.meta, doc.blob);
    else this.viewer.clear();
    if (doc.meta.pdf) {
      doc.pdfMode ||= hasModel ? 'model' : 'pages'; // a 3D PDF opens on its model, one click from its pages
      this.pdf.open(doc);
      this.$('workspace').classList.toggle('pdf-doc', doc.pdfMode === 'pages');
    } else {
      this.pdf.close();
      this.$('workspace').classList.remove('pdf-doc');
    }
    if (doc.view && hasModel) {
      this.viewer.rig.quat.copy(doc.view.quat);
      this.viewer.rig.target.copy(doc.view.target);
      this.viewer.rig.height = doc.view.height;
      this.viewer.rig.changed();
    }
    document.title = `${doc.name} - ${PRODUCT}`;
    api.title(document.title);
    this.refreshAll();
  }

  // a 3D PDF's two sides: its model, and its pages
  setPdfMode(mode) {
    const doc = this.active;
    if (!doc?.meta?.pdf || doc.pdfMode === mode) return;
    doc.pdfMode = mode;
    this.setSelection([]);
    this.tools.closeDocDialogs();
    this.pages.close(false);
    this.$('workspace').classList.toggle('pdf-doc', mode === 'pages');
    this.pdf.setMode(mode);
    this.refreshAll();
    requestAnimationFrame(() => this.viewer.requestRender());
  }

  async closeDoc(doc) {
    const i = this.docs.indexOf(doc);
    if (i < 0) return;
    this.docs.splice(i, 1);
    api.close(doc.id).catch(() => {});
    if (this.active === doc) {
      const next = this.docs[Math.min(i, this.docs.length - 1)];
      if (next) this.activate(next);
      else {
        this.active = null;
        this.$('workspace').classList.remove('pdf-doc');
        this.pdf.close();
        this.viewer.clear();
        this.sel = [];
        this.tools.closeDocDialogs();
        this.pages.close(false);
        document.title = PRODUCT;
        api.title(PRODUCT);
        this.refreshAll();
      }
    }
    this.shell.renderDocTabs();
  }

  // show another configuration of a SolidWorks part (like double-clicking one in the ConfigurationManager)
  setConfig(id) {
    if (!this.meta || this.meta.config === id) return;
    this.reload(this.prefs.quality, id);
  }

  /** A DWG shown as its thumbnail: offer to fetch the free converter that shows its lines (only on a click). */
  offerDwgSetup(doc) {
    const t = toast(`${doc.name} is showing its preview picture. To see its lines and measure them, SolidSmurfs can download the free ODA File Converter (about 32 MB, from opendesign.com) into your own folder. No admin is needed.`, 'info', 86400000); // stays until answered
    const go = h('button', { class: 'btn', text: 'Set it up' });
    const later = h('button', { class: 'btn', text: 'Not now', onclick: () => t.remove() });
    go.addEventListener('click', async () => {
      go.disabled = true;
      go.textContent = 'Setting up…';
      try {
        await api.dwgSetup();
        t.remove();
        toast('DWG drawings are set up. Opening the drawing again…');
        for (const d of this.docs.filter((x) => x.meta?.pdf?.dwgSetup)) { // every DWG open as a picture
          await api.reload(d.id, this.prefs.quality);
          Object.assign(d, { meta: null, state: 'loading', view: null, pdfMode: null, pdfState: null, envelope: null, envelopeKey: null });
          if (this.active === d) this.activate(d);
          this.poll(d);
        }
      } catch (e) {
        go.disabled = false;
        go.textContent = 'Try again';
        toast(e.message, 'error');
      }
    });
    t.append(go, later);
  }

  async reload(quality = this.prefs.quality, config) {
    const doc = this.active;
    if (!doc) return;
    try {
      await api.reload(doc.id, quality, config);
      doc.envelope = null; doc.envelopeKey = null;
      doc.meta = null;
      doc.state = 'loading';
      doc.view = this.viewer.rig.state();
      this.activate(doc);
      this.poll(doc);
    } catch (e) { toast(e.message, 'error'); }
  }

  // Align Part: turn the part so the picks face the given directions (refs null: back to as modelled)
  async realign(refs, targets) {
    const doc = this.active;
    if (!doc) return;
    if (refs) await api.align(doc.id, refs, targets);
    else await api.unalign(doc.id, this.prefs.quality);
    doc.envelope = null; doc.envelopeKey = null;
    doc.meta = null;
    doc.state = 'loading';
    doc.view = null;  // a fresh fit of the turned part
    this.setSelection([]);
    this.activate(doc);
    this.poll(doc);
  }

  // ================================================================== selection
  _wireViewer() {
    const v = this.viewer;
    v.onHover = (hit) => {
      this.hovered = hit;
      v.setHover(this.prefs.hoverHighlight !== false ? hit : null);
      this.statusXYZ(hit);
    };
    v.onClick = (hit, e, p) => this.click(hit, e, p);
    v.onDoubleClick = (hit) => {
      if (!hit) { v.fitAll(); return; }
      const f = this.meta.faces;
      if (hit.kind === 'face' && f.type[hit.index] === 'plane' && f.params[hit.index]) v.normalTo(f.params[hit.index].normal);
      else v.fitBox(v.entityBox(hit));
    };
    v.onContext = (hit, e, p) => this.contextMenu(hit, e, p);
    v.onBoxSelect = (ents, add) => this.setSelection(add ? mergeSel(this.sel, ents) : ents);
    v.onGesture = (cmd) => this.run(cmd);
    v.onModeDone = () => { v.mode = 'select'; this.shell.refresh(); };
    v.onViewChange = () => this.shell.placeContextToolbar();
  }

  click(hit, e, p) {
    if (this.selector.active) return;
    const same = (a, b) => a.kind === b.kind && a.index === b.index && a.kind !== 'point';
    if (!hit) {
      if (this.sel.length && !this.measuring) this.setSelection([]);
      else if (this.measuring && this.sel.length) this.setSelection([]);
      return;
    }
    let ent = { kind: hit.kind, index: hit.index };
    if (this.measuring && this.tools.pointToPoint && hit.kind === 'face' && hit.point) {
      ent = { kind: 'point', index: -1, point: hit.point, face: hit.index };
    }
    const additive = this.measuring || e.ctrlKey || e.shiftKey;
    let next;
    if (additive) {
      const i = this.sel.findIndex((s) => same(s, ent));
      next = i >= 0 ? this.sel.filter((_, k) => k !== i) : [...this.sel, ent];
    } else next = this.sel.length === 1 && same(this.sel[0], ent) ? [] : [ent];
    this.setSelection(next, p);
  }

  setSelection(list, at = null) {
    this.sel = list;
    this.viewer.setSelection(list);
    this.manager.selectionChanged();
    this.tools.selectionChanged();
    this.pages.selectionChanged();
    this.shell.selectionChanged(at);
    this.quickMeasure();
  }

  // the visible bodies' best-fit size and volumes, shown in the status bar whenever nothing is selected
  // (for stock); worked out again when bodies are hidden or shown, like Bounding Box and Stock Size
  visibleKey(doc = this.active) {
    if (!doc?.meta || this.active !== doc) return '';
    return doc.meta.bodies.map((_, i) => (this.viewer.bodies[i]?.visible === false ? 0 : 1)).join('');
  }

  async envelope(doc) {
    const key = this.visibleKey(doc);
    if (!doc.meta || doc.envelopeKey === key) return;
    doc.envelopeKey = key;
    const shown = doc.meta.bodies.map((_, i) => i).filter((i) => key[i] !== '0');
    if (!shown.length) { doc.envelope = null; this.status(); return; }
    try {
      const [box, mass] = await Promise.all([api.bbox(doc.id, shown, 'oriented'), api.massprops(doc.id, shown, 1.0)]);
      if (!box || doc.envelopeKey !== key) return;
      const size = [...box.size].sort((a, b) => b - a);
      doc.envelope = { size, box: size[0] * size[1] * size[2], part: mass?.volume, partial: shown.length < doc.meta.bodies.length };
    } catch { doc.envelopeKey = null; return; }
    if (this.active === doc) this.status();
  }

  // SolidWorks shows a quick measurement of the selection in the status bar
  async quickMeasure() {
    const token = (this._qm = (this._qm || 0) + 1);
    const sel = this.sel.filter((s) => s.kind !== 'body' && s.kind !== 'plane' && s.kind !== 'origin');
    this.quick = null;
    if (!sel.length || !this.active?.meta) { this.status(); return; }
    try {
      const r = await api.measure(this.active.id, sel.map(clean), this.tools.measureOpts(sel));
      if (token !== this._qm) return;
      this.quick = r;
    } catch { if (token !== this._qm) return; }
    this.status();
  }

  planarSelection() {
    const f = this.meta?.faces;
    return this.sel.find((s) => s.kind === 'face' && f.type[s.index] === 'plane' && f.params[s.index]) || null;
  }

  selectedBodies() {
    const m = this.meta;
    if (!m) return [];
    const out = new Set();
    for (const s of this.sel) {
      if (s.kind === 'body') out.add(s.index);
      else if (s.kind === 'face') out.add(m.faces.body[s.index]);
      else if (s.kind === 'edge') { const fs = m.edges.faces[s.index]; if (fs.length) out.add(m.faces.body[fs[0]]); }
    }
    return [...out];
  }

  normalTo() {
    const pf = this.planarSelection();
    if (pf) this.viewer.normalTo(this.meta.faces.params[pf.index].normal);
    else {
      const plane = this.sel.find((s) => s.kind === 'plane');
      if (plane) this.viewer.normalTo(this.viewer.planeNormal(plane.index));
      else toast('Select a flat face or a plane first', 'info');
    }
  }

  zoomToSelection() {
    if (!this.sel.length) { this.viewer.fitAll(); return; }
    const box = new THREE.Box3();
    for (const s of this.sel) {
      if (s.kind === 'body') box.union(this.viewer.bodyBox(s.index));
      else if (s.kind === 'face' || s.kind === 'edge' || s.kind === 'vertex' || s.kind === 'point') box.union(this.viewer.entityBox(s));
    }
    this.viewer.fitBox(box);
  }

  hideBodies(bodies) {
    bodies.forEach((b) => this.viewer.setBodyVisible(b, false));
    this.setSelection(this.sel.filter((s) => s.kind !== 'body' || !bodies.includes(s.index)));
    this.manager.refresh();
  }

  showAll() { this.viewer.showAll(); this.manager.refresh(); }
  isolate(bodies) { this.viewer.isolate(bodies); this.manager.refresh(); this.viewer.fitAll(); }
  toggleTransparent(bodies) {
    for (const b of bodies) { const body = this.viewer.bodies[b]; if (body) this.viewer.setBodyOpacity(b, body.opacity < 1 ? 1 : 0.35); }
    this.manager.refresh();
  }

  contextMenu(hit, e, p) {
    if (!this.meta) return;
    const before = this.sel;
    if (hit && !this.sel.some((s) => s.kind === hit.kind && s.index === hit.index) && !this.measuring) this.setSelection([{ kind: hit.kind, index: hit.index }]);
    const bodies = this.selectedBodies();
    const items = [];
    if (hit) {
      items.push({ head: this.describe(hit, true) });
      const under = p ? this.viewer.facesUnder(p.x, p.y) : [];
      if (under.length > 1) items.push({ label: 'Select Other', icon: 'select', sub: () => this.selectOtherItems(under, before) });
      if (this.planarSelection()) items.push({ label: 'Normal To', icon: 'normalTo', kb: 'Ctrl+8', action: () => this.normalTo() });
      items.push({ label: 'Zoom to Selection', icon: 'zoomFit', action: () => this.zoomToSelection() });
      items.push({ label: 'Measure', icon: 'measure', action: () => this.run('measure') });
      if (bodies.length) {
        items.push({ sep: true });
        items.push({ label: 'Hide Body', icon: 'hide', kb: 'Tab', action: () => this.hideBodies(bodies) });
        items.push({ label: 'Isolate', icon: 'isolate', action: () => this.isolate(bodies) });
        items.push({ label: 'Change Transparency', icon: 'transparency', action: () => this.toggleTransparent(bodies) });
        items.push({ label: 'Appearance…', icon: 'appearance', action: () => this.run('appearance') });
        items.push({ label: 'Select Body', icon: 'body', action: () => this.setSelection(bodies.map((b) => ({ kind: 'body', index: b }))) });
      }
      items.push({ sep: true });
    }
    items.push({ label: 'Show All', icon: 'showAll', kb: 'Ctrl+Shift+H', action: () => this.showAll() });
    items.push({ label: 'Zoom to Fit', icon: 'zoomFit', kb: 'F', action: () => this.viewer.fitAll() });
    items.push({ label: 'View Orientation', icon: 'orientation', kb: 'Space', action: () => this.selector.open() });
    items.push({ label: 'Display Style', icon: 'displayStyle', sub: () => this.styleItems() });
    this.shell.menuAt(items, e.clientX, e.clientY);
  }

  // SolidWorks' Select Other: every face under the cursor, front to back; hovering one highlights it
  selectOtherItems(faces, before) {
    const same = (a, b) => a.kind === b.kind && a.index === b.index;
    return faces.map((f, i) => ({
      label: `${this.describe(f, true)}${i === 0 ? ' (front)' : ''}`,
      hover: () => this.viewer.setHover(f),
      action: () => {
        this.viewer.setHover(null);
        const keep = this.measuring ? before.filter((s) => !same(s, f)) : [];
        this.setSelection([...keep, f]);
      },
    }));
  }

  styleItems() {
    return STYLES.map((s) => ({ label: s.label, icon: s.icon, check: this.viewer.style === s.id, action: () => this.setStyle(s.id) }));
  }

  setStyle(id) { this.viewer.setStyle(id); this.save({ style: id }); this.shell.refresh(); }

  // ================================================================== commands
  run(id, anchor) {
    const c = this.commands[id];
    if (!c) return;
    if (c.needsDoc && !this.meta) { toast('Open a part first', 'info'); return; }
    closeMenus();
    c.run(anchor);
  }

  _commands() {
    const v = () => this.viewer;
    const C = {};
    const def = (id, o) => { C[id] = { id, needsDoc: true, ...o }; };
    // file
    def('open', { label: 'Open', icon: 'open', kb: 'Ctrl+O', tip: 'Open a part, assembly or mesh file', needsDoc: false, run: () => this.openDialog() });
    def('reload', { label: 'Rebuild', icon: 'reload', kb: 'Ctrl+B', tip: 'Read the file again from disk', run: () => this.reload() });
    def('close', { label: 'Close', icon: 'close', kb: 'Ctrl+W', tip: 'Close the active document', run: () => this.active && this.closeDoc(this.active) });
    def('closeAll', { label: 'Close All', icon: 'close', tip: 'Close every open document', needsDoc: false, run: () => [...this.docs].forEach((d) => this.closeDoc(d)) });
    def('print', { label: 'Print', icon: 'print', kb: 'Ctrl+P', tip: "A PDF's pages, or the model as shown on white", needsDoc: false, run: () => this.print() });
    def('savePicture', { label: 'Save Picture', icon: 'camera', tip: 'Save the graphics area as a PNG', run: () => this.savePicture() });
    def('saveStep', { label: 'Save As STEP', icon: 'file', tip: 'Save the part or assembly as a STEP file, for anyone without SolidWorks', run: () => this.saveStep() });
    def('copyPicture', { label: 'Copy Picture', icon: 'camera', kb: 'Ctrl+Shift+C', tip: 'Copy the graphics area to the clipboard', run: () => this.copyPicture() });
    def('fileProps', { label: 'File Properties', icon: 'props', tip: 'File, format and model statistics', run: () => this.taskpane.show('props') });
    def('options', { label: 'Options', icon: 'options', tip: 'System options and document properties', needsDoc: false, run: () => this.tools.options() });
    def('help', { label: 'Mouse and Keyboard', icon: 'select', kb: 'F1', tip: 'How to move around and every shortcut', needsDoc: false, run: () => this.tools.help() });
    def('about', { label: `About ${PRODUCT}`, icon: 'props', needsDoc: false, run: () => this.tools.about() });
    // view
    def('zoomFit', { label: 'Zoom to Fit', icon: 'zoomFit', kb: 'F', tip: 'Fit the whole model in the window', run: () => v().fitAll() });
    def('zoomArea', { label: 'Zoom to Area', icon: 'zoomArea', tip: 'Drag a box to zoom into', toggle: () => v().mode === 'zoomArea', run: () => { v().mode = v().mode === 'zoomArea' ? 'select' : 'zoomArea'; this.shell.refresh(); this.status(); } });
    def('prevView', { label: 'Previous View', icon: 'prevView', kb: 'Ctrl+Shift+Z', tip: 'Go back to the last view', run: () => v().rig.previous() });
    def('zoomSel', { label: 'Zoom to Selection', icon: 'zoomFit', tip: 'Fit the selected items', run: () => this.zoomToSelection() });
    def('orientation', { label: 'View Orientation', icon: 'orientation', kb: 'Space', tip: 'Standard views and the View Selector', menu: () => this.shell.viewsMenuItems(), run: () => this.selector.open() });
    def('normalTo', { label: 'Normal To', icon: 'normalTo', kb: 'Ctrl+8', tip: 'Look straight at the selected flat face or plane', run: () => this.normalTo() });
    for (const [id, label, kb] of [['front', 'Front', 'Ctrl+1'], ['back', 'Back', 'Ctrl+2'], ['left', 'Left', 'Ctrl+3'], ['right', 'Right', 'Ctrl+4'],
      ['top', 'Top', 'Ctrl+5'], ['bottom', 'Bottom', 'Ctrl+6'], ['iso', 'Isometric', 'Ctrl+7'], ['dimetric', 'Dimetric', ''], ['trimetric', 'Trimetric', '']]) {
      def(id, { label, icon: id, kb, tip: `${label} view`, run: () => v().setView(id) });
    }
    def('sectionView', { label: 'Section View', icon: 'sectionView', tip: 'Cut the model with a plane', toggle: () => !!v().section, run: () => this.pages.toggleSection() });
    def('displayStyle', { label: 'Display Style', icon: 'displayStyle', kb: 'D', tip: 'Shaded, edges, hidden lines, wireframe', menu: () => this.styleItems(),
      run: () => { const i = STYLES.findIndex((s) => s.id === v().style); this.setStyle(STYLES[(i + 1) % STYLES.length].id); } });
    for (const s of STYLES) def(s.id, { label: s.label, icon: s.icon, tip: s.label, run: () => this.setStyle(s.id) });
    def('hideShow', { label: 'Hide/Show Items', icon: 'hideShow', tip: 'Bodies, planes and origin', menu: () => this.shell.hideShowItems(), run: () => this.showAll() });
    def('showAll', { label: 'Show All', icon: 'showAll', kb: 'Ctrl+Shift+H', tip: 'Show every body', run: () => this.showAll() });
    def('hideSel', { label: 'Hide Selected', icon: 'hide', kb: 'Tab', tip: 'Hide the selected bodies (or the one under the cursor)', run: () => this.hideBodies(this.selectedBodies()) });
    def('isolate', { label: 'Isolate', icon: 'isolate', tip: 'Show only the selected bodies', run: () => this.isolate(this.selectedBodies()) });
    def('appearance', { label: 'Edit Appearance', icon: 'appearance', tip: 'Color and transparency of bodies', run: () => this.pages.appearance() });
    def('scene', { label: 'Apply Scene', icon: 'scene', tip: 'Background of the graphics area', menu: () => SCENES.map((s) => ({ label: s.label, check: this.prefs.scene === s.id, action: () => { this.setScene(s.id); this.taskpane.refresh(); } })), run: () => this.taskpane.show('appearance') });
    def('viewSettings', { label: 'View Settings', icon: 'viewSettings', tip: 'Perspective, silhouettes, view cube', menu: () => this.shell.viewSettingsItems(), run: () => this.tools.options('display') });
    def('realView', { label: 'RealView Graphics', icon: 'appearance', tip: 'Show the colors, finishes and materials saved in the file', toggle: () => v().realView, run: () => { const on = !v().realView; v().setRealView(on); this.save({ realView: on }); this.shell.refresh(); } });
    def('perspective', { label: 'Perspective', icon: 'perspective', kb: 'P', tip: 'Perspective or orthographic view', toggle: () => v().rig.perspective, run: () => { const on = !v().rig.perspective; v().setPerspective(on); this.save({ perspective: on }); this.shell.refresh(); } });
    def('fmToggle', { label: 'FeatureManager Tree', icon: 'featureMgr', kb: 'F9', tip: 'Show or hide the left panel', needsDoc: false, run: () => this.shell.toggleManager() });
    def('taskPane', { label: 'Task Pane', icon: 'tpHome', tip: 'Show or hide the task pane', needsDoc: false, run: () => this.taskpane.toggle() });
    def('theme', { label: 'Dark Interface', icon: 'viewSettings', tip: 'Switch between light and dark', needsDoc: false, toggle: () => this.prefs.theme === 'dark', run: () => this.setTheme(this.prefs.theme === 'dark' ? 'light' : 'dark') });
    // evaluate
    def('measure', { label: 'Measure', icon: 'measure', tip: 'Distances, angles, radii and coordinates', toggle: () => this.measuring, run: () => this.tools.measure() });
    def('massProps', { label: 'Mass Properties', icon: 'massProps', tip: 'Mass, volume, center of mass, inertia', run: () => this.tools.massProps() });
    def('sectionProps', { label: 'Section Properties', icon: 'sectionProps', tip: 'Area properties of selected flat faces', run: () => this.tools.sectionProps() });
    def('bbox', { label: 'Bounding Box', icon: 'bbox', tip: 'Exact overall size, or the tightest box', run: () => this.pages.boundingBox() });
    def('statistics', { label: 'Statistics', icon: 'statistics', tip: 'Bodies, faces, edges and surface types', run: () => this.tools.statistics() });
    def('draft', { label: 'Draft Analysis', icon: 'draft', tip: 'Color faces by draft angle', toggle: () => v().analysis?.type === 'draft', run: () => this.pages.draft() });
    def('zebra', { label: 'Zebra Stripes', icon: 'zebra', tip: 'Check surface smoothness', toggle: () => v().analysis?.type === 'zebra', run: () => this.pages.zebra() });
    def('curvature', { label: 'Curvature', icon: 'curvature', tip: 'Color the model by curvature', toggle: () => v().analysis?.type === 'curvature', run: () => this.pages.curvature() });
    // Tools tab (stock, holes, quote)
    def('align', { label: 'Align Part', icon: 'normalTo', tip: 'Turn the part so picked faces face Top / Front / Right', run: () => this.pages.alignPart() });
    def('stock', { label: 'Stock Size', icon: 'stock', tip: 'Smallest block the part fits in, with allowance', run: () => this.tools.stock() });
    def('holes', { label: 'Hole Report', icon: 'holes', tip: 'Every hole by diameter, with drill and tap matches', run: () => this.tools.holes() });
    def('quote', { label: 'Quote Summary', icon: 'quote', tip: 'Size, volume, weight and holes in one copyable list', run: () => this.tools.quote() });
    def('material', { label: 'Edit Material', icon: 'material', tip: 'Material for mass properties', run: () => this.tools.material() });
    def('explorer', { label: 'File Explorer', icon: 'tpExplorer', tip: 'Browse folders for parts', needsDoc: false, run: () => this.taskpane.show('explorer') });
    return C;
  }

  // ================================================================== pictures
  async copyPicture() {
    if (!this.meta) return;
    const url = this.viewer.screenshot(2);
    try {
      const blob = await (await fetch(url)).blob();
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
      toast('Picture copied to the clipboard');
    } catch { toast("Couldn't copy the picture; try Save Picture", 'warn'); }
  }

  async savePicture() {
    if (!this.meta) return;
    const url = this.viewer.screenshot(2);
    const name = `${(this.active?.name || 'view').replace(/\.[^.]+$/, '')}.png`;
    if (!this.native) { h('a', { href: url, download: name }).click(); return; }
    try {
      const r = await api.saveImage(url, name);
      if (r.path) toast(`Saved ${r.path.split(/[\\/]/).pop()}`);
    } catch (e) { toast(e.message, 'error'); }
  }

  // ================================================================== printing
  /** What's on show, on paper: a PDF's or picture's pages (all of them, or the range asked for), or the
   *  model as it's shown, on white. */
  async print() {
    const doc = this.active;
    if (!doc?.meta) { toast('Open a file first', 'info'); return; }
    if (!this.native) { toast('Printing needs the desktop window.', 'warn'); return; }
    const pages = doc.meta.pdf && doc.pdfMode === 'pages';
    if (!pages && !doc.meta.bodies.length) { toast('There is nothing to print yet.', 'warn'); return; }
    const name = doc.name;
    let busy = null;
    const later = setTimeout(() => { busy = toast(`Printing ${name}…`, 'info', 600000); }, 1500); // after the dialog
    try {
      const r = pages ? await api.printPages(doc.id) : await api.printImage(this.viewer.printPicture(), name);
      if (r.sheets) toast(`Sent ${name} to the printer (${r.sheets} ${r.sheets === 1 ? 'sheet' : 'sheets'})`);
    } catch (e) { toast(e.message, 'error'); } finally { clearTimeout(later); busy?.remove?.(); }
  }

  /** For printing from the command line: a picture of a document's model on white, once it's on show; null
   *  until then (each call moves it along). */
  printPicture(id) {
    const doc = this.docs.find((d) => d.id === id);
    if (!doc?.meta?.bodies?.length) return null;
    if (this.active !== doc) { this.activate(doc); doc.printShown = performance.now(); return null; }
    if (doc.meta.pdf && doc.pdfMode === 'pages') { this.setPdfMode('model'); doc.printShown = performance.now(); return null; }
    doc.printShown ||= performance.now();
    if (performance.now() - doc.printShown < 1500) return null; // let the fit and the silhouettes settle
    return this.viewer.printPicture();
  }

  async saveStep() {
    const doc = this.active;
    if (!doc?.meta || doc.meta.kind !== 'brep') { toast('Only CAD parts and assemblies can be saved as STEP.', 'warn'); return; }
    if (!this.native) { toast('Save As STEP needs the desktop window.', 'warn'); return; }
    const done = toast(`Saving ${doc.name} as STEP…`, 'info', 60000);
    try {
      const r = await api.saveStep(doc.id);
      done?.remove?.();
      if (r.path) toast(`Saved ${r.path.split(/[\\/]/).pop()}`);
    } catch (e) { done?.remove?.(); toast(e.message, 'error'); }
  }

  // ================================================================== status bar
  describe(ent, short = false) {
    const m = this.meta;
    if (!m || !ent) return '';
    const u = this.units;
    if (ent.kind === 'face') {
      const t = m.faces.type[ent.index], p = m.faces.params[ent.index] || {};
      const name = { plane: 'Plane', cylinder: 'Cylinder', cone: 'Cone', sphere: 'Sphere', torus: 'Torus', bspline: 'Spline surface', mesh: 'Mesh face' }[t] || 'Surface';
      let dim = '';
      if ((t === 'cylinder' || t === 'sphere') && p.radius) dim = ` Ø${u.len(p.radius * 2)}`;
      return short ? `Face<${ent.index + 1}> ${name}` : `<b>Face&lt;${ent.index + 1}&gt;</b> ${name}${dim}`;
    }
    if (ent.kind === 'edge') {
      const t = m.edges.type[ent.index], p = m.edges.params[ent.index] || {};
      const name = t === 'circle' ? (p.closed ? 'Circle' : 'Arc') : t === 'line' ? 'Line' : t === 'bspline' ? 'Spline' : 'Curve';
      return short ? `Edge<${ent.index + 1}> ${name}` : `<b>Edge&lt;${ent.index + 1}&gt;</b> ${name}`;
    }
    if (ent.kind === 'vertex') return short ? `Vertex<${ent.index + 1}>` : `<b>Vertex&lt;${ent.index + 1}&gt;</b>`;
    if (ent.kind === 'point') return short ? 'Point' : '<b>Point</b>';
    if (ent.kind === 'body') return short ? m.bodies[ent.index].name : `<b>${escapeHtml(m.bodies[ent.index].name)}</b>`;
    if (ent.kind === 'plane') return short ? this.viewer.planeName(ent.index) : `<b>${this.viewer.planeName(ent.index)}</b>`;
    return '';
  }

  status() {
    const el = this.$('sb-msg');
    const u = this.units;
    let html = '';
    if (this.viewer.mode === 'zoomArea') html = 'Drag a box to zoom into it.';
    else if (this.quick?.rows?.length) {
      const rows = this.quick.rows.filter((r) => r.status || (r.kind !== 'text' && r.kind !== 'vector'));
      const pick = [...rows.filter((r) => r.primary), ...rows.filter((r) => !r.primary)].slice(0, 4);
      html = pick.map((r) => `${r.label}: <b>${escapeHtml(u.value(r))}</b>`).join('<span class="sep">|</span>');
    } else if (this.sel.length > 1) html = `${this.sel.length} items selected`;
    else if (this.sel.length === 1) html = this.describe(this.sel[0]);
    else if (this.meta && this.active?.envelope) {
      const e = this.active.envelope;
      if (this.active.exact && this.active.envelopeKey !== this.visibleKey()) setTimeout(() => this.envelope(this.active), 0);
      html = `${e.partial ? 'Shown bodies — size' : 'Size'}: <b>${e.size.map((x) => u.len(x, false)).join(' × ')} ${u.label}</b><span class="sep">|</span>Box volume: <b>${u.vol(e.box)}</b>`;
      if (e.part > 0) html += `<span class="sep">|</span>Part volume: <b>${u.vol(e.part)}</b> (${Math.round((100 * e.part) / e.box)}% of box)`;
    } else if (this.meta) html = this.prefs.mouse === 'sw'
      ? 'Middle-drag to rotate · Ctrl+middle to pan · Wheel to zoom · Right-drag for gestures'
      : 'Drag to rotate · Right-drag to pan · Wheel to zoom';
    else if (this.active?.meta?.pdf && this.active.pdfMode === 'pages') html = `Drag to pan · ${this.active.meta.pdf.picture ? '' : 'Shift+drag to select text · '}${this.active.meta.pdf.pages.length > 1 ? 'Ctrl+wheel' : 'Wheel'} to zoom`;
    else html = 'Open a part to begin.';
    if (this.active && this.active.state === 'ready' && this.active.exact === false) html += '<span class="sep">|</span>Loading exact geometry for measuring…';
    el.innerHTML = html;
    this.$('sb-mode').textContent = this.meta ? (this.isAssembly ? 'Editing Assembly' : 'Editing Part') : '';
    this.$('sb-units').textContent = this.units.system === 'Custom' ? 'Custom' : this.units.system;
  }

  statusXYZ(hit) {
    const el = this.$('sb-xyz');
    if (hit?.point) {
      const u = this.units, p = hit.point;
      el.innerHTML = `X <b>${u.len(p[0], false)}</b>  Y <b>${u.len(p[1], false)}</b>  Z <b>${u.len(p[2], false)}</b> ${u.label}`;
    } else el.textContent = '';
  }

  renderEmpty() {
    const el = this.$('empty');
    if (this.active) { el.hidden = true; return; }
    el.hidden = false;
    const recent = (this.recent || []).slice(0, 8);
    el.replaceChildren(h('div', { class: 'welcome' },
      h('div', { class: 'wl-brand' },
        h('img', { src: 'img/icon.svg', alt: '' }),
        h('div', {}, h('div', { class: 'wl-title', text: PRODUCT }),
          h('div', { class: 'wl-by', text: 'by Wagner Machine Co.' }),
          h('div', { class: 'wl-sub', text: 'The difficult we do right away, the impossible will take a little longer.' }))),
      h('div', { class: 'wl-card' }, h('div', { class: 'wl-row' },
        h('div', { class: 'wl-actions' },
          this.shell.bigButton('open', 'Open…'),
          this.shell.bigButton('explorer', 'Browse Folders…'),
          this.shell.bigButton('help', 'Mouse and Keyboard'),
          this.shell.bigButton('options', 'Options'),
          h('div', { class: 'wl-formats', html: 'STEP · IGES · BREP<br>SolidWorks SLDPRT · SLDASM · SLDDRW<br>Parasolid X_T / X_B<br>STL · OBJ · PLY · OFF · 3MF · glTF<br>PDF · DXF · DWG · PLT · SVG · eDrawings<br>G-code · pictures · zip' })),
        h('div', { class: 'wl-recent' }, h('h3', { text: 'Recent Documents' }),
          recent.length ? recent.map((r) => this.shell.recentRow(r)) : h('div', { class: 'wl-empty', text: 'Files you open show up here.' }))))));
  }

  renderLoading() {
    const el = this.$('loading');
    const d = this.active;
    if (!d || d.state === 'ready' || d.state === 'password') { el.hidden = true; return; }
    el.hidden = false;
    const err = d.state === 'error';
    const pct = Math.round((d.fraction || 0) * 100);
    el.replaceChildren(h('div', { class: `load-card${err ? ' error' : ''}` },
      h('div', { class: 'lc-head' }, h('img', { src: 'img/icon.svg', alt: '' }), h('span', { text: err ? 'Could not open the file' : 'Opening' })),
      h('div', { class: 'lc-body' },
        h('div', { class: 'lc-name', text: d.name }),
        h('div', { class: 'lc-stage', text: err ? (d.error || 'Could not open this file.') : `${d.stage || 'Working'}…` }),
        err ? null : h('div', { class: 'bar' }, h('div', { style: { width: `${Math.max(4, pct)}%` } })),
        h('div', { class: 'lc-foot' }, h('span', { text: err ? '' : `${(d.elapsed || 0).toFixed(1)} s` }),
          h('button', { class: 'btn', onclick: () => this.closeDoc(d), text: err ? 'Close' : 'Cancel' })))));
  }

  // ================================================================== keyboard & mouse helpers
  _wireKeys() {
    document.addEventListener('keydown', (e) => {
      if (e.target.closest('input, select, textarea')) return;
      const k = e.key, v = this.viewer;
      const ctrl = e.ctrlKey || e.metaKey;
      const lk = k.toLowerCase();
      if (ctrl && lk === 'o') { e.preventDefault(); this.run('open'); return; }
      if (ctrl && lk === 'w') { e.preventDefault(); this.run('close'); return; }
      if (ctrl && lk === 'p') { e.preventDefault(); this.run('print'); return; }
      if (ctrl && lk === 'f') { e.preventDefault(); this.$('cmd-search').focus(); return; }
      if (ctrl && k === 'Tab') { e.preventDefault(); this.cycleDocs(e.shiftKey ? -1 : 1); return; }
      if (k === 'F1' || k === '?') { e.preventDefault(); this.run('help'); return; }
      if (k === 'F9') { e.preventDefault(); this.run('fmToggle'); return; }
      if (!this.meta) return;
      if (ctrl && e.shiftKey && lk === 'c') { e.preventDefault(); this.run('copyPicture'); return; }
      if (ctrl && e.shiftKey && lk === 'h') { e.preventDefault(); this.run('showAll'); return; }
      if (ctrl && e.shiftKey && lk === 'z') { e.preventDefault(); this.run('prevView'); return; }
      if (ctrl && lk === 'b') { e.preventDefault(); this.run('reload'); return; }
      if (ctrl && lk === 'c') { this.tools.copyMeasure(); return; }
      const views = { 1: 'front', 2: 'back', 3: 'left', 4: 'right', 5: 'top', 6: 'bottom', 7: 'iso' };
      if (ctrl && views[k]) { e.preventDefault(); v.setView(views[k]); return; }
      if (ctrl && k === '8') { e.preventDefault(); this.run('normalTo'); return; }
      if (k.startsWith('Arrow')) {
        e.preventDefault();
        const step = e.shiftKey ? 90 : 15;
        if (ctrl) {
          const px = 40;
          v.rig.pan(k === 'ArrowLeft' ? -px : k === 'ArrowRight' ? px : 0, k === 'ArrowUp' ? -px : k === 'ArrowDown' ? px : 0, v.height);
        } else if (e.altKey && (k === 'ArrowLeft' || k === 'ArrowRight')) v.rotateView('view', k === 'ArrowLeft' ? step : -step);
        else if (k === 'ArrowLeft' || k === 'ArrowRight') v.rotateView('screenY', k === 'ArrowLeft' ? -step : step);
        else v.rotateView('screenX', k === 'ArrowUp' ? -step : step);
        return;
      }
      switch (k) {
        case 'f': case 'F': v.fitAll(); break;
        case 'z': v.rig.zoomAt(1.25); break; // SolidWorks: Z zooms out, Shift+Z zooms in
        case 'Z': v.rig.zoomAt(0.8); break;
        case 's': case 'S': this.shell.shortcutBar(); break;
        case 'd': case 'D': this.run('displayStyle'); break;
        case 'p': case 'P': this.run('perspective'); break;
        case 'Tab': {
          e.preventDefault();
          const hit = this.hovered;
          const b = hit && hit.kind === 'face' ? this.meta.faces.body[hit.index] : null;
          if (e.shiftKey) this.showAll();
          else if (b !== null && b !== undefined) this.hideBodies([b]);
          else if (this.selectedBodies().length) this.hideBodies(this.selectedBodies());
          break;
        }
        case ' ': e.preventDefault(); this.selector.toggle(); break;
        case 'Escape':
          if (this.selector.active) this.selector.close();
          else if (v.mode !== 'select') { v.mode = 'select'; this.shell.refresh(); this.status(); }
          else if (this.sel.length) this.setSelection([]);
          break;
        default: return;
      }
    });
  }

  cycleDocs(dir) {
    if (this.docs.length < 2) return;
    const i = this.docs.indexOf(this.active);
    this.activate(this.docs[(i + dir + this.docs.length) % this.docs.length]);
  }

  _wireDrop() {
    const drop = this.$('drop');
    let depth = 0;
    window.addEventListener('dragenter', (e) => { if (e.dataTransfer?.types?.includes('Files')) { depth++; drop.hidden = false; } });
    window.addEventListener('dragleave', () => { depth = Math.max(0, depth - 1); if (!depth) drop.hidden = true; });
    window.addEventListener('dragover', (e) => e.preventDefault());
    window.addEventListener('drop', (e) => {
      e.preventDefault();
      depth = 0;
      drop.hidden = true;
      for (const f of e.dataTransfer?.files || []) this.upload(f);
    });
  }

  _wireSplitter() {
    const sp = this.$('splitter'), ws = this.$('workspace');
    sp.addEventListener('pointerdown', (e) => {
      sp.setPointerCapture(e.pointerId);
      sp.classList.add('drag');
      const x0 = e.clientX, w0 = this.$('manager').getBoundingClientRect().width;
      const move = (ev) => { ws.style.setProperty('--mgr-w', `${Math.min(560, Math.max(180, w0 + ev.clientX - x0))}px`); this.viewer.resize(); };
      const up = () => {
        sp.classList.remove('drag');
        sp.removeEventListener('pointermove', move);
        sp.removeEventListener('pointerup', up);
        this.save({ mgrWidth: Math.round(this.$('manager').getBoundingClientRect().width) });
      };
      sp.addEventListener('pointermove', move);
      sp.addEventListener('pointerup', up);
    });
  }

  // called from the desktop window
  nativeDrag(on) { this.$('drop').hidden = !on; }
  toast(msg, kind) { toast(msg, kind); }
}

window.SS = new App();
