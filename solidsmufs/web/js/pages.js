// PropertyManager pages: Section View, Appearance, Bounding Box, Draft Analysis, Zebra Stripes,
// Curvature. Each opens in the left panel with OK / Cancel, like SolidWorks.
import * as THREE from 'three';
import { api } from './api.js';
import { tool } from './icons.js';
import { h, spinBox, toast, copyText } from './ui.js';

const PLANES = { front: ['Front Plane', [0, 0, 1]], top: ['Top Plane', [0, 1, 0]], right: ['Right Plane', [1, 0, 0]] };
const PALETTE = ['#c9ced6', '#e8e8e8', '#9aa3ae', '#5a6270', '#2b2f36', '#213367', '#3a6fd8', '#7fb0f0', '#2f9e46', '#9bd06f',
  '#f2b33d', '#f08c2b', '#d9473f', '#a02f6b', '#7b4fc0', '#c08a52', '#d8c3a5', '#b87333'];

export class Pages {
  constructor(app) {
    this.app = app;
    this.sec = { plane: 'front', custom: null, offset: 0, rotX: 0, rotY: 0, flip: false, caps: true, keepColor: true, capColor: '#c8a050' };
    this.draftOpts = { dir: 'top', custom: null, angle: 1, reverse: false };
    this.zebraOpts = { count: 14, width: 0.5 };
    this.bboxOpts = { mode: 'oriented', hidden: false };
  }

  get viewer() { return this.app.viewer; }
  get meta() { return this.app.meta; }
  get mgr() { return this.app.manager; }

  close(ok) { if (this.mgr.page) this.mgr.closePM(ok); }
  selectionChanged() { if (this.mgr.page?.onSelection) { this.mgr.page.onSelection(); this.mgr.updatePM(); } }

  // ================================================================== section view
  toggleSection() {
    if (this.viewer.section && this.mgr.page?.id !== 'section') { this.viewer.setSection(null); this.app.shell.refresh(); return; }
    if (this.mgr.page?.id === 'section') { this.close(false); return; }
    this.section();
  }

  section(opts = {}) {
    const s = this.sec;
    if (opts.plane) { s.plane = opts.plane; s.custom = null; s.rotX = s.rotY = 0; s.reset = true; }
    const pf = this.app.planarSelection();
    if (!opts.plane && pf && !this.viewer.section) {
      const p = this.meta.faces.params[pf.index];
      s.custom = { label: `Face<${pf.index + 1}>`, normal: p.normal, origin: p.origin };
      s.reset = true;
    }
    this._applySection(true);
    const u = this.app.units;
    const page = {
      id: 'section', title: 'Section View', icon: 'sectionView',
      message: 'Graphics-only section. Measurements still use the whole part.',
      groups: () => {
        const [lo, hi] = this._range(this._normal());
        const planeBtns = h('div', { class: 'seg' }, ...Object.entries(PLANES).map(([k, [label]]) => {
          const b = h('button', { class: !s.custom && s.plane === k ? 'on' : '', text: label.split(' ')[0] });
          b.addEventListener('click', () => { s.plane = k; s.custom = null; s.rotX = s.rotY = 0; s.reset = true; this._applySection(true); this.mgr.updatePM(); });
          return b;
        }));
        const facePf = this.app.planarSelection();
        const slider = h('input', { type: 'range', min: lo, max: hi, step: (hi - lo) / 1000 || 0.01, value: s.offset });
        const off = spinBox(+(s.offset / u.u.factor).toFixed(u.decimals), {
          step: Math.pow(10, -Math.min(u.decimals, 3)) * 10, format: (v) => (+v).toFixed(u.decimals),
          onChange: (v) => { s.offset = u.toMm(v); slider.value = s.offset; this._applySection(); },
        });
        slider.addEventListener('input', () => { s.offset = +slider.value; off.querySelector('input').value = (s.offset / u.u.factor).toFixed(u.decimals); this._applySection(); });
        const rot = (key, label) => h('div', { class: 'pm-row' }, h('label', { text: label }),
          spinBox(s[key], { step: 5, format: (v) => (+v).toFixed(1), onChange: (v) => { s[key] = v; this._applySection(); } }), h('span', { text: '°' }));
        return [
          { title: 'Section 1', body: [
            h('div', { class: 'pm-row' }, h('label', { text: 'Reference' }), planeBtns),
            h('div', { class: 'pm-row' }, h('label', { text: '' }), h('button', { class: `btn${s.custom ? ' primary' : ''}`, disabled: !facePf && !s.custom,
              title: 'Cut along the selected flat face',
              onclick: () => {
                const f = this.app.planarSelection();
                if (!f) return;
                const p = this.meta.faces.params[f.index];
                s.custom = { label: `Face<${f.index + 1}>`, normal: p.normal, origin: p.origin };
                s.rotX = s.rotY = 0; s.reset = true;
                this._applySection(true);
                this.mgr.updatePM();
              } }, h('span', { html: tool('face'), style: { width: '15px', height: '15px', display: 'inline-flex' } }), s.custom ? s.custom.label : 'Selected Face')),
            h('div', { class: 'pm-row' }, h('label', { text: `Offset (${u.label})` }), off),
            slider,
            rot('rotX', 'Rotate X'), rot('rotY', 'Rotate Y'),
            h('label', { class: 'chk' }, h('input', { type: 'checkbox', checked: s.flip, onchange: (e) => { s.flip = e.target.checked; this._applySection(); } }), 'Reverse section direction'),
          ] },
          { title: 'Section Options', body: [
            h('label', { class: 'chk' }, h('input', { type: 'checkbox', checked: s.caps, onchange: (e) => { s.caps = e.target.checked; this._applySection(); this.mgr.updatePM(); } }), 'Show section cap'),
            s.caps ? h('label', { class: 'chk' }, h('input', { type: 'checkbox', checked: s.keepColor, onchange: (e) => { s.keepColor = e.target.checked; this._applySection(); this.mgr.updatePM(); } }), 'Keep cap color (body color)') : null,
            s.caps && !s.keepColor ? h('div', { class: 'pm-row' }, h('label', { text: 'Cap color' }), h('input', { type: 'color', value: s.capColor, oninput: (e) => { s.capColor = e.target.value; this._applySection(); } })) : null,
            h('button', { class: 'btn', onclick: () => this.viewer.normalTo(this._normal().toArray()) }, h('span', { html: tool('normalTo'), style: { width: '15px', height: '15px', display: 'inline-flex' } }), 'Normal To Section'),
          ] },
        ];
      },
      onOK: () => this.app.shell.refresh(),
      onCancel: () => { this.viewer.setSection(null); this.app.shell.refresh(); },
    };
    this.mgr.openPM(page);
    this.app.shell.refresh();
  }

  _normal() {
    const s = this.sec;
    const base = s.custom ? new THREE.Vector3(...s.custom.normal) : new THREE.Vector3(...PLANES[s.plane][1]);
    const a = Math.abs(base.y) < 0.9 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0);
    const ux = new THREE.Vector3().crossVectors(base, a).normalize();
    const uy = new THREE.Vector3().crossVectors(base, ux).normalize();
    return base.clone().applyAxisAngle(ux, THREE.MathUtils.degToRad(s.rotX)).applyAxisAngle(uy, THREE.MathUtils.degToRad(s.rotY)).normalize();
  }

  _range(n) {
    const box = this.viewer.model.box;
    let lo = Infinity, hi = -Infinity;
    for (let i = 0; i < 8; i++) {
      const c = new THREE.Vector3(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z);
      lo = Math.min(lo, c.dot(n)); hi = Math.max(hi, c.dot(n));
    }
    return [lo, hi];
  }

  _applySection(reset = false) {
    if (!this.viewer.model) return;
    const s = this.sec;
    const n = this._normal();
    const [lo, hi] = this._range(n);
    if (reset || s.reset || !(s.offset >= lo && s.offset <= hi)) {
      s.offset = s.custom?.origin ? new THREE.Vector3(...s.custom.origin).dot(n) : (lo + hi) / 2;
      s.reset = false;
    }
    const keep = s.flip ? n.clone() : n.clone().negate();
    this.viewer.capsOn = s.caps;
    this.viewer.capColor = s.keepColor ? null : s.capColor;
    this.viewer.setSection(new THREE.Plane(keep, s.flip ? -s.offset : s.offset));
  }

  // ================================================================== appearance
  appearance(bodies = null) {
    if (!this.meta) return;
    const app = this.app;
    let targets = bodies || app.selectedBodies();
    if (!targets.length) targets = this.meta.bodies.map((_, i) => i);
    const before = targets.map((b) => ({ b, color: this.viewer.bodies[b]?.override || null, opacity: this.viewer.bodies[b]?.opacity ?? 1 }));
    const toHex = (rgb) => '#' + rgb.map((c) => Math.round(c * 255).toString(16).padStart(2, '0')).join('');
    const fromHex = (hx) => [1, 3, 5].map((i) => parseInt(hx.slice(i, i + 2), 16) / 255);
    const apply = (hx) => { targets.forEach((b) => this.viewer.setBodyColor(b, fromHex(hx))); app.manager.refresh(); app.manager.updatePM(); };
    const page = {
      id: 'appearance', title: 'Appearance', icon: 'appearance',
      onSelection: () => { const s = app.selectedBodies(); if (s.length) targets = s; },
      groups: () => {
        const cur = toHex(this.viewer.bodyColor(targets[0]));
        const opacity = this.viewer.bodies[targets[0]]?.opacity ?? 1;
        return [
          { title: 'Selected Geometry', body: [
            h('div', { class: 'selbox active' }, ...targets.map((b) => h('div', { class: 'si' }, h('span', { html: tool('body'), style: { width: '13px', height: '13px', display: 'inline-flex' } }), this.meta.bodies[b].name))),
            h('div', { class: 'hint', text: 'Select bodies in the graphics area or the tree to change them.' }),
          ] },
          { title: 'Color', body: [
            h('div', { class: 'swatches', style: { padding: 0 } }, ...PALETTE.map((c) => h('button', { style: { background: c }, title: c, onclick: () => apply(c) }))),
            h('div', { class: 'pm-row' }, h('label', { text: 'Custom' }), h('input', { type: 'color', value: cur, oninput: (e) => apply(e.target.value) })),
            h('button', { class: 'btn', onclick: () => { targets.forEach((b) => this.viewer.setBodyColor(b, null)); app.manager.refresh(); app.manager.updatePM(); } }, 'Use the file\'s colors'),
          ] },
          { title: 'Optical Properties', body: [
            h('div', { class: 'pm-row' }, h('label', { text: 'Transparency' }),
              h('input', { type: 'range', min: 0, max: 90, value: Math.round((1 - opacity) * 100), class: 'grow',
                oninput: (e) => { targets.forEach((b) => this.viewer.setBodyOpacity(b, 1 - e.target.value / 100)); app.manager.refresh(); } })),
          ] },
        ];
      },
      onOK: () => app.manager.refresh(),
      onCancel: () => { before.forEach(({ b, color, opacity }) => { this.viewer.setBodyColor(b, color); this.viewer.setBodyOpacity(b, opacity); }); app.manager.refresh(); },
    };
    this.mgr.openPM(page);
  }

  // ================================================================== bounding box
  async boundingBox() {
    if (!this.meta) return;
    const app = this.app, o = this.bboxOpts;
    let result = null, busy = false;
    const compute = async () => {
      busy = true;
      this.mgr.updatePM();
      const bodies = this.meta.bodies.map((_, i) => i).filter((i) => o.hidden || this.viewer.bodies[i]?.visible);
      try { result = await api.bbox(app.active.id, bodies, o.mode); } catch (e) { result = { error: e.message }; }
      busy = false;
      if (result && !result.error) this.viewer.showBox(result);
      this.mgr.updatePM();
      app.manager.refresh();
    };
    const u = app.units;
    const page = {
      id: 'bbox', title: 'Bounding Box', icon: 'bbox',
      groups: () => [
        { title: 'Reference Face/Plane', body: [
          h('label', { class: 'chk' }, h('input', { type: 'radio', name: 'bbm', checked: o.mode === 'oriented', onchange: () => { o.mode = 'oriented'; compute(); } }), 'Best fit (smallest box, for stock)'),
          h('label', { class: 'chk' }, h('input', { type: 'radio', name: 'bbm', checked: o.mode === 'world', onchange: () => { o.mode = 'world'; compute(); } }), 'Aligned to Front / Top / Right planes'),
        ] },
        { title: 'Options', body: [
          h('label', { class: 'chk' }, h('input', { type: 'checkbox', checked: o.hidden, onchange: (e) => { o.hidden = e.target.checked; compute(); } }), 'Include hidden bodies'),
        ] },
        { title: 'Size', body: busy ? [h('div', { class: 'row' }, h('span', { class: 'spin' }), h('span', { class: 'hint', text: 'Finding the exact extents…' }))]
          : result?.error ? [h('div', { class: 'hint', style: { color: 'var(--bad)' }, text: result.error })]
            : result ? (() => {
              const dims = o.mode === 'oriented' ? [...result.size].sort((a, b) => b - a) : result.size;
              const names = o.mode === 'oriented' ? ['Length', 'Width', 'Thickness'] : ['X', 'Y', 'Z'];
              const text = dims.map((d) => u.len(d)).join(' x ');
              return [
                ...dims.map((d, i) => h('div', { class: 'pm-row' }, h('label', { text: names[i] }), h('b', { text: u.len(d) }))),
                h('div', { class: 'pm-row' }, h('label', { text: 'Volume' }), h('b', { text: u.vol(dims[0] * dims[1] * dims[2]) })),
                h('div', { class: 'row' }, h('button', { class: 'btn', onclick: () => copyText(text).then(() => toast('Size copied')) }, 'Copy Size'),
                  h('span', { class: 'subtle', text: 'Exact, from the true surfaces' })),
              ];
            })() : [] },
      ],
      onOK: () => app.manager.refresh(),
      onCancel: () => { this.viewer.showBox(null); app.manager.refresh(); },
    };
    this.mgr.openPM(page);
    compute();
  }

  // ================================================================== analyses
  _dirVector(key, custom) {
    if (custom) return custom.normal;
    return PLANES[key][1];
  }

  draft() {
    if (!this.meta) return;
    if (this.viewer.analysis?.type === 'draft' && this.mgr.page?.id !== 'draft') { this.viewer.setAnalysis(null); this.app.shell.refresh(); return; }
    const o = this.draftOpts;
    const apply = () => {
      const d = new THREE.Vector3(...this._dirVector(o.dir, o.custom));
      if (o.reverse) d.negate();
      this.viewer.setAnalysis({ type: 'draft', dir: d.normalize().toArray(), angle: o.angle });
      this.app.shell.refresh();
    };
    apply();
    const page = {
      id: 'draft', title: 'Draft Analysis', icon: 'draft',
      groups: () => [
        { title: 'Analysis Parameters', body: [
          h('div', { class: 'pm-row' }, h('label', { text: 'Pull direction' }), h('div', { class: 'seg' }, ...Object.entries(PLANES).map(([k, [label]]) => {
            const b = h('button', { class: !o.custom && o.dir === k ? 'on' : '', text: label.split(' ')[0], title: `Normal to the ${label}` });
            b.addEventListener('click', () => { o.dir = k; o.custom = null; apply(); this.mgr.updatePM(); });
            return b;
          }))),
          h('button', { class: 'btn', disabled: !this.app.planarSelection(), onclick: () => {
            const f = this.app.planarSelection();
            o.custom = { normal: this.meta.faces.params[f.index].normal };
            apply(); this.mgr.updatePM();
          } }, 'Use Selected Face'),
          h('div', { class: 'pm-row' }, h('label', { text: 'Draft angle' }), spinBox(o.angle, { step: 0.5, format: (v) => (+v).toFixed(2), onChange: (v) => { o.angle = Math.max(0, v); apply(); } }), h('span', { text: '°' })),
          h('label', { class: 'chk' }, h('input', { type: 'checkbox', checked: o.reverse, onchange: (e) => { o.reverse = e.target.checked; apply(); } }), 'Reverse direction'),
        ] },
        { title: 'Color Settings', body: [
          legend('#3aa856', 'Positive draft'), legend('#f3c13a', 'Requires draft'), legend('#d9473f', 'Negative draft'),
        ] },
      ],
      onOK: () => this.app.shell.refresh(),
      onCancel: () => { this.viewer.setAnalysis(null); this.app.shell.refresh(); },
    };
    this.mgr.openPM(page);
  }

  zebra() {
    if (!this.meta) return;
    if (this.viewer.analysis?.type === 'zebra' && this.mgr.page?.id !== 'zebra') { this.viewer.setAnalysis(null); this.app.shell.refresh(); return; }
    const o = this.zebraOpts;
    const apply = () => { this.viewer.setAnalysis({ type: 'zebra', count: o.count, width: o.width }); this.app.shell.refresh(); };
    apply();
    this.mgr.openPM({
      id: 'zebra', title: 'Zebra Stripes', icon: 'zebra',
      message: 'Stripes that run smoothly across an edge mean the faces meet smoothly; a kink or jump shows a break in curvature or tangency.',
      groups: () => [{ title: 'Settings', body: [
        h('div', { class: 'pm-row' }, h('label', { text: 'Stripes' }), h('input', { type: 'range', min: 4, max: 48, value: o.count, class: 'grow', oninput: (e) => { o.count = +e.target.value; apply(); } })),
        h('div', { class: 'pm-row' }, h('label', { text: 'Width' }), h('input', { type: 'range', min: 10, max: 90, value: o.width * 100, class: 'grow', oninput: (e) => { o.width = e.target.value / 100; apply(); } })),
      ] }],
      onOK: () => this.app.shell.refresh(),
      onCancel: () => { this.viewer.setAnalysis(null); this.app.shell.refresh(); },
    });
  }

  curvature() {
    if (!this.meta) return;
    if (this.viewer.analysis?.type === 'curvature') { this.viewer.setAnalysis(null); this.app.shell.refresh(); return; }
    const size = this.viewer.rig.radius * 2;
    this.viewer.setAnalysis({ type: 'curvature', scale: 1 / Math.max(size * 0.02, 1e-6) });
    this.app.shell.refresh();
    toast('Curvature on: blue is flat, red is tightly curved. Click Curvature again to turn it off.', 'info', 4200);
  }
}

function legend(color, label) {
  return h('div', { class: 'row' }, h('span', { style: { width: '22px', height: '13px', background: color, border: '1px solid rgba(0,0,0,.25)', borderRadius: '2px', display: 'inline-block' } }), h('span', { text: label }));
}
