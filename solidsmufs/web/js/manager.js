// The left panel, SolidWorks-style: FeatureManager design tree, PropertyManager (tools put their
// options here, with OK / Cancel) and DisplayManager (appearances per body).
import { materialLabel } from './consts.js';
import * as THREE from 'three';
import { tool, icon } from './icons.js';
import { h, menu } from './ui.js';

const TABS = [
  { id: 'tree', icon: 'featureMgr', title: 'FeatureManager Design Tree' },
  { id: 'pm', icon: 'propertyMgr', title: 'PropertyManager' },
  { id: 'display', icon: 'displayMgr', title: 'DisplayManager' },
];

export class Manager {
  constructor(app) {
    this.app = app;
    this.tab = 'tree';
    this.page = null;
    this.open = new Set(['root', 'solids', 'surfaces', 'meshes', 'layers']);
    this.filter = '';
    this.tabsEl = document.getElementById('mgr-tabs');
    this.body = document.getElementById('mgr-body');
    this._buildTabs();
  }

  get viewer() { return this.app.viewer; }
  get meta() { return this.app.meta; }

  _buildTabs() {
    this.tabsEl.replaceChildren(...TABS.map((t) => {
      const b = h('button', { class: `mgr-tab${t.id === this.tab ? ' on' : ''}`, title: t.title, html: tool(t.icon), 'data-tab': t.id });
      b.addEventListener('click', () => this.show(t.id));
      return b;
    }));
  }

  show(tab) {
    this.tab = tab;
    this.tabsEl.querySelectorAll('.mgr-tab').forEach((b) => b.classList.toggle('on', b.dataset.tab === tab));
    this.refresh();
  }

  refresh() {
    if (this.tab === 'pm') this._renderPM();
    else if (this.tab === 'display') this._renderDisplay();
    else this._renderTree();
    try { this.app.status?.(); } catch { /* still starting up */ } // hiding or showing bodies changes the size in the status bar
  }

  selectionChanged() {
    if (this.tab === 'tree') this._markSelection();
    else if (this.tab === 'display') this._renderDisplay();
  }

  // ================================================================== PropertyManager
  openPM(page) {
    if (this.page && this.page !== page) this.page.onCancel?.();
    this.page = page;
    this.show('pm');
    const tab = this.tabsEl.querySelector('[data-tab="pm"]');
    tab.classList.remove('blink');
    void tab.offsetWidth;
    tab.classList.add('blink');
  }

  closePM(ok) {
    const p = this.page;
    this.page = null;
    if (p) (ok ? p.onOK : p.onCancel)?.();
    this.show('tree');
  }

  updatePM() { if (this.tab === 'pm' && this.page) this._renderPM(); }

  _renderPM() {
    const p = this.page;
    if (!p) {
      this.body.replaceChildren(h('div', { class: 'pm-msg', text: 'Nothing is being edited. Section View, Appearance, Bounding Box and the analysis tools show their options here.' }));
      return;
    }
    const groups = (typeof p.groups === 'function' ? p.groups() : p.groups) || [];
    this.body.replaceChildren(h('div', { class: 'pm' },
      h('div', { class: 'pm-head' }, h('span', { class: 'pm-icon', html: tool(p.icon) }), h('span', { class: 'pm-title', text: p.title })),
      h('div', { class: 'pm-actions' },
        h('button', { class: 'pm-act ok', title: 'OK', html: icon('check'), onclick: () => this.closePM(true) }),
        h('button', { class: 'pm-act cancel', title: 'Cancel', html: icon('cancel'), onclick: () => this.closePM(false) })),
      p.message ? h('div', { class: 'pm-msg', html: p.message }) : null,
      ...groups.filter(Boolean).map((g) => {
        const el = h('div', { class: `pm-group${g.collapsed ? ' collapsed' : ''}` },
          h('div', { class: 'pm-ghead' }, h('span', { class: 'twist', text: '▼' }), h('span', { text: g.title })),
          h('div', { class: 'pm-gbody' }, ...[].concat(g.body).filter(Boolean)));
        el.querySelector('.pm-ghead').addEventListener('click', () => { el.classList.toggle('collapsed'); g.collapsed = el.classList.contains('collapsed'); });
        return el;
      })));
  }

  // ================================================================== FeatureManager tree
  _renderTree() {
    const m = this.meta;
    const app = this.app;
    if (!m) {
      this.body.replaceChildren(h('div', { class: 'pm-msg', text: 'Open a part or assembly to see its FeatureManager design tree.' }));
      return;
    }
    const filterBox = h('label', { class: 'mgr-filter' }, h('i', { html: icon('filter'), style: { display: 'inline-flex', width: '13px', height: '13px' } }),
      h('input', { placeholder: 'Filter the tree', value: this.filter, oninput: (e) => { this.filter = e.target.value; this._renderTree(); setTimeout(() => this.body.querySelector('.mgr-filter input')?.focus(), 0); } }));
    const tree = h('div', { class: 'ftree' });
    this.rows = [];
    const asm = app.isAssembly;
    const docName = (app.active?.name || m.name).replace(/\.[^.]+$/, '');
    const q = this.filter.trim().toLowerCase();
    const add = (o) => {
      if (q && o.searchable && !o.label.toLowerCase().includes(q)) return null;
      const depth = o.depth || 0;
      const row = h('div', { class: `fnode${o.dim ? ' dim' : ''}${o.hidden ? ' hidden-item' : ''}`, style: { paddingLeft: `${4 + depth * 16}px` }, title: o.title || o.label },
        h('span', { class: `twist${o.open ? ' open' : ''}`, text: o.children ? '▶' : '' }),
        h('span', { class: 'ficon', html: tool(o.icon) }),
        h('span', { class: 'fname' }, o.label, o.note ? h('span', { class: 'fnote', text: ` ${o.note}` }) : null),
        o.swatch ? h('span', { class: 'fswatch', style: { background: o.swatch } }) : null,
        o.eye !== undefined ? h('span', { class: `feye${o.eye ? '' : ' off'}`, title: o.eye ? 'Hide' : 'Show', html: icon(o.eye ? 'eye' : 'eyeOff'),
          onclick: (e) => { e.stopPropagation(); o.toggleEye(); } }) : null);
      if (o.children) row.querySelector('.twist').addEventListener('click', (e) => { e.stopPropagation(); if (this.open.has(o.key)) this.open.delete(o.key); else this.open.add(o.key); this._renderTree(); });
      row.addEventListener('click', (e) => o.select?.(e));
      row.addEventListener('dblclick', () => o.dbl?.());
      row.addEventListener('mouseenter', () => o.hover && this.viewer.setHover(o.hover));
      row.addEventListener('mouseleave', () => o.hover && this.viewer.setHover(null));
      row.addEventListener('contextmenu', (e) => { e.preventDefault(); o.context?.(e); });
      row._ent = o.ent;
      tree.append(row);
      this.rows.push(row);
      return row;
    };
    const bodyRow = (bi, depth) => {
      const b = m.bodies[bi];
      const vb = this.viewer.bodies[bi];
      const vis = vb ? vb.visible : true;
      const rgb = this.viewer.bodyColor(bi);
      const ent = { kind: 'body', index: bi };
      add({
        key: `b${bi}`, depth, label: b.name, searchable: true, ent,
        icon: b.kind === 'sheet' ? 'surfaceBody' : b.kind === 'mesh' ? 'meshBody' : b.kind === 'layer' ? 'layer' : asm ? 'component' : 'body',
        swatch: `rgb(${rgb.map((c) => Math.round(c * 255)).join(',')})`, hidden: !vis, eye: vis,
        toggleEye: () => { this.viewer.setBodyVisible(bi, !vis); this.refresh(); },
        hover: ent,
        select: (e) => this._select(ent, e),
        dbl: () => this.viewer.fitBox(this.viewer.bodyBox(bi)),
        context: (e) => { this.app.setSelection([ent]); this.app.contextMenu(ent, e); },
      });
    };
    const planeRow = (i, depth) => {
      const ent = { kind: 'plane', index: i };
      const vis = this.viewer.planeShown(i);
      add({
        key: `p${i}`, depth, label: this.viewer.planeName(i), icon: 'plane', ent, eye: vis, dim: !vis,
        toggleEye: () => { this.viewer.showPlane(i, !vis); this.refresh(); },
        hover: ent, select: (e) => this._select(ent, e),
        context: (e) => menu(null, [
          { label: 'Normal To', icon: 'normalTo', action: () => this.viewer.normalTo(this.viewer.planeNormal(i)) },
          { label: vis ? 'Hide' : 'Show', glyph: vis ? 'eyeOff' : 'eye', action: () => { this.viewer.showPlane(i, !vis); this.refresh(); } },
          { label: 'Section View Here', icon: 'sectionView', action: () => this.app.pages.section({ plane: ['front', 'top', 'right'][i] }) },
        ], { at: { x: e.clientX, y: e.clientY } }),
      });
    };
    const rootKind = asm ? 'assembly' : 'part';
    const solids = m.bodies.map((b, i) => [b, i]).filter(([b]) => b.kind === 'solid').map(([, i]) => i);
    const sheets = m.bodies.map((b, i) => [b, i]).filter(([b]) => b.kind === 'sheet').map(([, i]) => i);
    const meshes = m.bodies.map((b, i) => [b, i]).filter(([b]) => b.kind === 'mesh').map(([, i]) => i);
    const layers = m.bodies.map((b, i) => [b, i]).filter(([b]) => b.kind === 'layer').map(([, i]) => i);
    const rootOpen = this.open.has('root');
    // the configuration shown, as SolidWorks writes it after the part name; right-click to show another
    const configs = m.configs || [];
    const shown = configs.find((c) => c.id === m.config) || configs[0];
    add({ key: 'root', depth: 0, label: docName, note: `(${shown?.name || 'Default'})`, icon: rootKind, children: true, open: rootOpen,
      select: () => this.app.setSelection(m.bodies.map((_, i) => ({ kind: 'body', index: i }))),
      title: configs.length > 1 ? `${m.name} — ${m.format}\nRight-click to show another configuration` : `${m.name} — ${m.format}`,
      context: configs.length > 1 ? (e) => menu(null, [
        { head: 'Configurations' },
        ...configs.map((c) => ({ label: c.name, check: c === shown, action: () => this.app.setConfig(c.id) })),
      ], { at: { x: e.clientX, y: e.clientY } }) : null });
    if (rootOpen && configs.length > 1 && !q) {
      const o = this.open.has('configs');
      add({ key: 'configs', depth: 1, label: `Configurations(${configs.length})`, icon: 'props', children: true, open: o });
      if (o) configs.forEach((c) => add({ key: `cfg${c.id}`, depth: 2, label: c.name, note: c === shown ? '(shown)' : '', icon: rootKind,
        dim: c !== shown, title: 'Double-click to show this configuration', select: () => {}, dbl: () => this.app.setConfig(c.id),
        context: (e) => menu(null, [{ label: 'Show Configuration', icon: rootKind, action: () => this.app.setConfig(c.id) }], { at: { x: e.clientX, y: e.clientY } }) }));
    }
    if (rootOpen && !q) {
      add({ key: 'hist', depth: 1, label: 'History', icon: 'history', title: `Opened ${new Date().toLocaleTimeString()}` });
      add({ key: 'ann', depth: 1, label: 'Annotations', icon: 'annotations' });
    }
    if (rootOpen && !asm) {
      if (solids.length) {
        const o = this.open.has('solids');
        if (!q) add({ key: 'solids', depth: 1, label: `Solid Bodies(${solids.length})`, icon: 'bodyFolder', children: true, open: o, select: () => this.app.setSelection(solids.map((i) => ({ kind: 'body', index: i }))) });
        if (o || q) solids.forEach((i) => bodyRow(i, 2));
      }
      if (sheets.length) {
        const o = this.open.has('surfaces');
        if (!q) add({ key: 'surfaces', depth: 1, label: `Surface Bodies(${sheets.length})`, icon: 'bodyFolder', children: true, open: o });
        if (o || q) sheets.forEach((i) => bodyRow(i, 2));
      }
      if (meshes.length) {
        const o = this.open.has('meshes');
        if (!q) add({ key: 'meshes', depth: 1, label: `Graphics Bodies(${meshes.length})`, icon: 'bodyFolder', children: true, open: o });
        if (o || q) meshes.forEach((i) => bodyRow(i, 2));
      }
      if (layers.length) { // a drawing's layers
        const o = this.open.has('layers');
        if (!q) add({ key: 'layers', depth: 1, label: `${m.toolpath ? 'Toolpaths' : 'Layers'}(${layers.length})`, icon: 'bodyFolder', children: true, open: o,
          select: () => this.app.setSelection(layers.map((i) => ({ kind: 'body', index: i }))) });
        if (o || q) layers.forEach((i) => bodyRow(i, 2));
      }
      if (!q && !m.drawing) { // a flat drawing has nothing to weigh
        const mat = this.app.active?.material;
        add({ key: 'mat', depth: 1, label: mat ? mat.name : 'Material', note: mat ? '' : '<not specified>', icon: 'material',
          title: mat ? `${materialLabel(mat)}${mat.fromFile ? ' — from the file' : ''}` : 'Double-click to choose a material for mass properties',
          dbl: () => this.app.run('material'), context: (e) => menu(null, [{ label: 'Edit Material…', icon: 'material', action: () => this.app.run('material') }], { at: { x: e.clientX, y: e.clientY } }) });
      }
    }
    if (rootOpen && !q) {
      [0, 1, 2].forEach((i) => planeRow(i, 1));
      const ov = this.viewer.originVisible;
      add({ key: 'origin', depth: 1, label: 'Origin', icon: 'origin', eye: ov, dim: !ov, ent: { kind: 'origin', index: 0 },
        toggleEye: () => { this.viewer.setOriginVisible(!ov); this.refresh(); }, select: (e) => this._select({ kind: 'origin', index: 0 }, e) });
    }
    if (rootOpen && asm) this._components(add, bodyRow, q);
    if (rootOpen && !asm && !q && !m.drawing) {
      add({ key: 'imp', depth: 1, label: 'Imported1', icon: 'imported', title: `Bodies read from ${m.name}`,
        select: () => this.app.setSelection(m.bodies.map((_, i) => ({ kind: 'body', index: i }))) });
    }
    if (rootOpen && this.viewer.bboxShown && !q) add({ key: 'bbox', depth: 1, label: 'Bounding Box', icon: 'bbox', select: () => this.app.pages.boundingBox() });
    this.body.replaceChildren(filterBox, tree);
    this._markSelection();
  }

  _components(add, bodyRow, q) {
    const m = this.meta;
    const root = { children: new Map(), bodies: [] };
    m.bodies.forEach((b, bi) => {
      let node = root;
      for (const p of displayParents(b.path || [], b.name)) {
        if (!node.children.has(p)) node.children.set(p, { name: p, children: new Map(), bodies: [] });
        node = node.children.get(p);
      }
      node.bodies.push(bi);
    });
    // the assembly's own top node is the document; skip a single wrapper level
    let top = root;
    while (top.children.size === 1 && !top.bodies.length) top = [...top.children.values()][0];
    const all = (n) => [...n.bodies, ...[...n.children.values()].flatMap(all)];
    const walk = (node, depth, key) => {
      for (const [name, child] of node.children) {
        const k = `${key}/${name}`;
        const bodies = all(child);
        const vis = bodies.some((bi) => this.viewer.bodies[bi]?.visible);
        const o = this.open.has(k);
        if (!q) add({
          key: k, depth, label: name, icon: 'subassembly', children: true, open: o, eye: vis, hidden: !vis,
          toggleEye: () => { bodies.forEach((bi) => this.viewer.setBodyVisible(bi, !vis)); this.refresh(); },
          select: () => this.app.setSelection(bodies.map((bi) => ({ kind: 'body', index: bi }))),
          dbl: () => { const box = new THREE.Box3(); bodies.forEach((bi) => box.union(this.viewer.bodyBox(bi))); this.viewer.fitBox(box); },
        });
        if (o || q) walk(child, depth + 1, k);
      }
      node.bodies.forEach((bi) => bodyRow(bi, depth));
    };
    walk(top, 1, 'c');
    if (!q) add({ key: 'mates', depth: 1, label: 'Mates', icon: 'history', dim: true, title: 'Assembly mates are not stored in STEP files' });
  }

  _select(ent, e) {
    const app = this.app;
    const same = (s) => s.kind === ent.kind && s.index === ent.index;
    if (e?.ctrlKey) app.setSelection(app.sel.some(same) ? app.sel.filter((s) => !same(s)) : [...app.sel, ent]);
    else app.setSelection([ent]);
  }

  _markSelection() {
    if (!this.rows) return;
    const sel = this.app.sel;
    for (const r of this.rows) {
      const e = r._ent;
      r.classList.toggle('sel', !!e && sel.some((s) => s.kind === e.kind && s.index === e.index));
    }
  }

  // ================================================================== DisplayManager
  _renderDisplay() {
    const m = this.meta;
    if (!m) { this.body.replaceChildren(h('div', { class: 'pm-msg', text: 'Open a document to see its appearances.' })); return; }
    const list = h('div', { class: 'ftree' });
    list.append(h('div', { class: 'fx-section', text: 'Appearances' }));
    m.bodies.forEach((b, bi) => {
      const rgb = this.viewer.bodyColor(bi);
      const vb = this.viewer.bodies[bi];
      const row = h('div', { class: 'fnode', style: { paddingLeft: '8px' } },
        h('span', { class: 'fswatch', style: { width: '16px', height: '16px', background: `rgb(${rgb.map((c) => Math.round(c * 255)).join(',')})`, opacity: vb && vb.opacity < 1 ? 0.5 : 1 } }),
        h('span', { class: 'fname', text: b.name }),
        h('span', { class: 'fnote', text: vb && vb.opacity < 1 ? `${Math.round((1 - vb.opacity) * 100)}% clear` : '' }));
      row.addEventListener('click', () => { this.app.setSelection([{ kind: 'body', index: bi }]); this.app.pages.appearance([bi]); });
      list.append(row);
    });
    list.append(h('div', { class: 'fx-section', text: 'Scene' }), h('div', { class: 'fnode', style: { paddingLeft: '8px' } },
      h('span', { class: 'ficon', html: tool('scene') }), h('span', { class: 'fname', text: 'Change the background…' })));
    list.lastChild.addEventListener('click', () => this.app.taskpane.show('appearance'));
    this.body.replaceChildren(list);
  }
}

export function displayParents(path, name) {
  const parts = path.slice(0, -1);
  const out = [];
  const base = (s) => s.replace(/\s\(\d+\)$/, '').replace(/<\d+>$/, '').replace(/::\d+$/, '').toLowerCase();
  for (const p of parts) {
    const mm = p.match(/^(.*)::(\d+)$/);
    const label = mm ? `${mm[1]}<${mm[2]}>` : p;
    if (out.length && base(out[out.length - 1]) === base(label)) continue;
    out.push(label);
  }
  if (out.length && base(out[out.length - 1]) === base(name)) out.pop();
  return out;
}
