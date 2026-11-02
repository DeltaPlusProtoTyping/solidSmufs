// Space bar: SolidWorks' View Selector. A see-through cube appears around the model (click a face,
// edge or corner of it to look from there) together with the orientation menu.
import { menu, closeMenus, menuOpen } from './ui.js';

export class ViewSelector {
  constructor(app) {
    this.app = app;
    this.active = false;
    app.viewer.onSelectorPick = (dir) => { app.viewer.viewAlong(dir, true); this.close(); };
  }

  toggle() { if (this.active) this.close(); else this.open(); }

  open() {
    const app = this.app;
    if (!app.meta) return;
    this.active = true;
    app.viewer.setSelector(true);
    const r = app.viewer.canvas.getBoundingClientRect();
    menu(null, app.shell.viewsMenuItems(), { at: { x: r.left + 10, y: r.top + 44 } });
    const watch = setInterval(() => {
      if (!menuOpen() && this.active && !this._keep) { clearInterval(watch); this.close(); }
    }, 150);
    this._watch = watch;
  }

  close() {
    if (!this.active) return;
    this.active = false;
    clearInterval(this._watch);
    this.app.viewer.setSelector(false);
    closeMenus();
  }
}
