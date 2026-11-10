// The window furniture, SolidWorks-style: menu bar, quick access toolbar, CommandManager, heads-up
// view toolbar, document tabs, status bar unit systems, the S-key shortcut bar, the context toolbar
// that pops up by a selection, and command search.
import { api } from './api.js';
import { tool, icon } from './icons.js';
import { SYSTEMS } from './units.js';
import { h, menu, closeMenus, toast } from './ui.js';
import { STYLES, PRODUCT, escapeHtml } from './consts.js';

const TABS = [
  { id: 'view', label: 'View', items: ['open', 'reload', '|', 'zoomFit', 'zoomArea', 'prevView', '|', 'orientation', 'normalTo', 'sectionView', '|', 'displayStyle', 'hideShow', 'appearance', 'scene', 'perspective', '|', 'savePicture'] },
  { id: 'evaluate', label: 'Evaluate', items: ['measure', 'massProps', 'sectionProps', 'bbox', 'statistics', '|', 'draft', 'zebra', 'curvature', '|', 'material'] },
  { id: 'wagner', label: 'Tools', items: ['stock', 'holes', 'quote', '|', 'align', 'massProps', 'measure', '|', 'explorer'] },
];
const HUD = ['zoomFit', 'zoomArea', 'prevView', 'sectionView', '|', 'orientation', 'displayStyle', 'hideShow', 'appearance', 'scene', 'viewSettings'];
const QAT = ['open', 'reload', 'print', 'savePicture', '|', 'select', 'options'];
const SHORTCUTS = ['measure', 'massProps', 'sectionView', 'zoomFit', 'normalTo', 'orientation', 'displayStyle', 'hideShow', 'appearance', 'bbox', 'holes', 'stock'];
const MENUS = {
  File: (app) => [
    { label: 'Open…', icon: 'open', kb: 'Ctrl+O', action: () => app.run('open') },
    { label: 'Open Recent', icon: 'open', sub: () => (app.recent?.length ? app.recent.slice(0, 12).map((r) => ({ label: r.name, action: () => app.openPath(r.path) })) : [{ label: 'Nothing yet', disabled: true }]) },
    { sep: true },
    { label: 'Close', icon: 'close', kb: 'Ctrl+W', disabled: !app.active, action: () => app.run('close') },
    { label: 'Close All', disabled: !app.docs.length, action: () => app.run('closeAll') },
    { sep: true },
    { label: 'Save As STEP…', icon: 'file', disabled: !app.meta || app.meta.kind !== 'brep' || !app.native, action: () => app.run('saveStep') },
    { label: 'Print…', icon: 'print', kb: 'Ctrl+P', disabled: !app.active?.meta || !app.native, action: () => app.run('print') },
    { label: 'Save Picture…', icon: 'camera', disabled: !app.meta, action: () => app.run('savePicture') },
    { label: 'Copy Picture', icon: 'camera', kb: 'Ctrl+Shift+C', disabled: !app.meta, action: () => app.run('copyPicture') },
    { sep: true },
    { label: 'Show in Folder', disabled: !app.meta?.path || !app.native, action: () => api.reveal(app.meta.path) },
    { label: 'File Properties…', icon: 'props', disabled: !app.meta, action: () => app.run('fileProps') },
  ],
  Edit: (app) => [
    { label: 'Copy Measurement', kb: 'Ctrl+C', disabled: !app.quick, action: () => app.tools.copyMeasure() },
    { label: 'Clear Selection', kb: 'Esc', disabled: !app.sel.length, action: () => app.setSelection([]) },
    { sep: true },
    { label: 'Appearance…', icon: 'appearance', disabled: !app.meta, action: () => app.run('appearance') },
    { label: 'Material…', icon: 'material', disabled: !app.meta, action: () => app.run('material') },
  ],
  View: (app) => [
    { label: 'Display', icon: 'displayStyle', sub: () => [...app.styleItems(), { sep: true }, ...app.shell.viewSettingsItems()] },
    { label: 'Modify', icon: 'orientation', sub: () => [
      { label: 'Zoom to Fit', icon: 'zoomFit', kb: 'F', action: () => app.run('zoomFit') },
      { label: 'Zoom to Area', icon: 'zoomArea', action: () => app.run('zoomArea') },
      { label: 'Zoom to Selection', icon: 'zoomFit', action: () => app.run('zoomSel') },
      { label: 'Previous View', icon: 'prevView', kb: 'Ctrl+Shift+Z', action: () => app.run('prevView') },
      { sep: true },
      { label: 'Orientation…', icon: 'orientation', kb: 'Space', action: () => app.run('orientation') },
      { label: 'Normal To', icon: 'normalTo', kb: 'Ctrl+8', action: () => app.run('normalTo') },
    ] },
    { label: 'Hide/Show', icon: 'hideShow', sub: () => app.shell.hideShowItems() },
    { sep: true },
    { label: 'Section View', icon: 'sectionView', check: !!app.viewer.section, action: () => app.run('sectionView') },
    { label: 'Perspective', icon: 'perspective', kb: 'P', check: app.viewer.rig.perspective, action: () => app.run('perspective') },
    { sep: true },
    { label: 'FeatureManager Tree', kb: 'F9', check: !app.$('workspace').classList.contains('mgr-hidden'), action: () => app.run('fmToggle') },
    { label: 'Task Pane', check: app.taskpane.visible, action: () => app.run('taskPane') },
    { label: 'Dark Interface', check: app.prefs.theme === 'dark', action: () => app.run('theme') },
  ],
  Tools: (app) => [
    { head: 'Evaluate' },
    ...['measure', 'massProps', 'sectionProps', 'bbox', 'statistics'].map((id) => app.shell.menuItem(id)),
    { sep: true },
    ...['draft', 'zebra', 'curvature'].map((id) => app.shell.menuItem(id)),
    { head: 'Tools' },
    ...['stock', 'holes', 'quote', 'align'].map((id) => app.shell.menuItem(id)),
    { sep: true },
    app.shell.menuItem('options'),
  ],
  Window: (app) => [
    ...(app.docs.length ? app.docs.map((d, i) => ({ label: `${i + 1} ${d.name}`, check: d === app.active, action: () => app.activate(d) })) : [{ label: 'No documents open', disabled: true }]),
    { sep: true },
    { label: 'Next Document', kb: 'Ctrl+Tab', disabled: app.docs.length < 2, action: () => app.cycleDocs(1) },
    { label: 'Close All', disabled: !app.docs.length, action: () => app.run('closeAll') },
  ],
  Help: (app) => [
    { label: 'Mouse and Keyboard', icon: 'select', kb: 'F1', action: () => app.run('help') },
    { sep: true },
    { label: `About ${PRODUCT}`, action: () => app.run('about') },
  ],
};

export class Shell {
  constructor(app) {
    this.app = app;
    this.tab = 'view';
    this._buildTitle();
    this._buildHud();
    this._buildCubeButtons();
    this._buildStatus();
    this._buildBottomTabs();
    this._wireSearch();
  }

  get viewer() { return this.app.viewer; }

  // ------------------------------------------------------------------ title bar
  _buildTitle() {
    const app = this.app;
    const bar = document.getElementById('menubar');
    for (const name of Object.keys(MENUS)) {
      const b = h('button', { text: name });
      b.addEventListener('click', () => menu(b, MENUS[name](app)));
      b.addEventListener('mouseenter', () => { if (document.querySelector('.menubar button.open') && !b.classList.contains('open')) menu(b, MENUS[name](app), { force: true }); });
      bar.append(b);
    }
    const logo = document.getElementById('logo');
    logo.addEventListener('click', () => menu(logo, [
      { label: 'Open…', icon: 'open', kb: 'Ctrl+O', action: () => app.run('open') },
      { label: 'Options…', icon: 'options', action: () => app.run('options') },
      { sep: true },
      { label: 'wagner-machine.com', action: () => window.open('https://wagner-machine.com/', '_blank') },
      { label: `About ${PRODUCT}`, action: () => app.run('about') },
    ]));
    const qat = document.getElementById('qat');
    for (const id of QAT) {
      if (id === '|') { qat.append(h('span', { style: { width: '6px' } })); continue; }
      if (id === 'select') {
        qat.append(h('button', { class: 'tb-btn', title: 'Select (Esc)', html: icon('select') || '', onclick: () => { this.viewer.mode = 'select'; app.setSelection([]); this.refresh(); } }));
        continue;
      }
      const c = app.commands[id];
      const b = h('button', { class: 'tb-btn', title: `${c.label}${c.kb ? ` (${c.kb})` : ''}`, 'data-cmd': id, html: tool(c.icon) });
      b.addEventListener('click', () => app.run(id, b));
      qat.append(b);
    }
    qat.querySelectorAll('svg').forEach((s) => { s.style.width = '18px'; s.style.height = '18px'; });
    document.getElementById('btn-help').addEventListener('click', () => app.run('help'));
  }

  // ------------------------------------------------------------------ CommandManager
  selectTab(id, persist = true) {
    this.tab = TABS.some((t) => t.id === id) ? id : 'view';
    if (persist) this.app.save({ cmTab: this.tab });
    this.renderCommandManager();
  }

  renderCommandManager() {
    const app = this.app;
    const row = document.getElementById('cm-row');
    const tabs = document.getElementById('cm-tabs');
    const t = TABS.find((x) => x.id === this.tab);
    row.replaceChildren(...t.items.map((id) => (id === '|' ? h('div', { class: 'cm-sep' }) : this.cmButton(id))));
    tabs.replaceChildren(...TABS.map((x) => h('button', { class: `cm-tab${x.id === this.tab ? ' on' : ''}`, text: x.label, onclick: () => this.selectTab(x.id) })));
    void app;
  }

  cmButton(id) {
    const app = this.app;
    const c = app.commands[id];
    const b = h('button', {
      class: `cm-btn${c.menu ? ' drop' : ''}${c.toggle?.() ? ' on' : ''}`,
      title: `${c.label}${c.kb ? ` (${c.kb})` : ''}\n${c.tip || ''}`,
      disabled: c.needsDoc && !app.meta,
      'data-cmd': id,
    }, h('span', { class: 'ci', html: tool(c.icon) }), h('span', { class: 'cl', text: c.label }));
    b.addEventListener('click', (e) => {
      if (c.menu && (e.offsetY > b.offsetHeight - 16 || !c.run)) { menu(b, c.menu()); return; }
      if (c.menu && id !== 'displayStyle' && id !== 'hideShow') { menu(b, c.menu()); return; }
      app.run(id, b);
    });
    if (c.menu) b.addEventListener('contextmenu', (e) => { e.preventDefault(); menu(b, c.menu()); });
    return b;
  }

  bigButton(id, label) {
    const c = this.app.commands[id];
    return h('button', { class: 'btn', onclick: () => this.app.run(id) }, h('span', { html: tool(c.icon), style: { width: '18px', height: '18px', display: 'inline-flex' } }), label || c.label);
  }

  menuItem(id) {
    const c = this.app.commands[id];
    return { label: c.label, icon: c.icon, kb: c.kb, check: c.toggle ? c.toggle() : undefined, disabled: c.needsDoc && !this.app.meta, action: () => this.app.run(id) };
  }

  // ------------------------------------------------------------------ heads-up view toolbar
  _buildHud() {
    this.hud = document.getElementById('hud');
    this.renderHud();
  }

  renderHud() {
    const app = this.app;
    this.hud.replaceChildren(...HUD.map((id) => {
      if (id === '|') return h('div', { class: 'sep' });
      const c = app.commands[id];
      const iconName = id === 'displayStyle' ? (STYLES.find((s) => s.id === this.viewer.style)?.icon || c.icon) : c.icon;
      const b = h('button', { class: `hb${c.menu ? ' drop' : ''}${c.toggle?.() ? ' on' : ''}`, title: `${c.label}${c.kb ? ` (${c.kb})` : ''}`, html: `<span class="ci">${tool(iconName)}</span>` });
      b.addEventListener('click', () => (c.menu ? menu(b, c.menu(), { align: 'center' }) : app.run(id, b)));
      return b;
    }));
    this.hud.classList.toggle('disabled', !app.meta);
  }

  viewsMenuItems() {
    const app = this.app;
    const views = [['front', 'Front'], ['back', 'Back'], ['left', 'Left'], ['right', 'Right'], ['top', 'Top'], ['bottom', 'Bottom'], ['iso', 'Isometric'], ['trimetric', 'Trimetric']];
    const grid = h('div', { class: 'views-grid' }, ...views.map(([id, label]) => h('button', {
      title: `${label}${app.commands[id].kb ? ` (${app.commands[id].kb})` : ''}`,
      onclick: () => { closeMenus(); app.viewer.setView(id); },
    }, h('span', { class: 'ci', html: tool(id) }), h('span', { text: label }))));
    const saved = app.active?.savedViews || [];
    return [
      { el: grid },
      { sep: true },
      { label: 'Dimetric', icon: 'dimetric', action: () => app.viewer.setView('dimetric') },
      { label: 'Normal To', icon: 'normalTo', kb: 'Ctrl+8', action: () => app.run('normalTo') },
      { label: 'View Selector', icon: 'orientation', kb: 'Space', action: () => app.selector.open() },
      { sep: true },
      { label: 'New View…', icon: 'tpViews', action: () => this.saveView() },
      ...saved.map((s) => ({ label: s.name, icon: 'tpViews', action: () => app.viewer.rig.animateTo(s.state) })),
    ];
  }

  hideShowItems() {
    const app = this.app, v = this.viewer;
    const sel = app.selectedBodies();
    return [
      { label: 'Show All Bodies', icon: 'showAll', kb: 'Ctrl+Shift+H', action: () => app.showAll() },
      { label: 'Hide Selected', icon: 'hide', kb: 'Tab', disabled: !sel.length, action: () => app.hideBodies(sel) },
      { label: 'Isolate Selected', icon: 'isolate', disabled: !sel.length, action: () => app.isolate(sel) },
      { sep: true },
      { label: 'Planes', icon: 'plane', check: v.planesVisible, action: () => { v.setPlanesVisible(!v.planesVisible); app.manager.refresh(); } },
      { label: 'Origin', icon: 'origin', check: v.originVisible, action: () => { v.setOriginVisible(!v.originVisible); app.manager.refresh(); } },
      { label: 'Seam Edges', check: v.showSeams, action: () => v.setShowSeams(!v.showSeams) },
    ];
  }

  viewSettingsItems() {
    const app = this.app, v = this.viewer;
    return [
      { label: 'Perspective', icon: 'perspective', kb: 'P', check: v.rig.perspective, action: () => app.run('perspective') },
      { label: 'RealView Graphics', check: v.realView, action: () => app.run('realView') },
      { label: 'Silhouette Edges', check: v.showSilhouettes, action: () => { v.showSilhouettes = !v.showSilhouettes; v.setStyle(v.style); app.save({ silhouettes: v.showSilhouettes }); } },
      { label: 'View Cube', check: v.showCube, action: () => { v.showCube = !v.showCube; app.save({ viewCube: v.showCube }); v.requestRender(); this._syncCubeButtons(); } },
      { label: 'Highlight on Hover', check: app.prefs.hoverHighlight !== false, action: () => app.save({ hoverHighlight: app.prefs.hoverHighlight === false }) },
      { sep: true },
      { label: 'Options…', icon: 'options', action: () => app.tools.options('display') },
    ];
  }

  _buildCubeButtons() {
    const ui = document.getElementById('cube-ui');
    const v = () => this.viewer;
    const b = (ic, title, style, fn) => ui.append(h('button', { class: 'cbtn', title, html: icon(ic), style, onclick: fn }));
    b('triUp', 'Rotate up 90°', { left: '64px', top: '-4px' }, () => v().rotateView('screenX', -90));
    b('triDown', 'Rotate down 90°', { left: '64px', top: '134px' }, () => v().rotateView('screenX', 90));
    b('triLeft', 'Rotate left 90°', { left: '-2px', top: '64px' }, () => v().rotateView('screenY', -90));
    b('triRight', 'Rotate right 90°', { left: '130px', top: '64px' }, () => v().rotateView('screenY', 90));
    b('rotateLeft', 'Roll 90° counter-clockwise', { left: '0px', top: '0px' }, () => v().rotateView('view', 90));
    b('rotateRight', 'Roll 90° clockwise', { left: '128px', top: '0px' }, () => v().rotateView('view', -90));
    b('home', 'Isometric', { left: '0px', top: '128px' }, () => v().setView('iso'));
    this._syncCubeButtons();
  }

  _syncCubeButtons() { document.getElementById('cube-ui').hidden = !this.viewer.showCube; }

  // ------------------------------------------------------------------ document tabs and bottom tabs
  renderDocTabs() {
    const app = this.app;
    const el = document.getElementById('doc-tabs');
    if (app.docs.length < 2 && !(app.docs.length === 1 && app.docs[0].state !== 'ready')) { el.replaceChildren(); this._title(); return; }
    el.replaceChildren(...app.docs.map((d) => {
      const asm = d.meta && d.meta.bodies.some((b) => (b.path || []).length > 1);
      const t = h('div', { class: `doc-tab${d === app.active ? ' on' : ''}`, title: d.path || d.name },
        d.state === 'loading' ? h('span', { class: 'spin' }) : h('span', { class: 'dt-icon', html: tool(d.state === 'error' ? 'close' : asm ? 'assembly' : 'part') }),
        h('span', { class: 'dt-name', text: d.name }),
        h('span', { class: 'dt-x', title: 'Close', text: '×', onclick: (e) => { e.stopPropagation(); app.closeDoc(d); } }));
      t.addEventListener('click', () => app.activate(d));
      t.addEventListener('auxclick', (e) => { if (e.button === 1) app.closeDoc(d); });
      return t;
    }));
    this._title();
  }

  _title() {
    const app = this.app;
    const el = document.getElementById('doc-title');
    const d = app.active;
    el.innerHTML = d ? `${escapeHtml(d.name)}${d.meta ? ` <span class="dim">— ${escapeHtml(d.meta.format)}</span>` : ''}` : PRODUCT;
  }

  _buildBottomTabs() {
    this.bottom = 'model';
    this.renderBottomTabs();
  }

  renderBottomTabs() {
    const el = document.getElementById('bottom-tabs');
    el.replaceChildren(
      h('button', { class: this.bottom === 'model' ? 'on' : '', text: 'Model', onclick: () => { this.bottom = 'model'; this.renderBottomTabs(); } }),
      h('button', { class: this.bottom === 'views' ? 'on' : '', text: '3D Views', onclick: () => { this.bottom = this.bottom === 'views' ? 'model' : 'views'; this.renderBottomTabs(); } }));
    const vp = document.getElementById('viewport');
    vp.querySelector('.views-strip')?.remove();
    if (this.bottom === 'views') {
      const saved = this.app.active?.savedViews || [];
      const strip = h('div', { class: 'views-strip' },
        h('button', { class: 'btn', onclick: () => this.saveView() }, h('span', { html: tool('tpViews'), style: { width: '16px', height: '16px', display: 'inline-flex' } }), 'Save Current View'),
        ...saved.map((s, i) => h('div', { class: 'vs-item', title: 'Restore this view', onclick: () => this.viewer.rig.animateTo(s.state) },
          h('span', { text: s.name }),
          h('button', { class: 'icon-btn', title: 'Delete', html: icon('close'), onclick: (e) => { e.stopPropagation(); saved.splice(i, 1); this.renderBottomTabs(); } }))),
        saved.length ? null : h('span', { class: 'hint', text: 'Named views of this document live here.' }));
      vp.append(strip);
    }
  }

  saveView() {
    const app = this.app;
    if (!app.active?.meta) return;
    const name = prompt('Name for this view:', `View ${(app.active.savedViews.length || 0) + 1}`);
    if (!name) return;
    app.active.savedViews.push({ name, state: this.viewer.rig.state() });
    this.renderBottomTabs();
    toast(`Saved view "${name}"`);
  }

  // ------------------------------------------------------------------ status bar
  _buildStatus() {
    const app = this.app;
    document.getElementById('sb-product').innerHTML = `<img src="img/icon.svg" alt=""> ${PRODUCT} 2026`;
    const ub = document.getElementById('sb-units');
    ub.addEventListener('click', () => menu(ub, [
      { head: 'Unit system' },
      ...Object.entries(SYSTEMS).map(([k, s]) => ({ label: s.name, check: app.units.system === k, action: () => app.setSystem(k) })),
      { sep: true },
      { label: 'Edit Document Units…', icon: 'options', action: () => app.tools.options('units') },
    ], { align: 'right' }));
    document.getElementById('sb-tips').addEventListener('click', () => app.run('help'));
  }

  // ------------------------------------------------------------------ refresh
  refresh() {
    this.renderCommandManager();
    this.renderHud();
    this.renderDocTabs();
    this._syncCubeButtons();
    document.querySelectorAll('.qat .tb-btn[data-cmd]').forEach((b) => {
      const c = this.app.commands[b.dataset.cmd];
      b.disabled = c.needsDoc && !this.app.meta;
    });
    const vp = document.getElementById('viewport');
    vp.classList.toggle('cursor-measure', this.app.measuring);
  }

  toggleManager() {
    const ws = document.getElementById('workspace');
    ws.classList.toggle('mgr-hidden');
    setTimeout(() => this.viewer.resize(), 30);
  }

  menuAt(items, x, y) { menu(null, items, { at: { x, y } }); }

  // ------------------------------------------------------------------ S key: shortcut bar near the cursor
  shortcutBar() {
    const app = this.app;
    const pos = this.viewer.lastPointer || { x: this.viewer.width / 2, y: this.viewer.height / 2 };
    const r = this.viewer.canvas.getBoundingClientRect();
    const grid = h('div', { class: 'views-grid', style: { gridTemplateColumns: 'repeat(6, 54px)' } }, ...SHORTCUTS.map((id) => {
      const c = app.commands[id];
      return h('button', { title: `${c.label}${c.kb ? ` (${c.kb})` : ''}`, onclick: (e) => { closeMenus(); app.run(id, e.currentTarget); } },
        h('span', { class: 'ci', html: tool(c.icon) }), h('span', { text: c.label.split(' ')[0] }));
    }));
    menu(null, [{ el: grid }], { at: { x: r.left + pos.x - 160, y: r.top + pos.y - 30 } });
  }

  // ------------------------------------------------------------------ context toolbar beside a new selection
  selectionChanged(at) {
    const tb = document.getElementById('ctx-toolbar');
    const app = this.app;
    clearTimeout(this._ctxTimer);
    if (!at || !app.sel.length || app.measuring || app.prefs.contextToolbar === false) { tb.classList.remove('show'); return; }
    const ids = [];
    if (app.planarSelection()) ids.push('normalTo');
    ids.push('zoomSel');
    if (app.selectedBodies().length) ids.push('hideSel', 'isolate', 'appearance');
    ids.push('measure');
    tb.replaceChildren(...ids.map((id) => {
      const c = app.commands[id];
      return h('button', { class: 'hb', title: c.label, html: `<span class="ci">${tool(c.icon)}</span>`, onclick: () => { tb.classList.remove('show'); app.run(id); } });
    }));
    this._ctxAt = { x: at.x, y: at.y };
    tb.classList.add('show');
    tb.style.opacity = '1';
    this.placeContextToolbar();
    this._ctxTimer = setTimeout(() => { tb.style.opacity = '0'; setTimeout(() => tb.classList.remove('show'), 160); }, 3200);
    tb.onmouseenter = () => { clearTimeout(this._ctxTimer); tb.style.opacity = '1'; };
    tb.onmouseleave = () => { this._ctxTimer = setTimeout(() => tb.classList.remove('show'), 900); };
  }

  placeContextToolbar() {
    const tb = document.getElementById('ctx-toolbar');
    if (!tb.classList.contains('show') || !this._ctxAt) return;
    tb.style.left = `${Math.min(this._ctxAt.x + 14, this.viewer.width - tb.offsetWidth - 6)}px`;
    tb.style.top = `${Math.max(6, this._ctxAt.y - tb.offsetHeight - 14)}px`;
  }

  // ------------------------------------------------------------------ command search
  _wireSearch() {
    const app = this.app;
    const inp = document.getElementById('cmd-search');
    const show = () => {
      const q = inp.value.trim().toLowerCase();
      if (!q) { closeMenus(); return; }
      const hits = Object.values(app.commands)
        .filter((c) => c.label.toLowerCase().includes(q) || (c.tip || '').toLowerCase().includes(q))
        .slice(0, 12);
      const items = hits.length ? hits.map((c) => ({ label: c.label, icon: c.icon, kb: c.kb, disabled: c.needsDoc && !app.meta, action: () => { inp.value = ''; app.run(c.id); } }))
        : [{ label: 'No matching commands', disabled: true }];
      menu(inp.parentElement, items, { force: true, cls: 'cmd-results', align: 'right' });
    };
    inp.addEventListener('input', show);
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { inp.value = ''; closeMenus(); inp.blur(); }
      if (e.key === 'Enter') { document.querySelector('.cmd-results .mi:not([disabled])')?.click(); inp.blur(); }
    });
  }

  recentRow(r) {
    const app = this.app;
    const ext = r.name.split('.').pop().toLowerCase();
    return h('div', { class: 'wl-item', title: r.path, onclick: () => app.openPath(r.path) },
      h('span', { class: 'wi-icon', html: tool(['stl', 'obj', 'ply', 'off', '3mf', 'glb', 'gltf'].includes(ext) ? 'meshBody' : 'part') }),
      h('div', { class: 'wi-text' }, h('div', { class: 'wi-name', text: r.name }), h('div', { class: 'wi-path', text: r.path })),
      h('button', { class: 'icon-btn', title: 'Remove from list', html: icon('close'),
        onclick: async (e) => { e.stopPropagation(); app.recent = (await api.removeRecent(r.path)).recent; app.renderEmpty(); app.taskpane.refresh(); } }));
  }
}

