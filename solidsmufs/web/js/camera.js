// Camera rig with SolidWorks-style navigation: orthographic by default (perspective optional),
// free rotation about the point under the cursor, zoom toward the cursor, animated view changes.
import * as THREE from 'three';

const V = () => new THREE.Vector3();
const ease = (t) => 1 - Math.pow(1 - t, 3);

export class CameraRig {
  constructor() {
    this.persp = new THREE.PerspectiveCamera(32, 1, 0.1, 1e7);
    this.ortho = new THREE.OrthographicCamera(-1, 1, 1, -1, -1e7, 1e7);
    this.perspective = false;
    this.target = V();
    this.quat = new THREE.Quaternion();
    this.height = 100; // world units visible top-to-bottom through the target
    this.aspect = 1;
    this.radius = 100; // model size, for clip planes and limits
    this.center = V();
    this.anim = null;
    this.history = [];
    this.turntable = false;
    this.up = new THREE.Vector3(0, 1, 0);
    this.onChange = () => {};
    this.update();
  }

  get camera() { return this.perspective ? this.persp : this.ortho; }

  setSize(w, h) {
    this.aspect = w / Math.max(h, 1);
    this.update();
  }

  setScene(center, radius) {
    this.center.copy(center);
    this.radius = Math.max(radius, 1e-6);
  }

  distance() {
    return (this.height / 2) / Math.tan(THREE.MathUtils.degToRad(this.persp.fov / 2));
  }

  dir() { return new THREE.Vector3(0, 0, 1).applyQuaternion(this.quat); } // from target toward the eye
  upVec() { return new THREE.Vector3(0, 1, 0).applyQuaternion(this.quat); }
  rightVec() { return new THREE.Vector3(1, 0, 0).applyQuaternion(this.quat); }

  update() {
    const d = this.dir();
    const back = Math.max(this.radius * 6, this.height * 2);
    // orthographic: eye far back, wide clip range around the model
    this.ortho.position.copy(this.target).addScaledVector(d, back);
    this.ortho.quaternion.copy(this.quat);
    const hh = this.height / 2, hw = hh * this.aspect;
    this.ortho.left = -hw; this.ortho.right = hw; this.ortho.top = hh; this.ortho.bottom = -hh;
    const toCenter = this.ortho.position.distanceTo(this.center);
    this.ortho.near = Math.max(toCenter - this.radius * 3, -this.radius * 4);
    this.ortho.far = toCenter + this.radius * 3;
    this.ortho.updateProjectionMatrix();
    this.ortho.updateMatrixWorld();
    // perspective: eye at the distance that shows `height` at the target
    const dist = this.distance();
    this.persp.position.copy(this.target).addScaledVector(d, dist);
    this.persp.quaternion.copy(this.quat);
    this.persp.aspect = this.aspect;
    const pc = this.persp.position.distanceTo(this.center);
    this.persp.near = Math.max(pc - this.radius * 3, dist * 0.002, this.radius * 1e-4);
    this.persp.far = pc + this.radius * 3;
    this.persp.updateProjectionMatrix();
    this.persp.updateMatrixWorld();
  }

  changed() { this.update(); this.onChange(); }

  // world units per screen pixel at the target depth
  unitsPerPixel(viewH) { return this.height / Math.max(viewH, 1); }

  // ------------------------------------------------------------------ navigation
  rotate(dx, dy, pivot) {
    const k = 0.0075;
    let q;
    if (this.turntable) {
      const qa = new THREE.Quaternion().setFromAxisAngle(this.up, -dx * k);
      const qb = new THREE.Quaternion().setFromAxisAngle(this.rightVec(), -dy * k);
      q = qa.multiply(qb);
    } else {
      const qa = new THREE.Quaternion().setFromAxisAngle(this.upVec(), -dx * k);
      const qb = new THREE.Quaternion().setFromAxisAngle(this.rightVec(), -dy * k);
      q = qa.multiply(qb);
    }
    this.applyRotation(q, pivot);
  }

  // SolidWorks: after middle-clicking a straight edge, dragging turns the view about that edge
  rotateAbout(axis, point, dx, dy) {
    const q = new THREE.Quaternion().setFromAxisAngle(axis, (-dx - dy) * 0.0075);
    this.applyRotation(q, point);
  }

  applyRotation(q, pivot) {
    pivot = pivot || this.target;
    this.quat.premultiply(q).normalize();
    this.target.sub(pivot).applyQuaternion(q).add(pivot);
    this.changed();
  }

  roll(angle) {
    const q = new THREE.Quaternion().setFromAxisAngle(this.dir(), angle);
    this.quat.premultiply(q).normalize();
    this.changed();
  }

  pan(dx, dy, viewH) {
    const upp = this.unitsPerPixel(viewH);
    this.target.addScaledVector(this.rightVec(), -dx * upp).addScaledVector(this.upVec(), dy * upp);
    this.changed();
  }

  // factor < 1 zooms in; (nx, ny) cursor in NDC keeps the point under it fixed
  zoomAt(factor, nx = 0, ny = 0) {
    const minH = this.radius * 1e-5, maxH = this.radius * 400;
    const newH = THREE.MathUtils.clamp(this.height * factor, minH, maxH);
    const f = newH / this.height;
    const hh = this.height / 2, hw = hh * this.aspect;
    const p = this.target.clone().addScaledVector(this.rightVec(), nx * hw).addScaledVector(this.upVec(), ny * hh);
    this.target.sub(p).multiplyScalar(f).add(p);
    this.height = newH;
    this.changed();
  }

  // ------------------------------------------------------------------ views
  state() { return { quat: this.quat.clone(), target: this.target.clone(), height: this.height }; }

  pushHistory() {
    this.history.push(this.state());
    if (this.history.length > 40) this.history.shift();
  }

  previous() {
    const s = this.history.pop();
    if (s) this.animateTo(s, 380, false);
  }

  // look along -dir (eye placed on the +dir side), with `up` as screen-up
  orient(dir, up) {
    const z = dir.clone().normalize();
    let y = up.clone().sub(z.clone().multiplyScalar(up.dot(z)));
    if (y.lengthSq() < 1e-10) y = Math.abs(z.y) < 0.9 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(0, 0, -1);
    y.normalize();
    const x = new THREE.Vector3().crossVectors(y, z);
    const m = new THREE.Matrix4().makeBasis(x, y, z);
    return new THREE.Quaternion().setFromRotationMatrix(m);
  }

  fitState(box, quat = this.quat) {
    if (!box || box.isEmpty()) return null;
    const center = box.getCenter(V());
    // project the box corners on the view axes for a snug fit
    const right = new THREE.Vector3(1, 0, 0).applyQuaternion(quat);
    const up = new THREE.Vector3(0, 1, 0).applyQuaternion(quat);
    let w = 0, h = 0;
    for (let i = 0; i < 8; i++) {
      const c = new THREE.Vector3(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z).sub(center);
      w = Math.max(w, Math.abs(c.dot(right)));
      h = Math.max(h, Math.abs(c.dot(up)));
    }
    const height = Math.max(h * 2, (w * 2) / this.aspect) * 1.18 || this.radius;
    return { quat: quat.clone(), target: center, height };
  }

  fit(box, animate = true, quat) {
    const s = this.fitState(box, quat || this.quat);
    if (!s) return;
    if (animate) this.animateTo(s, 420);
    else { this.quat.copy(s.quat); this.target.copy(s.target); this.height = s.height; this.changed(); }
  }

  animateTo(s, ms = 450, remember = true) {
    if (remember) this.pushHistory();
    this.anim = {
      t0: performance.now(), ms,
      from: this.state(),
      to: { quat: s.quat ? s.quat.clone() : this.quat.clone(), target: s.target ? s.target.clone() : this.target.clone(), height: s.height ?? this.height },
    };
  }

  // advance an animation; true while still moving
  tick(now) {
    if (!this.anim) return false;
    const a = this.anim;
    const t = Math.min(1, (now - a.t0) / a.ms);
    const k = ease(t);
    this.quat.slerpQuaternions(a.from.quat, a.to.quat, k);
    this.target.lerpVectors(a.from.target, a.to.target, k);
    this.height = Math.exp(THREE.MathUtils.lerp(Math.log(a.from.height), Math.log(a.to.height), k));
    this.changed();
    if (t >= 1) this.anim = null;
    return true;
  }
}

// Standard view directions for the two common "up" conventions. dir = from the model toward the eye.
export function standardViews(upAxis = 'y') {
  const v = (x, y, z) => new THREE.Vector3(x, y, z);
  if (upAxis === 'z') {
    return {
      front: { dir: v(0, -1, 0), up: v(0, 0, 1) },
      back: { dir: v(0, 1, 0), up: v(0, 0, 1) },
      left: { dir: v(-1, 0, 0), up: v(0, 0, 1) },
      right: { dir: v(1, 0, 0), up: v(0, 0, 1) },
      top: { dir: v(0, 0, 1), up: v(0, 1, 0) },
      bottom: { dir: v(0, 0, -1), up: v(0, -1, 0) },
      iso: { dir: v(1, -1, 1), up: v(0, 0, 1) },
      dimetric: { dir: v(0.92, -0.92, 0.55), up: v(0, 0, 1) },
      trimetric: { dir: v(1, -0.6, 0.75), up: v(0, 0, 1) },
    };
  }
  return {
    front: { dir: v(0, 0, 1), up: v(0, 1, 0) },
    back: { dir: v(0, 0, -1), up: v(0, 1, 0) },
    left: { dir: v(-1, 0, 0), up: v(0, 1, 0) },
    right: { dir: v(1, 0, 0), up: v(0, 1, 0) },
    top: { dir: v(0, 1, 0), up: v(0, 0, -1) },
    bottom: { dir: v(0, -1, 0), up: v(0, 0, 1) },
    iso: { dir: v(1, 1, 1), up: v(0, 1, 0) },
    dimetric: { dir: v(0.92, 0.55, 0.92), up: v(0, 1, 0) },
    trimetric: { dir: v(0.75, 0.6, 1), up: v(0, 1, 0) },
  };
}
