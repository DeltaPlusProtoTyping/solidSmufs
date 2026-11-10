// The view cube (top right) and the axis triad (bottom left), drawn into corners of the main canvas.
import * as THREE from 'three';

const LABELS = { px: 'RIGHT', nx: 'LEFT', py: 'TOP', ny: 'BOTTOM', pz: 'FRONT', nz: 'BACK' };

function faceTexture(text, theme) {
  const c = document.createElement('canvas');
  c.width = c.height = 256;
  const g = c.getContext('2d');
  const dark = theme === 'dark';
  const grad = g.createLinearGradient(0, 0, 0, 256);
  grad.addColorStop(0, dark ? '#3a4656' : '#fbfcfe');
  grad.addColorStop(1, dark ? '#2b3542' : '#e3e9f1');
  g.fillStyle = grad;
  g.fillRect(0, 0, 256, 256);
  g.strokeStyle = dark ? '#5b6b80' : '#aab6c6';
  g.lineWidth = 10;
  g.strokeRect(5, 5, 246, 246);
  g.fillStyle = dark ? '#e8eef6' : '#2a3442';
  g.font = '600 46px "Segoe UI Variable Text", "Segoe UI", sans-serif';
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.fillText(text, 128, 132);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

export class ViewCube {
  constructor(theme = 'dark') {
    this.size = 128; // CSS px
    this.margin = 14;
    this.scene = new THREE.Scene();
    this.camera = new THREE.OrthographicCamera(-1.75, 1.75, 1.75, -1.75, 0.1, 20);
    this.group = new THREE.Group();
    this.scene.add(this.group);
    this.scene.add(new THREE.AmbientLight(0xffffff, 2.2));
    const dl = new THREE.DirectionalLight(0xffffff, 1.2);
    dl.position.set(1, 2, 3);
    this.camera.add(dl);
    this.scene.add(this.camera);
    this.cube = new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2), []);
    this.group.add(this.cube);
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(this.cube.geometry),
      new THREE.LineBasicMaterial({ color: 0x8090a5, transparent: true, opacity: 0.7 }));
    this.cube.add(edges);
    this.edges = edges;
    this.hl = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1),
      new THREE.MeshBasicMaterial({ color: 0x4d8dff, transparent: true, opacity: 0.55, depthTest: true }));
    this.hl.visible = false;
    this.group.add(this.hl);
    this.hover = null;
    this.raycaster = new THREE.Raycaster();
    this.setTheme(theme);
    this.setUp('y');
    // triad
    this.triScene = new THREE.Scene();
    this.triCam = new THREE.OrthographicCamera(-1.6, 1.6, 1.6, -1.6, 0.1, 20);
    this.triScene.add(this.triCam);
    this.triad = new THREE.Group();
    this.triScene.add(this.triad);
    this.triSize = 84;
  }

  setTheme(theme) {
    this.theme = theme;
    const order = ['px', 'nx', 'py', 'ny', 'pz', 'nz'];
    this.cube.material.forEach?.((m) => m.map?.dispose());
    this.cube.material = order.map((k) => new THREE.MeshLambertMaterial({ map: faceTexture(LABELS[k], theme) }));
    this.edges.material.color.set(theme === 'dark' ? 0x7f8ea3 : 0x8a99ad);
    this.buildTriad?.();
  }

  // the cube is labelled for Y-up; for Z-up it is turned so TOP faces +Z and FRONT faces -Y
  setUp(axis) {
    this.upAxis = axis;
    this.group.rotation.set(axis === 'z' ? Math.PI / 2 : 0, 0, 0);
    this.group.updateMatrixWorld(true);
    if (this.triad) this.buildTriad();
  }

  buildTriad() {
    if (!this.triad) return;
    this.triad.clear();
    const colors = { x: 0xff5f57, y: 0x3fcf6e, z: 0x4d8dff };
    const dirs = { x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] };
    for (const k of ['x', 'y', 'z']) {
      const d = new THREE.Vector3(...dirs[k]);
      const mat = new THREE.MeshBasicMaterial({ color: colors[k] });
      const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.045, 0.95, 10), mat);
      shaft.position.copy(d.clone().multiplyScalar(0.475));
      shaft.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), d);
      const tip = new THREE.Mesh(new THREE.ConeGeometry(0.11, 0.28, 16), mat);
      tip.position.copy(d.clone().multiplyScalar(1.05));
      tip.quaternion.copy(shaft.quaternion);
      const c = document.createElement('canvas');
      c.width = c.height = 64;
      const g = c.getContext('2d');
      g.fillStyle = '#' + colors[k].toString(16).padStart(6, '0');
      g.font = '700 46px "Segoe UI", sans-serif';
      g.textAlign = 'center';
      g.textBaseline = 'middle';
      g.fillText(k.toUpperCase(), 32, 35);
      const tex = new THREE.CanvasTexture(c);
      tex.colorSpace = THREE.SRGBColorSpace;
      const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false }));
      spr.position.copy(d.clone().multiplyScalar(1.42));
      spr.scale.setScalar(0.5);
      spr.userData.axis = k;
      this.triad.add(shaft, tip, spr);
    }
    this.triad.add(new THREE.Mesh(new THREE.SphereGeometry(0.08, 12, 8), new THREE.MeshBasicMaterial({ color: 0x9aa6b5 })));
  }

  // CSS-pixel rectangle of the cube inside a viewport of width w
  rect(w) { return { x: w - this.size - this.margin, y: this.margin, w: this.size, h: this.size }; }
  triRect(h) { return { x: 10, y: h - this.triSize - 10, w: this.triSize, h: this.triSize }; }

  contains(x, y, w) {
    const r = this.rect(w);
    return x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h;
  }

  syncCamera(quat) {
    const d = new THREE.Vector3(0, 0, 1).applyQuaternion(quat);
    this.camera.position.copy(d.multiplyScalar(6));
    this.camera.quaternion.copy(quat);
    this.camera.updateMatrixWorld();
    this.triCam.position.copy(new THREE.Vector3(0, 0, 1).applyQuaternion(quat).multiplyScalar(6));
    this.triCam.quaternion.copy(quat);
    this.triCam.updateMatrixWorld();
  }

  render(renderer, w, h, quat, showCube = true, showTriad = true) {
    this.syncCamera(quat);
    const r = this.rect(w);
    renderer.setScissorTest(true);
    if (showCube) {
      renderer.setViewport(r.x, h - r.y - r.h, r.w, r.h);
      renderer.setScissor(r.x, h - r.y - r.h, r.w, r.h);
      renderer.clearDepth();
      renderer.render(this.scene, this.camera);
    }
    if (showTriad) {
      const t = this.triRect(h);
      renderer.setViewport(t.x, h - t.y - t.h, t.w, t.h);
      renderer.setScissor(t.x, h - t.y - t.h, t.w, t.h);
      renderer.clearDepth();
      renderer.render(this.triScene, this.triCam);
    }
    renderer.setScissorTest(false);
    renderer.setViewport(0, 0, w, h);
  }

  // which view region (a direction in world space) is under (x, y)? null if none
  pick(x, y, w) {
    const r = this.rect(w);
    const nx = ((x - r.x) / r.w) * 2 - 1, ny = -(((y - r.y) / r.h) * 2 - 1);
    this.raycaster.setFromCamera(new THREE.Vector2(nx, ny), this.camera);
    const hit = this.raycaster.intersectObject(this.cube, false)[0];
    if (!hit) return null;
    const local = this.cube.worldToLocal(hit.point.clone());
    const reg = [local.x, local.y, local.z].map((c) => (Math.abs(c) > 0.98 ? Math.sign(c) : Math.abs(c) > 0.6 ? Math.sign(c) : 0));
    const key = reg.join(',');
    const dirLocal = new THREE.Vector3(...reg).normalize();
    const dirWorld = dirLocal.clone().applyQuaternion(this.group.quaternion);
    return { key, reg, dir: dirWorld };
  }

  setHover(p) {
    const key = p ? p.key : null;
    if (key === this.hover) return false;
    this.hover = key;
    if (!p) { this.hl.visible = false; return true; }
    const s = new THREE.Vector3(), c = new THREE.Vector3();
    p.reg.forEach((v, i) => {
      s.setComponent(i, v ? 0.42 : 1.24);
      c.setComponent(i, v ? v * (1 - 0.21 + 0.03) : 0);
    });
    this.hl.scale.copy(s);
    this.hl.position.copy(c);
    this.hl.visible = true;
    return true;
  }

  pickTriad(x, y, h) {
    const t = this.triRect(h);
    if (x < t.x || x > t.x + t.w || y < t.y || y > t.y + t.h) return null;
    const nx = ((x - t.x) / t.w) * 2 - 1, ny = -(((y - t.y) / t.h) * 2 - 1);
    this.raycaster.setFromCamera(new THREE.Vector2(nx, ny), this.triCam);
    const hit = this.raycaster.intersectObjects(this.triad.children.filter((o) => o.isSprite), false)[0];
    return hit ? hit.object.userData.axis : null;
  }
}
