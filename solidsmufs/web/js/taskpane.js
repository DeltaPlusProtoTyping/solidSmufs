// The task pane on the right edge: Home (recent documents), File Explorer, Appearances & Scenes,
// and Custom Properties of the open file. Tabs open a flyout over the graphics area.
import { api } from './api.js';
import { tool, icon } from './icons.js';
import { h, toast } from './ui.js';
import { SCENES, PRODUCT } from './consts.js';

const TABS = [
  { id: 'home', icon: 'tpHome', title: 'Wagner Machine Resources' },
  { id: 'explorer', icon: 'tpExplorer', title: 'File Explorer' },
  { id: 'appearance', icon: 'tpAppearance', title: 'Appearances & Scenes' },
  { id: 'props', icon: 'tpProps', title: 'Custom Properties' },
];
const MODEL_EXTS = ['step', 'stp', 'igs', 'iges', 'sldprt', 'sldasm', 'x_t', 'x_b', 'xmt_txt', 'xmt_bin', 'brep', 'brp', 'stl', 'obj', 'ply', 'off', '3mf', 'glb', 'gltf'];
const SWATCHES = ['#c9ced6', '#e6e6e6', '#a7aeb9', '#6e7888', '#3b414b', '#1b1e23', '#213367', '#3a6fd8', '#8fb6ee', '#2f9e46', '#a7d77a', '#f2b33d',
  '#f08c2b', '#d9473f', '#a02f6b', '#7b4fc0', '#c08a52', '#e3cfae'];

export class TaskPane {
  constructor(app) {
    this.app = app;
    this.tab = null;
    this.visible = true;
    this.path = null;
    this.strip = document.getElementById('tp-strip');
    this.fly = document.getElementById('tp-flyout');
    this.strip.replaceChildren(...TABS.map((t) => {
      const b = h('button', { class: 'tp-tab', title: t.title, html: tool(t.icon), 'data-tab': t.id });
      b.addEventListener('click', () => (this.tab === t.id ? this.hide() : this.show(t.id)));
      return b;
    }));
    document.addEventListener('pointerdown', (e) => {
      if (this.tab && !this.pinned && !this.fly.contains(e.target) && !this.strip.contains(e.target) && !e.target.closest('#layer')) this.hide();
    });
  }

  toggle() {
    this.visible = !this.visible;
    document.getElementById('taskpane').hidden = !this.visible;
    document.getElementById('workspace').style.gridTemplateColumns = this.visible ? '' : 'var(--mgr-w) 4px 1fr 0';
    setTimeout(() => this.app.viewer.resize(), 30);
  }

  show(tab) {
    if (!this.visible) this.toggle();
    this.tab = tab;
    this.fly.hidden = false;
    this.strip.querySelectorAll('.tp-tab').forEach((b) => b.classList.toggle('on', b.dataset.tab === tab));
    this.render();
  }

  hide() {
    this.tab = null;
    this.fly.hidden = true;
    this.strip.querySelectorAll('.tp-tab').forEach((b) => b.classList.remove('on'));
  }

  refresh() { if (this.tab) this.render(); }

  render() {
    const t = TABS.find((x) => x.id === this.tab);
    const head = h('div', { class: 'tp-head' }, h('span', { html: tool(t.icon), style: { width: '18px', height: '18px', display: 'inline-flex' } }), h('span', { text: t.title }),
      h('span', { class: 'spacer' }),
      h('button', { class: `icon-btn${this.pinned ? ' on' : ''}`, title: 'Keep open', html: icon('pin'), onclick: () => { this.pinned = !this.pinned; this.render(); } }),
      h('button', { class: 'icon-btn', title: 'Close', html: icon('close'), onclick: () => this.hide() }));
    const body = h('div', { class: 'tp-body' });
    this.fly.replaceChildren(head, body);
    if (this.tab === 'home') this._home(body);
    else if (this.tab === 'explorer') this._explorer(body);
    else if (this.tab === 'appearance') this._appearance(body);
    else this._props(body);
  }

  // ------------------------------------------------------------------ home
  _home(body) {
    const app = this.app;
    body.append(
      h('div', { style: { padding: '14px 12px 10px', background: 'var(--title-bg)', color: '#fff' } },
        h('img', { src: 'img/brand/wmc-logo-white.svg', style: { height: '34px' } }),
        h('div', { style: { font: 'italic 12px var(--serif)', marginTop: '6px', opacity: 0.85 }, text: 'The difficult we do right away, the impossible will take a little longer.' })),
      h('div', { class: 'fx-section', text: 'Get started' }),
      ...['open', 'explorer', 'help', 'options'].map((id) => {
        const c = app.commands[id];
        return h('div', { class: 'fx-item', onclick: () => { this.hide(); app.run(id); } }, h('span', { class: 'fx-icon', html: tool(c.icon) }), h('span', { class: 'fx-name', text: c.label }));
      }),
      h('div', { class: 'fx-section', text: 'Recent documents' }),
      ...((app.recent || []).length ? app.recent.slice(0, 12).map((r) => h('div', { class: 'fx-item', title: r.path, onclick: () => app.openPath(r.path) },
        h('span', { class: 'fx-icon', html: tool(iconFor(r.name)) }), h('span', { class: 'fx-name', text: r.name }))) : [h('div', { class: 'hint', style: { padding: '4px 12px' }, text: 'Nothing yet.' })]),
      h('div', { class: 'fx-section', text: 'Wagner Machine Co.' }),
      h('div', { class: 'fx-item', onclick: () => window.open('https://wagner-machine.com/', '_blank') }, h('span', { class: 'fx-icon', html: tool('tpHome') }), h('span', { class: 'fx-name', text: 'wagner-machine.com' })),
      h('div', { class: 'hint', style: { padding: '6px 12px 14px' }, text: `${PRODUCT} — AS9100D · ISO 9001:2015 · ITAR registered shop, Champaign IL.` }));
  }

  // ------------------------------------------------------------------ file explorer
  async _explorer(body) {
    const app = this.app;
    const pathBox = h('input', { class: 'inp', value: this.path || '', placeholder: 'Folder path', spellcheck: 'false' });
    const list = h('div');
    const go = async (path) => {
      list.replaceChildren(h('div', { class: 'hint', style: { padding: '10px 12px' } }, h('span', { class: 'spin' })));
      if (!path) {
        let roots;
        try { roots = await api.fsRoots(); } catch (e) { list.replaceChildren(h('div', { class: 'pm-msg', text: e.message })); return; }
        this.path = null;
        pathBox.value = '';
        list.replaceChildren(...[
          h('div', { class: 'fx-section', text: 'Places' }), ...roots.places.map((p) => item(p.name, 'folder', () => go(p.path), p.path)),
          roots.recentDirs?.length ? h('div', { class: 'fx-section', text: 'Recent folders' }) : null, ...(roots.recentDirs || []).map((p) => item(p.name, 'folder', () => go(p.path), p.path)),
          h('div', { class: 'fx-section', text: 'Drives' }), ...roots.drives.map((p) => item(p.name, 'drive', () => go(p.path), p.path))].filter(Boolean));
        return;
      }
      let r;
      try { r = await api.fsList(path); } catch (e) { list.replaceChildren(h('div', { class: 'pm-msg', text: e.message })); return; }
      this.path = r.path;
      pathBox.value = r.path;
      list.replaceChildren(...[
        r.parent ? item('..', 'folder', () => go(r.parent), 'Up one folder') : null,
        ...r.dirs.map((d) => item(d.name, 'folder', () => go(d.path), d.path)),
        ...r.files.map((f) => item(f.name, iconFor(f.name), () => app.openPath(f.path), f.path, fmtSize(f.size))),
        !r.dirs.length && !r.files.length ? h('div', { class: 'hint', style: { padding: '8px 12px' }, text: 'No folders or 3D files here.' }) : null].filter(Boolean));
    };
    const item = (name, ic, fn, title, size) => {
      const el = h('div', { class: 'fx-item', title }, h('span', { class: 'fx-icon', html: tool(ic) }), h('span', { class: 'fx-name', text: name }), size ? h('span', { class: 'fx-size', text: size }) : null);
      el.addEventListener('click', fn);
      return el;
    };
    pathBox.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(pathBox.value.trim()); });
    body.append(h('div', { class: 'fx-path' },
      h('button', { class: 'icon-btn', title: 'Places', html: icon('home'), onclick: () => go(null) }),
      h('button', { class: 'icon-btn', title: 'Up', html: icon('up'), onclick: () => { if (this.path) api.fsList(this.path).then((r) => go(r.parent)).catch(() => go(null)); } }),
      pathBox,
      h('button', { class: 'icon-btn', title: 'Refresh', html: icon('refresh'), onclick: () => go(this.path) })), list);
    go(this.path || (app.meta?.path ? app.meta.path.replace(/[\\/][^\\/]+$/, '') : null));
  }

  // ------------------------------------------------------------------ appearances & scenes
  _appearance(body) {
    const app = this.app, v = app.viewer;
    const targets = () => (app.selectedBodies().length ? app.selectedBodies() : app.meta ? app.meta.bodies.map((_, i) => i) : []);
    body.append(
      h('div', { class: 'fx-section', text: 'Colors' }),
      h('div', { class: 'hint', style: { padding: '0 12px' }, text: app.selectedBodies().length ? 'Applies to the selected bodies.' : 'Applies to every body (select bodies to color just those).' }),
      h('div', { class: 'swatches' }, ...SWATCHES.map((c) => h('button', { style: { background: c }, title: c, onclick: () => {
        if (!app.meta) return;
        const rgb = [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16) / 255);
        targets().forEach((b) => v.setBodyColor(b, rgb));
        app.manager.refresh();
      } }))),
      h('div', { style: { padding: '0 12px 8px' } }, h('button', { class: 'btn', disabled: !app.meta, onclick: () => { targets().forEach((b) => v.setBodyColor(b, null)); app.manager.refresh(); } }, "Use the file's colors")),
      h('div', { class: 'fx-section', text: 'Scenes' }),
      h('div', { class: 'scenes' }, ...SCENES.map((s) => h('button', {
        class: app.prefs.scene === s.id ? 'on' : '',
        style: { background: `linear-gradient(180deg, ${s.bg[0]}, ${s.bg[1]})`, color: s.dark ? '#fff' : '#1b2231' },
        text: s.label, onclick: () => { app.setScene(s.id); this.render(); },
      }))));
  }

  // ------------------------------------------------------------------ custom properties
  _props(body) {
    const app = this.app, m = app.meta;
    if (!m) { body.append(h('div', { class: 'pm-msg', text: 'Open a document to see its properties.' })); return; }
    const st = m.stats || {};
    const rows = [
      ['File name', m.name], ['Folder', m.path ? m.path.replace(/[\\/][^\\/]+$/, '') : '—'], ['Format', m.format],
      ...Object.entries(m.info || {}),
      ['Material', app.active?.material ? `${app.active.material.name} (${app.active.material.density} g/cm³)` : '<not specified>'],
      ['Bodies', st.bodies], ['Faces', st.faces], ['Edges', st.edges], ['Vertices', st.vertices], ['Triangles', (st.triangles || 0).toLocaleString()],
      ['Opened in', `${(st.load_s ?? 0).toFixed(2)} s${st.cached ? ' (cache)' : ''}`],
    ];
    body.append(h('table', { class: 'props-table' }, h('tbody', {}, ...rows.map(([k, v]) => h('tr', {}, h('td', { text: k }), h('td', { text: String(v ?? '—') }))))));
    if (m.warnings?.length) {
      body.append(h('div', { class: 'fx-section', text: 'Notes from the reader' }), ...m.warnings.map((w) => h('div', { class: 'hint', style: { padding: '2px 12px' }, text: `• ${w}` })));
    }
    if (m.path && app.native) body.append(h('div', { style: { padding: '10px 12px' } }, h('button', { class: 'btn', onclick: () => api.reveal(m.path) }, 'Show in Folder')));
  }
}

function iconFor(name) {
  const ext = name.split('.').pop().toLowerCase();
  if (['stl', 'obj', 'ply', 'off', '3mf', 'glb', 'gltf'].includes(ext)) return 'meshBody';
  if (MODEL_EXTS.includes(ext)) return 'part';
  return 'file';
}

function fmtSize(n) {
  if (n > 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  if (n > 1e3) return `${Math.round(n / 1e3)} KB`;
  return `${n} B`;
}

void toast;
