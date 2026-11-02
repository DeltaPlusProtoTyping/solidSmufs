// Floating tool windows: Measure, Mass Properties, Section Properties, Statistics, and the Wagner
// tools (Stock Size, Hole Report, Quote Summary), plus Material, Options, Help and About.
import * as THREE from 'three';
import { api } from './api.js';
import { tool, icon } from './icons.js';
import { SYSTEMS, LENGTH } from './units.js';
import { h, Dialog, menu, toast, copyText, modal } from './ui.js';
import { PRODUCT, MATERIALS, escapeHtml, clean, materialLabel } from './consts.js';

const AXIS = { x: 0xd93a3a, y: 0x2f9e46, z: 0x2c63d6 };
const KIND_ICON = { face: 'face', edge: 'edge', vertex: 'vertex', point: 'point', body: 'body', plane: 'plane', origin: 'origin' };

export class Tools {
  constructor(app) {
    this.app = app;
    this.arcMode = 'center';
    this.pointToPoint = false;
    this.showXYZ = true;
    this.projected = 'none';
    this.history = [];
    this.dialogs = {};
    this.stockOpts = { allowance: null, round: true, align: 'best' };
  }

  get viewer() { return this.app.viewer; }
  get meta() { return this.app.meta; }
  get units() { return this.app.units; }

  refresh() {
    if (this.dialogs.measure && !this.dialogs.measure.closed) this._renderMeasure();
    if (this.dialogs.mass && !this.dialogs.mass.closed) this._renderMass();
    if (this.dialogs.section && !this.dialogs.section.closed) this.sectionProps();
  }

  closeDocDialogs() {
    for (const k of Object.keys(this.dialogs)) this.dialogs[k]?.close();
    this.dialogs = {};
  }

  selectionChanged() {
    if (this.dialogs.measure && !this.dialogs.measure.closed) this._runMeasure();
    if (this.dialogs.mass && !this.dialogs.mass.closed && this.massScope === 'selected') this._computeMass();
    if (this.dialogs.stock && !this.dialogs.stock.closed) this._stockRecalc?.();
  }

  _dialog(key, opts) {
    if (this.dialogs[key] && !this.dialogs[key].closed) { this.dialogs[key].el.style.zIndex = 999; return this.dialogs[key]; }
    const d = new Dialog({ key, ...opts, onClose: () => { delete this.dialogs[key]; opts.onClose?.(); } });
    this.dialogs[key] = d;
    return d;
  }

  // ================================================================== Measure
  measure() {
    if (this.dialogs.measure && !this.dialogs.measure.closed) { this.dialogs.measure.close(); return; }
    const app = this.app;
    const tb = (iconName, title, on, fn) => h('button', { class: `icon-btn${on ? ' on' : ''}`, title, html: tool(iconName), onclick: fn });
    const tools = () => [
      tb('measure', 'Arc/Circle measurements', false, (e) => menu(e.currentTarget, [
        { label: 'Center to Center', check: this.arcMode === 'center', action: () => { this.arcMode = 'center'; this._runMeasure(); } },
        { label: 'Minimum Distance', check: this.arcMode === 'min', action: () => { this.arcMode = 'min'; this._runMeasure(); } },
        { label: 'Maximum Distance', check: this.arcMode === 'max', action: () => { this.arcMode = 'max'; this._runMeasure(); } },
      ])),
      tb('options', 'Units/Precision', false, (e) => menu(e.currentTarget, [
        ...Object.entries(SYSTEMS).map(([k, s]) => ({ label: s.name, check: app.units.system === k, action: () => app.setSystem(k) })),
        { sep: true },
        ...[1, 2, 3, 4, 5].map((n) => ({ label: `${n} decimal places`, check: app.units.decimals === n, action: () => app.setSystem(app.units.system, n) })),
      ])),
      h('span', { class: 'sep' }),
      tb('origin', 'Show XYZ Measurements', this.showXYZ, () => { this.showXYZ = !this.showXYZ; this._renderMeasure(); }),
      tb('point', 'Point-to-Point (pick any spot on a face)', this.pointToPoint, () => { this.pointToPoint = !this.pointToPoint; this._renderMeasure(); app.status(); }),
      tb('plane', 'Projected On', this.projected !== 'none', (e) => menu(e.currentTarget, [
        ...[['none', 'None'], ['screen', 'Screen'], ['xy', 'Front Plane (XY)'], ['xz', 'Top Plane (XZ)'], ['yz', 'Right Plane (YZ)']]
          .map(([k, label]) => ({ label, check: this.projected === k, action: () => { this.projected = k; this._renderMeasure(); } })),
      ])),
      tb('history', 'Measurement History', false, () => this._history()),
    ];
    this.measureTools = tools;
    const d = this._dialog('measure', {
      title: `Measure - ${this.app.active?.name || ''}`, icon: 'measure', width: 340, tools: h('div', { class: 'row', style: { gap: '1px' } }, ...tools()), body: h('div'),
      onClose: () => { app.measuring = false; this.viewer.clearAnnotations(); app.shell.refresh(); app.status(); },
    });
    app.measuring = true;
    app.shell.refresh();
    this._runMeasure();
    return d;
  }

  async _runMeasure() {
    const app = this.app;
    const sel = app.sel.filter((s) => !['body', 'plane', 'origin'].includes(s.kind));
    const token = (this._mt = (this._mt || 0) + 1);
    if (!sel.length || !app.active?.meta) { this.mresult = null; this._renderMeasure(); return; }
    this.mbusy = true;
    this._renderMeasure();
    try {
      const r = await api.measure(app.active.id, sel.map(clean), { arc: this.arcMode });
      if (token !== this._mt) return;
      this.mresult = r;
      const primary = (r.rows || []).find((x) => x.primary);
      if (primary) {
        const what = (r.labels || []).join(', ');
        if (!this.history.length || this.history[0].what !== what || this.history[0].row.label !== primary.label) this.history.unshift({ what, row: primary });
        this.history = this.history.slice(0, 30);
      }
    } catch (e) {
      if (token !== this._mt) return;
      this.mresult = { error: e.message };
    }
    this.mbusy = false;
    this._renderMeasure();
  }

  _renderMeasure() {
    const d = this.dialogs.measure;
    if (!d || d.closed) return;
    const app = this.app, u = this.units;
    d.setTitle(`Measure - ${app.active?.name || ''}`);
    d.toolsEl.replaceChildren(h('div', { class: 'row', style: { gap: '1px' } }, ...this.measureTools()));
    const sel = app.sel.filter((s) => !['body', 'plane', 'origin'].includes(s.kind));
    const selbox = h('div', { class: 'selbox active' }, ...sel.map((s) => h('div', { class: 'si' },
      h('span', { html: tool(KIND_ICON[s.kind]), style: { width: '13px', height: '13px', display: 'inline-flex' } }),
      app.describe(s, true),
      h('span', { class: 'x', text: '×', onclick: () => app.setSelection(app.sel.filter((x) => x !== s)) }))));
    const res = h('div', { class: 'mres' });
    const r = this.mresult;
    if (!sel.length) res.append(h('div', { class: 'empty-msg', html: `Select faces, edges or vertices to measure.${this.pointToPoint ? '<br>Point-to-point is on: click anywhere on a face.' : ''}` }));
    else if (this.mbusy && !r) res.append(h('div', { class: 'empty-msg' }, h('span', { class: 'spin' })));
    else if (r?.error) res.append(h('div', { class: 'empty-msg', style: { color: 'var(--bad)' }, text: r.error }));
    else if (r) {
      const rows = this._displayRows(r);
      for (const row of rows) {
        const val = u.value(row);
        const el = h('div', { class: `mr${row.primary ? ' primary' : ''}`, title: 'Click to copy' },
          h('span', { class: 'mk' }, row.axis ? h('span', { class: 'dot', style: { background: `var(--${row.axis})` } }) : null, `${row.label}:`),
          h('span', { class: 'mv', text: val }));
        el.addEventListener('click', async () => { if (await copyText(val)) { el.classList.add('copied'); setTimeout(() => el.classList.remove('copied'), 400); } });
        res.append(el);
      }
    }
    d.setBody(selbox, h('div', { style: { height: '6px' } }), res);
    this._drawMeasure();
  }

  _displayRows(r) {
    const rows = (r.rows || []).filter((x) => this.showXYZ || !x.axis).map((x) => ({ ...x }));
    // SolidWorks words "Delta X" for dX
    rows.forEach((x) => { if (x.axis) x.label = `Delta ${x.axis.toUpperCase()}`; });
    if (this.projected !== 'none') {
      const line = (r.graphics || []).find((g) => g.type === 'line' && !g.style);
      if (line) {
        const d = new THREE.Vector3(...line.p2).sub(new THREE.Vector3(...line.p1));
        const n = this.projected === 'screen' ? this.viewer.rig.dir() : new THREE.Vector3(...{ xy: [0, 0, 1], xz: [0, 1, 0], yz: [1, 0, 0] }[this.projected]);
        const proj = d.clone().sub(n.clone().multiplyScalar(d.dot(n)));
        rows.splice(1, 0, { label: `Projected (${this.projected === 'screen' ? 'screen' : this.projected.toUpperCase()})`, value: proj.length(), kind: 'length' });
      }
    }
    return rows;
  }

  _drawMeasure() {
    const v = this.viewer;
    v.clearAnnotations();
    const r = this.mresult;
    if (!this.app.measuring || !r?.graphics) return;
    const u = this.units;
    const main = 0x213367, center = 0x8a59c4, normal = 0x1f9e8f;
    for (const g of r.graphics) {
      if (g.type === 'line') {
        const p1 = new THREE.Vector3(...g.p1), p2 = new THREE.Vector3(...g.p2);
        const color = g.style === 'center' ? center : g.style === 'normal' ? normal : main;
        if (p1.distanceTo(p2) > 1e-9) v.annotLine(g.p1, g.p2, color, 2);
        v.annotDots([g.p1, g.p2], color, 6);
        v.addLabel(p1.clone().add(p2).multiplyScalar(0.5), escapeHtml(u.len(g.value)), g.style ? 'small' : 'primary');
        if (g.xyz && this.showXYZ) {
          const a = p1, b = new THREE.Vector3(p2.x, p1.y, p1.z), c = new THREE.Vector3(p2.x, p2.y, p1.z), d = p2;
          const tiny = (p1.distanceTo(p2) || 1) * 1e-4;
          [[a, b, 'x', Math.abs(p2.x - p1.x)], [b, c, 'y', Math.abs(p2.y - p1.y)], [c, d, 'z', Math.abs(p2.z - p1.z)]].forEach(([s, e, ax, val]) => {
            if (val < tiny) return;
            v.annotLine(s.toArray(), e.toArray(), AXIS[ax], 1.3, { dashed: true, dashSize: v.rig.radius * 0.02, gapSize: v.rig.radius * 0.012 });
            v.addLabel(s.clone().add(e).multiplyScalar(0.5), `d${ax.toUpperCase()} ${escapeHtml(u.len(val, false))}`, `small ${ax}`);
          });
        }
      } else if (g.type === 'point') {
        v.annotDots([g.p], g.style === 'center' ? center : main, 7);
        if (g.style === 'center') v.addLabel(new THREE.Vector3(...g.p), 'Center', 'small');
      } else if (g.type === 'axis') {
        const c = new THREE.Vector3(...g.p), dd = new THREE.Vector3(...g.d).normalize(), half = (g.len || 10) * 0.65;
        v.annotLine(c.clone().addScaledVector(dd, -half).toArray(), c.clone().addScaledVector(dd, half).toArray(), center, 1.3,
          { dashed: true, dashSize: half * 0.06, gapSize: half * 0.04 });
      }
    }
  }

  _history() {
    const u = this.units;
    const body = h('div', { class: 'mres', style: { maxHeight: '360px' } }, ...(this.history.length ? this.history.map((it) => {
      const val = u.value(it.row);
      const el = h('div', { class: 'mr', title: 'Click to copy' }, h('span', { class: 'mk', text: `${it.row.label} (${it.what})` }), h('span', { class: 'mv', text: val }));
      el.addEventListener('click', () => copyText(val).then(() => toast('Copied')));
      return el;
    }) : [h('div', { class: 'empty-msg', text: 'Measurements you take show up here.' })]));
    this._dialog('mhistory', { title: 'Measurement History', icon: 'history', width: 380, body });
  }

  copyMeasure() {
    const r = this.dialogs.measure && !this.dialogs.measure.closed ? this.mresult : this.app.quick;
    if (!r?.rows?.length) return;
    const u = this.units;
    copyText(r.rows.map((row) => `${row.label}: ${u.value(row)}`).join('\n')).then(() => toast('Measurement copied'));
  }

  // ================================================================== Mass Properties
  massProps() {
    const app = this.app;
    this.massScope = this.massScope || 'all';
    this.massOpts = this.massOpts || { hidden: true, showCom: true };
    const tb = (iconName, title, fn) => h('button', { class: 'icon-btn', title, html: tool(iconName), onclick: fn });
    this._dialog('mass', {
      title: 'Mass Properties', icon: 'massProps', width: 520, height: 600,
      tools: h('div', { class: 'row', style: { gap: '1px' } },
        tb('quote', 'Copy to Clipboard', () => this._copyMass()),
        tb('reload', 'Recalculate', () => this._computeMass()),
        tb('options', 'Options… (units)', () => this.options('units')),
        h('span', { class: 'sep' }),
        tb('material', 'Edit Material…', () => this.material())),
      body: h('div'),
      onClose: () => this.viewer.clearAnnotations(),
    });
    this._computeMass();
  }

  async _computeMass() {
    const app = this.app;
    if (!app.active?.meta) return;
    const m = this.meta;
    let bodies = m.bodies.map((_, i) => i);
    if (this.massScope === 'selected') { const s = app.selectedBodies(); if (s.length) bodies = s; }
    if (!this.massOpts.hidden) bodies = bodies.filter((i) => this.viewer.bodies[i]?.visible);
    this.massBusy = true;
    this._renderMass();
    const mat = app.active.material;
    try { this.mass = await api.massprops(app.active.id, bodies, mat ? mat.density : 1.0); } catch (e) { this.mass = { error: e.message }; }
    this.massBusy = false;
    this._renderMass();
  }

  _renderMass() {
    const d = this.dialogs.mass;
    if (!d || d.closed) return;
    const app = this.app, u = this.units, r = this.mass, mat = app.active?.material;
    const scope = h('div', { class: 'seg' }, ...[['all', 'All bodies'], ['selected', 'Selected bodies']].map(([k, label]) =>
      h('button', { class: this.massScope === k ? 'on' : '', text: label, onclick: () => { this.massScope = k; this._computeMass(); } })));
    const controls = h('div', { class: 'stack', style: { marginBottom: '8px' } },
      h('div', { class: 'row' }, h('span', { text: 'Selected items:', style: { minWidth: '92px' } }), scope),
      h('div', { class: 'row' }, h('span', { text: 'Material:', style: { minWidth: '92px' } }),
        h('b', { text: mat ? materialLabel(mat) : '<not specified>' }),
        h('button', { class: mat ? 'btn' : 'btn primary', style: { marginLeft: 'auto' }, onclick: () => this.material() }, mat ? 'Edit…' : 'Pick Material…')),
      // like SolidWorks, a part with no material weighs as water; say so plainly so it isn't taken as the real weight
      mat ? null : h('div', { class: 'pm-msg', style: { margin: 0 }, text: `This ${app.isAssembly ? 'assembly' : 'part'} has no material, so the mass below is at water density (1 g/cm³), not its real weight. Pick a material to get the weight.` }),
      h('div', { class: 'row' },
        h('label', { class: 'chk' }, h('input', { type: 'checkbox', checked: this.massOpts.hidden, onchange: (e) => { this.massOpts.hidden = e.target.checked; this._computeMass(); } }), 'Include hidden bodies'),
        h('label', { class: 'chk', style: { marginLeft: '14px' } }, h('input', { type: 'checkbox', checked: this.massOpts.showCom, onchange: (e) => { this.massOpts.showCom = e.target.checked; this._drawMass(); } }), 'Show center of mass')),
      h('div', { class: 'row' }, h('span', { text: 'Report coordinate values relative to:', style: { color: 'var(--muted)' } }), h('span', { text: '-- default --' })));
    let report;
    if (this.massBusy && !r) report = h('div', { class: 'report' }, h('span', { class: 'spin' }));
    else if (r?.error) report = h('div', { class: 'report', style: { color: 'var(--bad)' }, text: r.error });
    else if (r) report = h('div', { class: 'report', style: { flex: '1', minHeight: '220px' }, text: this._massReport(r) });
    d.setBody(h('div', { style: { display: 'flex', flexDirection: 'column', height: '100%' } }, controls, report));
    this._drawMass();
  }

  _massReport(r) {
    const u = this.units, app = this.app;
    const L = u.lengthName(true), Mn = u.massName(true);
    const n = (v) => u.num(v);
    const name = (app.active?.name || 'part').replace(/\.[^.]+$/, '');
    const dens = u.densityValue(r.density);
    const lines = [
      `Mass properties of ${name} (${app.isAssembly ? 'Assembly' : 'Part'} Configuration - Default)`,
      'Output coordinate System: -- default --', '',
      `Density = ${dens < 0.01 ? dens.toPrecision(3) : n(dens)} ${u.densityUnit()}`, '',
      `Mass = ${n(r.mass / ({ g: 1, kg: 1000, lb: 453.59237 }[u.massUnit]))} ${Mn}`, '',
      `Volume = ${u.vol(r.volume, false)} cubic ${L}`, '',
      `Surface area = ${u.area(r.area, false)} square ${L}`, '',
      `Center of mass: ( ${L} )`,
      `\tX = ${u.len(r.center[0], false)}`, `\tY = ${u.len(r.center[1], false)}`, `\tZ = ${u.len(r.center[2], false)}`, '',
      `Principal axes of inertia and principal moments of inertia: ( ${Mn} *  square ${L} )`,
      'Taken at the center of mass.',
      ...['x', 'y', 'z'].map((k, i) => `\t I${k} = (${r.principal_axes[i].map((c) => u.num(c, 2).padStart(6)).join(', ')})   \tP${k} = ${u.inertia(r.principal_moments[i])}`), '',
      `Moments of inertia: ( ${Mn} *  square ${L} )`,
      'Taken at the center of mass and aligned with the output coordinate system. (Using positive tensor notation.)',
      ...tensorLines('L', r.inertia_center, u), '',
      `Moments of inertia: ( ${Mn} *  square ${L} )`,
      'Taken at the output coordinate system. (Using positive tensor notation.)',
      ...tensorLines('I', r.inertia_origin, u),
    ];
    if (r.notes?.length) lines.push('', ...r.notes.map((x) => `Note: ${x}`));
    return lines.join('\n');
  }

  _copyMass() { if (this.mass && !this.mass.error) copyText(this._massReport(this.mass)).then(() => toast('Mass properties copied')); }

  _drawMass() {
    const v = this.viewer, r = this.mass;
    v.clearAnnotations();
    if (!this.massOpts?.showCom || !r || r.error || !(r.mass > 0)) return;
    const c = new THREE.Vector3(...r.center);
    v.annotDots([r.center], 0xb04a96, 11);
    v.addLabel(c, 'Center of Mass', 'small com');
    const len = v.rig.radius * 0.35;
    r.principal_axes.forEach((ax, i) => {
      const dd = new THREE.Vector3(...ax).normalize();
      v.annotLine(c.clone().addScaledVector(dd, -len).toArray(), c.clone().addScaledVector(dd, len).toArray(), [0xd93a3a, 0x2f9e46, 0x2c63d6][i], 1.5);
    });
  }

  // ================================================================== Section Properties
  async sectionProps() {
    const app = this.app;
    const f = this.meta.faces;
    const faces = app.sel.filter((s) => s.kind === 'face' && f.type[s.index] === 'plane').map((s) => s.index);
    const d = this._dialog('section', { title: 'Section Properties', icon: 'sectionProps', width: 500, height: 480, body: h('div') });
    if (!faces.length) { d.setBody(h('div', { class: 'pm-msg', text: 'Select one or more flat faces (all in one plane), then run Section Properties again.' })); return; }
    d.setBody(h('div', { class: 'report' }, h('span', { class: 'spin' })));
    let r;
    try { r = await api.sectionProps(app.active.id, faces); } catch (e) { d.setBody(h('div', { class: 'pm-msg', text: e.message })); return; }
    const u = this.units, L = u.lengthName(true);
    const k4 = u.u.factor ** 4;
    const n4 = (v) => u.num(v / k4);
    const lines = [
      `Section properties of selected face(s): ${faces.map((i) => `Face<${i + 1}>`).join(', ')}`, '',
      `Area = ${u.area(r.area, false)} square ${L}`, '',
      `Centroid relative to output coordinate system origin: ( ${L} )`,
      `\tX = ${u.len(r.centroid[0], false)}`, `\tY = ${u.len(r.centroid[1], false)}`, `\tZ = ${u.len(r.centroid[2], false)}`, '',
      `Moments of area, at the centroid: ( ${L} ^ 4 )`,
      ...['x', 'y', 'z'].map((a, i) => ['x', 'y', 'z'].map((b, j) => `L${a}${b} = ${n4(r.inertia[i][j])}`).join('\t')).map((s) => `\t${s}`), '',
      `Polar moment of area, at the centroid = ${n4(r.polar)} ${L} ^ 4`, '',
      `Principal moments of area, at the centroid: ( ${L} ^ 4 )`,
      `\tIx = ${n4(r.principal[0])}`, `\tIy = ${n4(r.principal[1])}`, '',
      `Plane normal: (${r.normal.map((c) => u.num(c, 4)).join(', ')})`,
    ];
    const text = lines.join('\n');
    d.setBody(h('div', { style: { display: 'flex', flexDirection: 'column', height: '100%', gap: '6px' } },
      h('div', { class: 'row' }, h('button', { class: 'btn', onclick: () => copyText(text).then(() => toast('Copied')) }, 'Copy to Clipboard')),
      h('div', { class: 'report', style: { flex: '1' }, text })));
  }

  // ================================================================== Statistics
  statistics() {
    const m = this.meta;
    const count = (arr) => arr.reduce((o, t) => { o[t] = (o[t] || 0) + 1; return o; }, {});
    const names = { plane: 'Planar', cylinder: 'Cylindrical', cone: 'Conical', sphere: 'Spherical', torus: 'Toroidal', bspline: 'Spline', revolution: 'Revolved', mesh: 'Mesh', surface: 'Other', line: 'Line', circle: 'Circle / arc', ellipse: 'Ellipse', polyline: 'Polyline', curve: 'Other', bezier: 'Bezier', conic: 'Conic' };
    const table = (title, obj) => h('table', { class: 'table', style: { marginBottom: '10px' } },
      h('thead', {}, h('tr', {}, h('th', { text: title }), h('th', { class: 'num', text: 'Count' }))),
      h('tbody', {}, ...Object.entries(obj).sort((a, b) => b[1] - a[1]).map(([k, v]) => h('tr', {}, h('td', { text: names[k] || k }), h('td', { class: 'num', text: String(v) })))));
    const st = m.stats;
    const kinds = count(m.bodies.map((b) => b.kind));
    const info = h('table', { class: 'table', style: { marginBottom: '10px' } }, h('tbody', {},
      ...[['Document', m.name], ['Format', m.format], ['Solid bodies', kinds.solid || 0], ['Surface bodies', kinds.sheet || 0], ['Graphics bodies', kinds.mesh || 0],
        ['Faces', st.faces], ['Edges', st.edges], ['Vertices', st.vertices], ['Triangles drawn', st.triangles.toLocaleString()],
        ['Opened in', `${(st.load_s ?? 0).toFixed(2)} s${st.cached ? ' (from cache)' : ''}`]]
        .map(([k, v]) => h('tr', {}, h('td', { text: k }), h('td', { class: 'num', text: String(v) })))));
    this._dialog('stats', { title: 'Statistics', icon: 'statistics', width: 380, height: 560, body: h('div', {}, info, table('Faces by type', count(m.faces.type)), table('Edges by type', count(m.edges.type))) });
  }

  // ================================================================== Wagner: Stock Size
  async stock() {
    const app = this.app, u = this.units, o = this.stockOpts;
    if (o.allowance === null) o.allowance = u.unit === 'in' ? 0.0625 * 25.4 : 1.5;
    const d = this._dialog('stock', { title: 'Stock Size — Wagner Tools', icon: 'stock', width: 420, body: h('div', { class: 'report' }, h('span', { class: 'spin' })),
      onClose: () => { this._stockRefs = null; } });
    let box = null, round = null, error = null;
    // the block either fits tightest (best fit) or stands on picked faces, as in Bounding Box: the first face
    // (or round face / straight edge) sets the thickness direction, a Ctrl+clicked second one the length
    const refs = () => app.sel.filter((s) => s.kind === 'face' || s.kind === 'edge').slice(0, 2).map((s) => ({ kind: s.kind, index: s.index }));
    const measureBox = async () => {
      this._stockRefs = JSON.stringify(o.align === 'faces' ? refs() : []);
      box = round = error = null;
      if (o.align === 'faces' && !refs().length) { this.viewer.showBox(null); render(); return; }
      d.setBody(h('div', { class: 'report' }, h('span', { class: 'spin' })));
      try {
        const bodies = this.meta.bodies.map((_, i) => i).filter((i) => this.viewer.bodies[i]?.visible);
        box = await api.bbox(app.active.id, bodies, o.align === 'faces' ? 'reference' : 'oriented', o.align === 'faces' ? refs() : undefined);
        round = roundStock(this.viewer, box);
        this.viewer.showBox(box);
      } catch (e) { error = e.message; }
      app.manager.refresh();
      render();
    };
    this._stockRecalc = () => { if (o.align === 'faces' && JSON.stringify(refs()) !== this._stockRefs) measureBox(); };
    const alignRow = () => h('div', { class: 'stack', style: { gap: '4px' } },
      h('div', { class: 'row' }, h('span', { text: 'Orientation', style: { minWidth: '160px' } }),
        h('div', { class: 'seg' }, ...[['best', 'Best fit'], ['faces', 'Selected faces']].map(([k, label]) =>
          h('button', { class: o.align === k ? 'on' : '', text: label, onclick: () => { o.align = k; measureBox(); } })))),
      o.align === 'faces' ? h('div', { class: 'hint', text: refs().length
        ? `Standing on ${refs().map((r, i) => `${app.describe(r, true)}${i ? ' (length)' : ' (thickness)'}`).join(', ')}. Ctrl+click another face to set the length.`
        : 'Click the face the stock should sit on (or a round face or straight edge for its axis). Ctrl+click a second face to set the length direction.' }) : null);
    const render = () => {
      if (!box) {
        d.setBody(h('div', { class: 'stack' }, alignRow(), error ? h('div', { class: 'pm-msg', style: { margin: 0 }, text: error }) : null));
        return;
      }
      // best fit: longest first; on picked faces: length and width as fitted, thickness along the face
      const dims = o.align === 'faces' ? [...box.size] : [...box.size].sort((a, b) => b - a);
      const step = u.unit === 'in' ? 0.125 * 25.4 : u.unit === 'mm' ? 1 : 0.001;
      const up = (v) => (o.round ? Math.ceil((v - 1e-9) / step) * step : v);
      const stock = dims.map((x) => up(x + 2 * o.allowance));
      const mat = app.active.material;
      const vol = stock[0] * stock[1] * stock[2];
      const part = app.active.envelope?.part;
      const rows = [
        ['Part envelope (L × W × T)', dims.map((x) => u.len(x, false)).join(' × ') + ` ${u.label}`],
        ['Envelope volume', u.vol(dims[0] * dims[1] * dims[2])],
        ['Rectangular stock', stock.map((x) => u.len(x, false)).join(' × ') + ` ${u.label}`],
        ['Stock volume', u.vol(vol)],
        ...(part > 0 ? [['Part volume', u.vol(part)], ['Removed from stock', `${u.vol(Math.max(vol - part, 0))} (${Math.round((100 * Math.max(vol - part, 0)) / vol)}%)`]] : []),
        mat?.density != null ? ['Stock weight', `${u.mass(vol * mat.density * 1e-3)} (${mat.name})`] : ['Stock weight', 'pick a material to see the weight'],
      ];
      // round bar only when the part is roughly round (no bar suggestions for plates)
      if (round && round.vol <= 1.3 * dims[0] * dims[1] * dims[2]) {
        const dia = up(round.d + 2 * o.allowance), len = up(round.len + 2 * o.allowance);
        rows.push(['Round bar (Ø × length)', `Ø${u.len(dia, false)} × ${u.len(len, false)} ${u.label}`]);
        if (mat?.density != null) rows.push(['Round bar weight', u.mass(Math.PI * (dia / 2) ** 2 * len * mat.density * 1e-3)]);
      }
      const text = rows.map(([k, v]) => `${k}: ${v}`).join('\n');
      d.setBody(h('div', { class: 'stack' }, alignRow(),
        h('div', { class: 'row' }, h('span', { text: `Allowance per side (${u.label})`, style: { minWidth: '160px' } }),
          h('input', { class: 'inp', style: { width: '90px' }, value: u.num(o.allowance / u.u.factor), onchange: (e) => { o.allowance = u.toMm(parseFloat(e.target.value) || 0); render(); } })),
        h('label', { class: 'chk' }, h('input', { type: 'checkbox', checked: o.round, onchange: (e) => { o.round = e.target.checked; render(); } }), `Round up to the next ${u.unit === 'in' ? '1/8"' : '1 mm'}`),
        h('table', { class: 'table' }, h('tbody', {}, ...rows.map(([k, v]) => h('tr', {}, h('td', { text: k }), h('td', { class: 'num', text: v }))))),
        h('div', { class: 'row' }, h('button', { class: 'btn primary', onclick: () => copyText(text).then(() => toast('Stock size copied')) }, 'Copy'),
          h('span', { class: 'subtle', text: o.align === 'faces' ? 'Box on the picked faces, from the exact surfaces; shown in the view.' : 'Smallest box from the exact surfaces; shown in the view.' }))));
    };
    await measureBox();
  }

  // ================================================================== Wagner: Hole Report
  async holes() {
    const app = this.app;
    const d = this._dialog('holes', { title: 'Hole Report — Wagner Tools', icon: 'holes', width: 600, height: 460, body: h('div', { class: 'report' }, h('span', { class: 'spin' })) });
    let r;
    try { r = await api.holes(app.active.id); } catch (e) { d.setBody(h('div', { class: 'pm-msg', text: e.message })); return; }
    const u = this.units;
    const groups = r.groups || [];
    if (!groups.length) { d.setBody(h('div', { class: 'pm-msg', text: 'No round holes found (holes are cylindrical faces that go into the material).' })); return; }
    const rows = groups.map((g) => {
      const match = holeMatch(g.diameter);
      return { g, match };
    });
    const text = ['Ø\tQty\tDepth\tLikely'].concat(rows.map(({ g, match }) => `${u.len(g.diameter)}\t${g.count}\t${g.through ? 'Thru' : u.len(g.depth_max)}\t${match}`)).join('\n');
    const total = groups.reduce((s, g) => s + g.count, 0);
    d.setBody(h('div', { style: { display: 'flex', flexDirection: 'column', height: '100%', gap: '6px' } },
      h('div', { class: 'row' }, h('b', { text: `${total} hole${total === 1 ? '' : 's'} in ${groups.length} size${groups.length === 1 ? '' : 's'}` }),
        h('span', { class: 'grow' }), h('button', { class: 'btn', onclick: () => copyText(text).then(() => toast('Hole report copied')) }, 'Copy')),
      h('div', { style: { flex: '1', overflow: 'auto', border: '1px solid var(--line-2)' } }, h('table', { class: 'table' },
        h('thead', {}, h('tr', {}, ...['Diameter', 'Qty', 'Depth', 'Likely feature', ''].map((t, i) => h('th', { class: i && i < 3 ? 'num' : '', text: t })))),
        h('tbody', {}, ...rows.map(({ g, match }) => h('tr', {},
          h('td', { text: `Ø${u.len(g.diameter)}` }),
          h('td', { class: 'num', text: String(g.count) }),
          h('td', { class: 'num', text: g.through ? 'Thru' : g.depth_min && Math.abs(g.depth_max - g.depth_min) > 1e-6 ? `${u.len(g.depth_min, false)}–${u.len(g.depth_max)}` : u.len(g.depth_max) }),
          h('td', { text: match }),
          h('td', {}, h('button', { class: 'btn', onclick: () => app.setSelection(g.faces.map((f) => ({ kind: 'face', index: f }))) }, 'Select'))))))),
      h('div', { class: 'subtle', text: 'Groups coaxial cylindrical faces that go into the material. "Likely" compares the diameter with tap drills, clearance holes and standard drills.' })));
  }

  // ================================================================== Wagner: Quote Summary
  async quote() {
    const app = this.app, u = this.units;
    const d = this._dialog('quote', { title: 'Quote Summary — Wagner Tools', icon: 'quote', width: 480, height: 520, body: h('div', { class: 'report' }, h('span', { class: 'spin' })) });
    const mat = app.active.material;
    const all = this.meta.bodies.map((_, i) => i);
    let mp, world, best, holes;
    try {
      [mp, world, best, holes] = await Promise.all([
        api.massprops(app.active.id, all, mat ? mat.density : 1.0),
        api.bbox(app.active.id, all, 'world'),
        api.bbox(app.active.id, all, 'oriented'),
        api.holes(app.active.id).catch(() => ({ groups: [] })),
      ]);
    } catch (e) { d.setBody(h('div', { class: 'pm-msg', text: e.message })); return; }
    const dims = [...best.size].sort((a, b) => b - a);
    const st = this.meta.stats;
    const lines = [
      `Part: ${app.active.name}`,
      app.meta.path ? `File: ${app.meta.path}` : null,
      `Format: ${this.meta.format}${this.meta.info?.['Created by'] ? ` (${this.meta.info['Created by']})` : ''}`,
      '',
      `Material: ${mat ? materialLabel(mat) : 'not specified'}`,
      `Volume: ${u.vol(mp.volume)}`,
      `Surface area: ${u.area(mp.area)}`,
      mat ? `Weight: ${u.mass(mp.mass)}` : 'Weight: pick a material',
      '',
      `Size along X/Y/Z: ${world.size.map((x) => u.len(x, false)).join(' × ')} ${u.label}`,
      `Envelope (L × W × T): ${dims.map((x) => u.len(x, false)).join(' × ')} ${u.label}`,
      '',
      `Holes: ${(holes.groups || []).reduce((s, g) => s + g.count, 0)}`,
      ...(holes.groups || []).map((g) => `  ${g.count} × Ø${u.len(g.diameter)} ${g.through ? 'thru' : `× ${u.len(g.depth_max)} deep`} — ${holeMatch(g.diameter)}`),
      '',
      `Bodies: ${st.bodies} · Faces: ${st.faces} · Edges: ${st.edges}`,
      `Faces by type: ${Object.entries(this.meta.faces.type.reduce((o, t) => { o[t] = (o[t] || 0) + 1; return o; }, {})).map(([k, v]) => `${k} ${v}`).join(', ')}`,
    ].filter((x) => x !== null);
    const text = lines.join('\n');
    d.setBody(h('div', { style: { display: 'flex', flexDirection: 'column', height: '100%', gap: '6px' } },
      h('div', { class: 'row' }, h('button', { class: 'btn primary', onclick: () => copyText(text).then(() => toast('Quote summary copied')) }, 'Copy to Clipboard'),
        h('button', { class: 'btn', onclick: () => this.material() }, 'Material…'), h('span', { class: 'grow' }),
        h('span', { class: 'subtle', text: 'Exact from the CAD surfaces' })),
      h('div', { class: 'report', style: { flex: '1' }, text })));
  }

  // ================================================================== Material
  material() {
    const app = this.app;
    if (!app.active) return;
    const cur = app.active.material;
    let pick = cur ? { ...cur } : null;
    const list = h('div', { style: { height: '320px', overflow: 'auto', border: '1px solid var(--line-2)' } });
    const fromFile = app.meta?.material ? { ...app.meta.material, fromFile: true } : null;
    const draw = () => {
      const fileRows = fromFile ? [h('div', { class: 'fx-section', text: 'From the file' }), (() => {
        const row = h('div', { class: `fnode${pick?.fromFile ? ' sel' : ''}`, style: { paddingLeft: '14px' } },
          h('span', { class: 'ficon', html: tool('material') }), h('span', { class: 'fname', text: fromFile.name }),
          h('span', { class: 'fnote', text: fromFile.density != null ? `${fromFile.density} g/cm³` : 'each part its own' }));
        row.addEventListener('click', () => { pick = { ...fromFile }; draw(); dens.value = fromFile.density ?? ''; });
        row.addEventListener('dblclick', () => { pick = { ...fromFile }; apply(); });
        return row;
      })()] : [];
      list.replaceChildren(...fileRows, ...MATERIALS.flatMap((g) => [
        h('div', { class: 'fx-section', text: g.group }),
        ...g.items.map(([name, rho]) => {
          const row = h('div', { class: `fnode${pick?.name === name ? ' sel' : ''}`, style: { paddingLeft: '14px' } },
            h('span', { class: 'ficon', html: tool('material') }), h('span', { class: 'fname', text: name }), h('span', { class: 'fnote', text: `${rho} g/cm³` }));
          row.addEventListener('click', () => { pick = { name, density: rho }; draw(); dens.value = rho; });
          row.addEventListener('dblclick', () => { pick = { name, density: rho }; apply(); });
          return row;
        }),
      ]));
    };
    const dens = h('input', { class: 'inp', style: { width: '90px' }, value: pick?.density ?? '', placeholder: 'g/cm³' });
    const apply = () => {
      const v = parseFloat(dens.value);
      if (pick && Number.isFinite(v) && v > 0 && !(pick.perBody && dens.value === '')) pick.density = v;
      else if (!pick && Number.isFinite(v) && v > 0) pick = { name: 'Custom', density: v };
      app.active.material = pick;
      app.manager.refresh();
      if (this.dialogs.mass && !this.dialogs.mass.closed) this._computeMass();
      d.close();
      if (pick) toast(`Material: ${pick.name}`);
    };
    draw();
    const d = this._dialog('material', {
      title: 'Material', icon: 'material', width: 420, body: h('div', { class: 'stack' }, list,
        h('div', { class: 'row' }, h('span', { text: 'Density (g/cm³)' }), dens, h('span', { class: 'grow' }),
          h('button', { class: 'btn', onclick: () => { app.active.material = null; app.manager.refresh(); if (this.dialogs.mass && !this.dialogs.mass.closed) this._computeMass(); d.close(); } }, 'Remove'),
          h('button', { class: 'btn primary', onclick: apply }, 'Apply'))),
    });
  }

  // ================================================================== Options
  options(section = 'display') {
    const app = this.app, p = app.prefs, v = this.viewer;
    const pages = [
      { id: 'display', label: 'Display' }, { id: 'mouse', label: 'Mouse' }, { id: 'performance', label: 'Performance' },
      { id: 'units', label: 'Units (document)' },
    ];
    let cur = section;
    const content = h('div', { style: { flex: '1', paddingLeft: '14px', overflow: 'auto' } });
    const nav = h('div', { style: { width: '150px', borderRight: '1px solid var(--line)' } });
    const chk = (label, val, fn) => h('label', { class: 'chk', style: { padding: '3px 0' } }, h('input', { type: 'checkbox', checked: val, onchange: (e) => fn(e.target.checked) }), label);
    const seg = (opts, val, fn) => h('div', { class: 'seg' }, ...opts.map(([k, label]) => h('button', { class: k === val ? 'on' : '', text: label, onclick: () => { fn(k); draw(); } })));
    const field = (label, ctl) => h('div', { class: 'pm-row', style: { margin: '6px 0' } }, h('label', { text: label, style: { minWidth: '150px' } }), ctl);
    const draw = () => {
      nav.replaceChildren(h('div', { class: 'fx-section', text: 'System Options' }), ...pages.slice(0, 3).map(navItem),
        h('div', { class: 'fx-section', text: 'Document Properties' }), ...pages.slice(3).map(navItem));
      let body;
      if (cur === 'display') body = [
        field('Interface', seg([['light', 'Light'], ['dark', 'Dark']], p.theme, (k) => app.setTheme(k))),
        field('Up direction', seg([['y', 'Y up (SolidWorks)'], ['z', 'Z up']], v.upAxis, (k) => { v.setUpAxis(k); app.save({ upAxis: k }); v.setView('iso'); })),
        field('Projection', seg([['ortho', 'Orthographic'], ['persp', 'Perspective']], v.rig.perspective ? 'persp' : 'ortho', (k) => { if ((k === 'persp') !== v.rig.perspective) app.run('perspective'); })),
        chk('Silhouette edges on curved faces', v.showSilhouettes, (on) => { v.showSilhouettes = on; v.setStyle(v.style); app.save({ silhouettes: on }); }),
        chk('View cube in the corner', v.showCube, (on) => { v.showCube = on; app.save({ viewCube: on }); v.requestRender(); app.shell.refresh(); }),
        chk('Highlight items under the cursor', p.hoverHighlight !== false, (on) => app.save({ hoverHighlight: on })),
        chk('Context toolbar next to a selection', p.contextToolbar !== false, (on) => app.save({ contextToolbar: on })),
        chk('Seam edges', v.showSeams, (on) => v.setShowSeams(on)),
      ];
      else if (cur === 'mouse') body = [
        field('Mouse buttons', seg([['sw', 'SolidWorks'], ['simple', 'Left-drag rotates']], p.mouse, (k) => { app.save({ mouse: k }); v.mouseMode = k; app.status(); })),
        h('div', { class: 'hint', style: { margin: '4px 0 10px' }, html: p.mouse === 'sw'
          ? 'Middle-drag rotates, Ctrl+middle-drag pans, Shift+middle-drag zooms. Left-drag draws a selection box (left-to-right: window, right-to-left: crossing). Right-drag shows mouse gestures.'
          : 'Left-drag rotates, right-drag pans, middle-drag rotates. Good for laptops without a middle button.' }),
        chk('Reverse wheel zoom direction (roll away from you to zoom in)', p.wheelReverse, (on) => { app.save({ wheelReverse: on }); v.wheelReverse = on; }),
      ];
      else if (cur === 'performance') body = [
        field('Image quality', seg([['coarse', 'Coarse (fast)'], ['normal', 'Normal'], ['fine', 'Fine (smooth)']], p.quality, (k) => { app.save({ quality: k }); if (app.meta?.kind === 'brep') app.reload(k); })),
        h('div', { class: 'hint', text: 'How finely curved faces are drawn. Measuring always uses the exact geometry. Files you have opened before load from a cache at the same quality.' }),
      ];
      else body = [
        h('div', { class: 'fx-section', style: { padding: '0 0 6px' }, text: 'Unit system' }),
        ...Object.entries(SYSTEMS).map(([k, s]) => h('label', { class: 'chk', style: { padding: '3px 0' } },
          h('input', { type: 'radio', name: 'us', checked: app.units.system === k, onchange: () => { app.setSystem(k); draw(); } }), s.name)),
        field('Length decimals', h('select', { class: 'inp', style: { width: '80px' }, onchange: (e) => { app.setSystem(app.units.system, +e.target.value); draw(); } },
          ...[0, 1, 2, 3, 4, 5, 6].map((n) => h('option', { value: n, text: String(n), selected: n === app.units.decimals })))),
        h('div', { class: 'hint', text: `Lengths in ${LENGTH[app.units.unit].label}, mass in ${app.units.massUnit}. Angles in degrees (2 decimals).` }),
      ];
      content.replaceChildren(h('div', { style: { fontWeight: 600, fontSize: '13px', marginBottom: '8px' }, text: pages.find((x) => x.id === cur).label }), ...body);
    };
    const navItem = (pg) => {
      const el = h('div', { class: `fnode${pg.id === cur ? ' sel' : ''}`, style: { paddingLeft: '12px' }, text: pg.label });
      el.addEventListener('click', () => { cur = pg.id; draw(); });
      return el;
    };
    draw();
    const d = this._dialog('options', { title: 'System Options', icon: 'options', width: 640, height: 430,
      body: h('div', { style: { display: 'flex', height: '100%' } }, nav, content),
      foot: [h('button', { class: 'btn primary', text: 'OK', onclick: () => d.close() })] });
  }

  // ================================================================== help & about
  help() {
    const row = (a, b) => h('div', {}, h('span', { text: a }), h('span', { html: b }));
    const sw = this.app.prefs.mouse === 'sw';
    modal('Mouse and Keyboard', h('div', { class: 'keys' },
      h('h3', { text: `Mouse (${sw ? 'SolidWorks buttons' : 'left-drag rotates'} — change in Options)` }),
      sw ? row('Rotate (about the model\'s centre)', '<kbd>Middle-drag</kbd>') : row('Rotate (about the point under the cursor)', '<kbd>Left-drag</kbd> · <kbd>Middle-drag</kbd>'),
      sw ? row('Rotate about a vertex, edge or face', '<kbd>Middle-click</kbd> it, then <kbd>Middle-drag</kbd> (middle-click empty space to go back)') : null,
      row('Pick a face hidden behind another', 'Right-click › <b>Select Other</b>'),
      row('Pan', sw ? '<kbd>Ctrl</kbd>+<kbd>Middle-drag</kbd>' : '<kbd>Right-drag</kbd> · <kbd>Ctrl</kbd>+<kbd>Middle-drag</kbd>'),
      row('Zoom at the cursor', '<kbd>Wheel</kbd> (roll toward you to zoom in) · <kbd>Shift</kbd>+<kbd>Middle-drag</kbd>'),
      row('Zoom to fit', '<kbd>Middle double-click</kbd> · <kbd>F</kbd>'),
      row('Select · add to selection', '<kbd>Click</kbd> · <kbd>Ctrl</kbd>+<kbd>Click</kbd>'),
      sw ? row('Box select (window · crossing)', '<kbd>Left-drag</kbd> → · ←') : null,
      sw ? row('Mouse gestures (views)', '<kbd>Right-drag</kbd>') : null,
      row('Normal to a flat face', '<kbd>Double-click</kbd> it'),
      row('Shortcut menu', '<kbd>Right-click</kbd>'),
      h('h3', { text: 'Views' }),
      row('Front · Back · Left · Right', '<kbd>Ctrl</kbd>+<kbd>1</kbd>…<kbd>4</kbd>'),
      row('Top · Bottom · Isometric', '<kbd>Ctrl</kbd>+<kbd>5</kbd>…<kbd>7</kbd>'),
      row('Normal To', '<kbd>Ctrl</kbd>+<kbd>8</kbd>'),
      row('View Selector / orientation', '<kbd>Space</kbd>'),
      row('Rotate 15° · 90°', '<kbd>Arrows</kbd> · <kbd>Shift</kbd>+<kbd>Arrows</kbd>'),
      row('Roll · pan', '<kbd>Alt</kbd>+<kbd>←</kbd><kbd>→</kbd> · <kbd>Ctrl</kbd>+<kbd>Arrows</kbd>'),
      row('Zoom out · in', '<kbd>Z</kbd> · <kbd>Shift</kbd>+<kbd>Z</kbd>'),
      row('Previous view', '<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd>'),
      h('h3', { text: 'Commands' }),
      row('Shortcut bar', '<kbd>S</kbd>'),
      row('Display style (cycle) · perspective', '<kbd>D</kbd> · <kbd>P</kbd>'),
      row('Hide body under cursor · show all', '<kbd>Tab</kbd> · <kbd>Shift</kbd>+<kbd>Tab</kbd>'),
      row('Show all bodies', '<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>H</kbd>'),
      row('Rebuild (reload file)', '<kbd>Ctrl</kbd>+<kbd>B</kbd>'),
      row('FeatureManager tree', '<kbd>F9</kbd>'),
      row('Search commands', '<kbd>Ctrl</kbd>+<kbd>F</kbd>'),
      row('Copy measurement · picture', '<kbd>Ctrl</kbd>+<kbd>C</kbd> · <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>C</kbd>'),
      row('Open · close · next document', '<kbd>Ctrl</kbd>+<kbd>O</kbd> · <kbd>Ctrl</kbd>+<kbd>W</kbd> · <kbd>Ctrl</kbd>+<kbd>Tab</kbd>'),
    ), { width: 760, icon: 'select' });
  }

  about() {
    modal(`About ${PRODUCT}`, h('div', { class: 'stack', style: { alignItems: 'center', textAlign: 'center', padding: '10px 8px' } },
      h('img', { src: 'img/icon.svg', style: { height: '84px' } }),
      h('div', { style: { font: '600 20px var(--brand)', marginTop: '4px' }, text: `${PRODUCT} 2026` }),
      h('div', { style: { display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--muted)' } }, 'by',
        h('img', { src: 'img/brand/wmc-logo.svg', style: { height: '28px', background: '#fff', padding: '3px 6px', borderRadius: '4px' } })),
      h('div', { style: { font: 'italic 13px var(--serif)', color: 'var(--muted)' }, text: 'The difficult we do right away, the impossible will take a little longer.' }),
      h('div', { class: 'hint', html: 'Wagner Machine Co. · 3200 Farber Drive, Champaign, Illinois<br>Reads STEP, IGES, SolidWorks, Parasolid and mesh files. Geometry by OpenCASCADE (via gmsh); graphics by three.js.' })),
    { width: 470 });
  }
}

function tensorLines(p, t, u) {
  const ax = ['x', 'y', 'z'];
  return ax.map((a, i) => `\t${ax.map((b, j) => `${p}${a}${b} = ${u.inertia(t[i][j])}`).join('\t')}`);
}

// smallest round bar along one of the box axes: enclosing circle of the drawn vertices
function roundStock(viewer, box) {
  const m = viewer.model;
  if (!m) return null;
  const pos = m.pos;
  const n = pos.length / 3;
  const stepI = Math.max(1, Math.floor(n / 40000));
  let best = null;
  for (const axis of box.axes) {
    const a = new THREE.Vector3(...axis).normalize();
    const u1 = new THREE.Vector3(Math.abs(a.x) < 0.9 ? 1 : 0, Math.abs(a.x) < 0.9 ? 0 : 1, 0).cross(a).normalize();
    const u2 = new THREE.Vector3().crossVectors(a, u1);
    const pts = [];
    let lo = Infinity, hi = -Infinity;
    for (let i = 0; i < n; i += stepI) {
      const x = pos[i * 3], y = pos[i * 3 + 1], z = pos[i * 3 + 2];
      const t = x * a.x + y * a.y + z * a.z;
      lo = Math.min(lo, t); hi = Math.max(hi, t);
      pts.push([x * u1.x + y * u1.y + z * u1.z, x * u2.x + y * u2.y + z * u2.z]);
    }
    const c = minCircle(pts);
    const vol = Math.PI * c.r * c.r * (hi - lo);
    if (!best || vol < best.vol) best = { d: 2 * c.r, len: hi - lo, vol };
  }
  return best;
}

function minCircle(points) {
  const P = points.slice();
  for (let i = P.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [P[i], P[j]] = [P[j], P[i]]; }
  let c = { x: 0, y: 0, r: -1 };
  const inside = (p) => (p[0] - c.x) ** 2 + (p[1] - c.y) ** 2 <= c.r * c.r * (1 + 1e-9) + 1e-12;
  const two = (a, b) => ({ x: (a[0] + b[0]) / 2, y: (a[1] + b[1]) / 2, r: Math.hypot(a[0] - b[0], a[1] - b[1]) / 2 });
  const three = (a, b, d) => {
    const bx = b[0] - a[0], by = b[1] - a[1], cx = d[0] - a[0], cy = d[1] - a[1];
    const D = 2 * (bx * cy - by * cx);
    if (Math.abs(D) < 1e-18) return two(a, b);
    const ux = (cy * (bx * bx + by * by) - by * (cx * cx + cy * cy)) / D;
    const uy = (bx * (cx * cx + cy * cy) - cx * (bx * bx + by * by)) / D;
    return { x: ux + a[0], y: uy + a[1], r: Math.hypot(ux, uy) };
  };
  for (let i = 0; i < P.length; i++) {
    if (c.r >= 0 && inside(P[i])) continue;
    c = { x: P[i][0], y: P[i][1], r: 0 };
    for (let j = 0; j < i; j++) {
      if (inside(P[j])) continue;
      c = two(P[i], P[j]);
      for (let k = 0; k < j; k++) if (!inside(P[k])) c = three(P[i], P[j], P[k]);
    }
  }
  return c;
}

// what a hole of this diameter (mm) most likely is: tap drill, clearance hole or a standard drill
const IN = 25.4;
const TAPS = [['#0-80', 0.0469], ['#2-56', 0.07], ['#4-40', 0.089], ['#6-32', 0.1065], ['#8-32', 0.136], ['#10-24', 0.1495], ['#10-32', 0.159],
  ['1/4-20', 0.201], ['1/4-28', 0.213], ['5/16-18', 0.257], ['5/16-24', 0.272], ['3/8-16', 0.3125], ['3/8-24', 0.332], ['7/16-14', 0.368],
  ['1/2-13', 0.4219], ['1/2-20', 0.4531], ['5/8-11', 0.5312], ['3/4-10', 0.6562]].map(([n, d]) => [n, d * IN])
  .concat([['M2x0.4', 1.6], ['M2.5x0.45', 2.05], ['M3x0.5', 2.5], ['M4x0.7', 3.3], ['M5x0.8', 4.2], ['M6x1', 5.0], ['M8x1.25', 6.8], ['M10x1.5', 8.5], ['M12x1.75', 10.2], ['M16x2', 14.0]]);
const CLEAR = [['#4', 0.116, 0.12], ['#6', 0.144, 0.15], ['#8', 0.169, 0.177], ['#10', 0.196, 0.201], ['1/4', 0.257, 0.266], ['5/16', 0.323, 0.332],
  ['3/8', 0.386, 0.397], ['1/2', 0.516, 0.531], ['5/8', 0.641, 0.656]].map(([n, a, b]) => [n, a * IN, b * IN])
  .concat([['M3', 3.2, 3.4], ['M4', 4.3, 4.5], ['M5', 5.3, 5.5], ['M6', 6.4, 6.6], ['M8', 8.4, 9.0], ['M10', 10.5, 11.0], ['M12', 13.0, 13.5]]);
const NUMBER_DRILLS = [0.228, 0.221, 0.213, 0.209, 0.2055, 0.204, 0.201, 0.199, 0.196, 0.1935, 0.191, 0.189, 0.185, 0.182, 0.18, 0.177, 0.173, 0.1695, 0.166, 0.161,
  0.159, 0.157, 0.154, 0.152, 0.1495, 0.147, 0.144, 0.1405, 0.136, 0.1285, 0.12, 0.116, 0.113, 0.111, 0.11, 0.1065, 0.104, 0.1015, 0.0995, 0.098, 0.096, 0.0935,
  0.089, 0.086, 0.082, 0.081, 0.0785, 0.076, 0.073, 0.07, 0.067, 0.0635, 0.0595, 0.055, 0.052, 0.0465, 0.043, 0.042, 0.041, 0.04];
const LETTER_DRILLS = [0.234, 0.238, 0.242, 0.246, 0.25, 0.257, 0.261, 0.266, 0.272, 0.277, 0.281, 0.29, 0.295, 0.302, 0.316, 0.323, 0.332, 0.339, 0.348, 0.358, 0.368, 0.377, 0.386, 0.397, 0.404, 0.413];

export function holeMatch(d) {
  const tolTap = Math.max(0.03, d * 0.006);
  const tap = TAPS.map(([n, td]) => [n, Math.abs(td - d)]).filter(([, e]) => e <= tolTap).sort((a, b) => a[1] - b[1])[0];
  if (tap) return `Tap drill for ${tap[0]}`;
  const clr = CLEAR.find(([, a, b]) => Math.abs(d - a) <= 0.03 || Math.abs(d - b) <= 0.03);
  if (clr) return `Clearance for ${clr[0]} screw (${Math.abs(d - clr[1]) <= Math.abs(d - clr[2]) ? 'close' : 'free'} fit)`;
  const inch = d / IN;
  const frac64 = Math.round(inch * 64);
  if (frac64 > 0 && Math.abs(frac64 / 64 - inch) < 0.0006) return `${fraction(frac64)}" drill`;
  const num = NUMBER_DRILLS.findIndex((x) => Math.abs(x - inch) < 0.0006);
  if (num >= 0) return `#${num + 1} drill (${inch.toFixed(4)}")`;
  const let_ = LETTER_DRILLS.findIndex((x) => Math.abs(x - inch) < 0.0006);
  if (let_ >= 0) return `Letter ${String.fromCharCode(65 + let_)} drill (${inch.toFixed(4)}")`;
  const mm = Math.round(d * 10) / 10;
  if (Math.abs(mm - d) < 0.01) return `${mm} mm drill`;
  return 'Bored / non-standard';
}

function fraction(n64) {
  let n = n64, dnm = 64;
  while (n % 2 === 0 && dnm > 1) { n /= 2; dnm /= 2; }
  const whole = Math.floor(n / dnm);
  const rest = n % dnm;
  return whole ? (rest ? `${whole}-${rest}/${dnm}` : `${whole}`) : `${rest}/${dnm}`;
}

void icon;
