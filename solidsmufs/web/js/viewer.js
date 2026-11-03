// The graphics area: draws the model, picks faces / edges / vertices under the cursor (GPU id pass),
// display styles, highlights, planes and origin, section view with caps, analysis shading (draft,
// zebra, curvature), the View Selector cube, measurement graphics and SolidWorks-style mouse input.
import * as THREE from 'three';
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { CameraRig, standardViews } from './camera.js';
import { ViewCube } from './viewcube.js';
import { tool } from './icons.js';

const DEFAULT_COLOR = [0.79, 0.81, 0.84];
const PLAIN_FINISH = { metal: 0.22, rough: 0.48 }; // bodies the file says nothing about, and RealView off
const METAL_REFLECTIONS = 1.6; // metals are mostly reflection: a brighter environment than plastics (0.5) so they read as metal
const PRE = new THREE.Color(0xff8a00); // SolidWorks dynamic highlight
const SEL = new THREE.Color(0x1f6fff); // selected items
const PLANES = [
  { name: 'Front Plane', n: [0, 0, 1], u: [1, 0, 0], v: [0, 1, 0] },
  { name: 'Top Plane', n: [0, 1, 0], u: [1, 0, 0], v: [0, 0, -1] },
  { name: 'Right Plane', n: [1, 0, 0], u: [0, 0, -1], v: [0, 1, 0] },
];
const GESTURES = [
  { dir: 'up', ang: -90, cmd: 'top', label: 'Top', icon: 'top' },
  { dir: 'upright', ang: -45, cmd: 'normalTo', label: 'Normal To', icon: 'normalTo' },
  { dir: 'right', ang: 0, cmd: 'right', label: 'Right', icon: 'right' },
  { dir: 'downright', ang: 45, cmd: 'back', label: 'Back', icon: 'back' },
  { dir: 'down', ang: 90, cmd: 'bottom', label: 'Bottom', icon: 'bottom' },
  { dir: 'downleft', ang: 135, cmd: 'front', label: 'Front', icon: 'front' },
  { dir: 'left', ang: 180, cmd: 'left', label: 'Left', icon: 'left' },
  { dir: 'upleft', ang: -135, cmd: 'iso', label: 'Isometric', icon: 'iso' },
];

function idColor(id) { return [(id & 255) / 255, ((id >> 8) & 255) / 255, ((id >> 16) & 255) / 255]; }

const FACE_PICK_VS = /* glsl */`
  attribute float faceId;
  varying float vId;
  #include <common>
  #include <clipping_planes_pars_vertex>
  void main() {
    vId = faceId;
    #include <begin_vertex>
    #include <project_vertex>
    #include <clipping_planes_vertex>
  }`;
const FACE_PICK_FS = /* glsl */`
  varying float vId;
  #include <common>
  #include <clipping_planes_pars_fragment>
  void main() {
    #include <clipping_planes_fragment>
    float id = floor(vId + 1.5);
    gl_FragColor = vec4(mod(id, 256.0) / 255.0, mod(floor(id / 256.0), 256.0) / 255.0, floor(id / 65536.0) / 255.0, 1.0);
  }`;

const DOT_VS = /* glsl */`
  attribute vec3 center;
  attribute vec3 dotColor;
  uniform vec2 resolution;
  uniform float size;
  uniform float bias;
  varying vec2 vUv;
  varying vec3 vColor;
  #include <common>
  #include <clipping_planes_pars_vertex>
  void main() {
    vUv = position.xy;
    vColor = dotColor;
    vec4 mvPosition = modelViewMatrix * vec4(center, 1.0);
    vec4 clip = projectionMatrix * mvPosition;
    clip.xy += position.xy * size / resolution * clip.w;
    clip.z -= bias * clip.w;
    gl_Position = clip;
    #include <clipping_planes_vertex>
  }`;
const DOT_FS = /* glsl */`
  uniform vec3 color;
  uniform float useVertexColor;
  uniform float ring;
  varying vec2 vUv;
  varying vec3 vColor;
  #include <common>
  #include <clipping_planes_pars_fragment>
  void main() {
    #include <clipping_planes_fragment>
    float r = length(vUv);
    if (r > 1.0) discard;
    vec3 c = mix(color, vColor, useVertexColor);
    if (ring > 0.5 && r < 0.55) c = vec3(1.0);
    gl_FragColor = vec4(c, 1.0);
  }`;

// analysis shading (draft / zebra / curvature); shared vertex shader
const ANALYSIS_VS = /* glsl */`
  varying vec3 vNormal;
  varying vec3 vViewNormal;
  varying vec3 vPos;
  varying vec3 vViewPos;
  #include <common>
  #include <clipping_planes_pars_vertex>
  void main() {
    vNormal = normal;
    vViewNormal = normalize(normalMatrix * normal);
    vPos = position;
    #include <begin_vertex>
    #include <project_vertex>
    vViewPos = mvPosition.xyz;
    #include <clipping_planes_vertex>
  }`;
const ANALYSIS_FS = /* glsl */`
  uniform int mode;          // 0 draft, 1 zebra, 2 curvature
  uniform vec3 pullDir;
  uniform float sinAngle;
  uniform float stripes;
  uniform float stripeWidth;
  uniform float curvScale;
  varying vec3 vNormal;
  varying vec3 vViewNormal;
  varying vec3 vPos;
  varying vec3 vViewPos;
  #include <common>
  #include <clipping_planes_pars_fragment>
  vec3 ramp(float t) {
    t = clamp(t, 0.0, 1.0);
    vec3 a = vec3(0.17, 0.39, 0.84), b = vec3(0.23, 0.66, 0.34), c = vec3(0.95, 0.76, 0.23), d = vec3(0.85, 0.28, 0.25);
    if (t < 0.33) return mix(a, b, t / 0.33);
    if (t < 0.66) return mix(b, c, (t - 0.33) / 0.33);
    return mix(c, d, (t - 0.66) / 0.34);
  }
  void main() {
    #include <clipping_planes_fragment>
    vec3 n = normalize(vNormal);
    vec3 vn = normalize(vViewNormal);
    if (!gl_FrontFacing) { n = -n; vn = -vn; }
    float light = 0.45 + 0.55 * abs(vn.z);
    vec3 col;
    if (mode == 0) {
      float d = dot(n, normalize(pullDir));
      col = d > sinAngle ? vec3(0.23, 0.66, 0.34) : (d < -sinAngle ? vec3(0.85, 0.28, 0.25) : vec3(0.95, 0.76, 0.23));
      col *= light;
    } else if (mode == 1) {
      vec3 v = normalize(-vViewPos);
      vec3 r = reflect(-v, vn);
      float t = fract((r.y * 0.5 + 0.5) * stripes);
      col = vec3(step(stripeWidth, t)) * (0.85 + 0.15 * light);
    } else {
      vec3 dn = fwidth(n);
      vec3 dp = fwidth(vPos);
      float k = length(dn) / max(length(dp), 1e-9);
      col = ramp(log(1.0 + k * curvScale) / log(1.0 + 40.0)) * light;
    }
    gl_FragColor = vec4(col, 1.0);
    #include <colorspace_fragment>
  }`;

function dotMaterial(opts = {}) {
  return new THREE.ShaderMaterial({
    vertexShader: DOT_VS, fragmentShader: DOT_FS, clipping: true,
    uniforms: {
      resolution: { value: new THREE.Vector2(1, 1) }, size: { value: opts.size ?? 9 }, bias: { value: opts.bias ?? 0.0002 },
      color: { value: new THREE.Color(opts.color ?? 0xffffff) }, useVertexColor: { value: opts.vertexColor ? 1 : 0 },
      ring: { value: opts.ring ? 1 : 0 },
    },
    depthTest: opts.depthTest ?? true, depthWrite: false, transparent: false, toneMapped: false,
  });
}

function dotGeometry(points, colors) {
  const g = new THREE.InstancedBufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0], 3));
  g.setIndex([0, 1, 2, 0, 2, 3]);
  g.setAttribute('center', new THREE.InstancedBufferAttribute(new Float32Array(points), 3));
  g.setAttribute('dotColor', new THREE.InstancedBufferAttribute(new Float32Array(colors || points.length), 3));
  g.instanceCount = points.length / 3;
  return g;
}

export class Viewer {
  constructor(container) {
    this.container = container;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, stencil: true, alpha: false, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.localClippingEnabled = true;
    this.renderer.autoClear = false;
    this.renderer.toneMapping = THREE.NeutralToneMapping;
    this.canvas = this.renderer.domElement;
    this.canvas.tabIndex = 0;
    container.prepend(this.canvas);
    // the first WebGL frame is slow (a few hundred ms); when a part is on its way at startup, make
    // its frame the first one instead of an empty scene's. Hidden until then (an undrawn canvas is black).
    this.canvas.style.visibility = 'hidden';
    this.holdUntil = performance.now() + 2000;

    this.rig = new CameraRig();
    this.rig.onChange = () => { this.viewChanged = true; this.requestRender(); };
    this.cube = new ViewCube('light');

    this.scene = new THREE.Scene();
    this.modelGroup = new THREE.Group();
    this.edgeGroup = new THREE.Group();
    this.silGroup = new THREE.Group();
    this.capGroup = new THREE.Group();
    this.refGroup = new THREE.Group(); // planes, origin
    this.boxGroup = new THREE.Group();
    this.selGroup = new THREE.Group(); // view selector cube
    this.overlay = new THREE.Group();
    this.annot = new THREE.Group();
    this.preview = new THREE.Group(); // Align Part's axis triad (kept apart from measurement annotations)
    this.scene.add(this.modelGroup, this.edgeGroup, this.silGroup, this.capGroup, this.refGroup, this.boxGroup, this.selGroup, this.overlay, this.annot, this.preview);

    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    this.scene.environmentIntensity = 0.5;
    this.lightRig = new THREE.Group();
    const head = new THREE.DirectionalLight(0xffffff, 1.6);
    head.position.set(-0.35, 0.6, 1);
    const fill = new THREE.DirectionalLight(0xffffff, 0.35);
    fill.position.set(0.6, -0.4, 0.4);
    this.lightRig.add(head, head.target, fill, fill.target);
    this.scene.add(this.lightRig);

    this.bgScene = new THREE.Scene();
    this.bgCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    this.bgMat = new THREE.ShaderMaterial({
      uniforms: { top: { value: new THREE.Color() }, bottom: { value: new THREE.Color() } },
      vertexShader: 'varying vec2 vUv;\nvoid main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }',
      fragmentShader: 'uniform vec3 top;\nuniform vec3 bottom;\nvarying vec2 vUv;\nvoid main() {\n  gl_FragColor = vec4(mix(bottom, top, smoothstep(0.0, 1.0, vUv.y)), 1.0);\n  #include <colorspace_fragment>\n}',
      depthTest: false, depthWrite: false,
    });
    this.bgScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.bgMat));

    this.pickScene = new THREE.Scene();
    const rt = () => new THREE.WebGLRenderTarget(1, 1, { type: THREE.UnsignedByteType, depthBuffer: true, stencilBuffer: false });
    this.pickTarget = rt();
    this.hoverTarget = rt();
    this.pickBuf = new Uint8Array(4);
    this.hoverBuf = new Uint8Array(4);
    this.faceIdMat = new THREE.ShaderMaterial({ vertexShader: FACE_PICK_VS, fragmentShader: FACE_PICK_FS, clipping: true, side: THREE.DoubleSide,
      polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 2, toneMapped: false });
    this.analysisMat = new THREE.ShaderMaterial({
      vertexShader: ANALYSIS_VS, fragmentShader: ANALYSIS_FS, clipping: true, side: THREE.DoubleSide,
      polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1, toneMapped: false,
      uniforms: { mode: { value: 0 }, pullDir: { value: new THREE.Vector3(0, 1, 0) }, sinAngle: { value: 0.017 }, stripes: { value: 14 }, stripeWidth: { value: 0.5 }, curvScale: { value: 1 } },
    });

    this.clipPlanes = [];
    this.style = 'shadedEdges';
    this.showSeams = false;
    this.realView = true;
    this.showSilhouettes = true;
    this.showCube = false;
    this.upAxis = 'y';
    this.theme = 'light';
    this.darkScene = false;
    this.planeVis = [false, false, false];
    this.planesVisible = false;
    this.originVisible = false;
    this.labels = [];
    this.labelLayer = container.querySelector('#labels');
    this.model = null;
    this.bodies = [];
    this.hover = null;
    this.selection = [];
    this.mode = 'select';
    this.mouseMode = 'sw';
    this.wheelReverse = false;
    this.analysis = null;
    this.bboxShown = false;
    this.selectorOn = false;
    this.needsRender = true;
    this.viewChanged = true;
    this.onHover = () => {};
    this.onClick = () => {};
    this.onContext = () => {};
    this.onViewChange = () => {};
    this.onBoxSelect = () => {};
    this.onGesture = () => {};
    this.onSelectorPick = () => {};

    this.resize();
    new ResizeObserver(() => this.resize()).observe(container);
    this.setBackgroundColors(['#fbfcfd', '#c3cbd6'], false);
    this._bindInput();
    this._loop = this._loop.bind(this);
    requestAnimationFrame(this._loop);
  }

  // ================================================================== frame
  requestRender() { this.needsRender = true; }

  resize() {
    const r = this.container.getBoundingClientRect();
    this.width = Math.max(1, Math.floor(r.width));
    this.height = Math.max(1, Math.floor(r.height));
    this.renderer.setSize(this.width, this.height, false);
    this.rig.setSize(this.width, this.height);
    this.scene.traverse((o) => {
      if (o.material?.isLineMaterial) o.material.resolution.set(this.width, this.height);
      if (o.material?.uniforms?.resolution && o.material.uniforms.size) o.material.uniforms.resolution.value.set(this.width, this.height);
    });
    this.viewChanged = true;
    this.requestRender();
  }

  _loop(now) {
    requestAnimationFrame(this._loop);
    if (this._spaceStep(now)) this.needsRender = true;
    if (this.rig.tick(now)) this.needsRender = true;
    if (!this.needsRender) return;
    if (!this.model && performance.now() < this.holdUntil) return;
    this.needsRender = false;
    this.render();
    if (this.canvas.style.visibility) {
      this.canvas.style.visibility = '';
      console.info(`[timing] first frame drawn (${this.model ? 'with the part' : 'empty'})`);
    }
  }

  // SpaceMouse: the app hands over the cap's latest [tx, ty, tz, rx, ry, rz] (about ±350 each); the view
  // moves by them every frame, scaled by the frame's time, the way 3Dconnexion's object mode works: slide
  // to pan, push / pull to zoom, tilt, twist and roll to turn about the model's centre (as SolidWorks)
  spaceNav(v) {
    this.space = v;
    this.spaceAt = performance.now();
  }

  _spaceStep(now) {
    const v = this.space;
    if (!v || !this.model) { this._spaceLast = now; return false; }
    const DEAD = 10, FULL = 350;
    const a = v.map((x) => (Math.abs(x) < DEAD ? 0 : (x - Math.sign(x) * DEAD) / (FULL - DEAD)));
    const dt = Math.min((now - (this._spaceLast ?? now)) / 1000, 0.05);
    this._spaceLast = now;
    if (now - this.spaceAt > 400 || a.every((x) => x === 0)) { this.spacePivot = null; return false; }  // let go, or gone quiet
    if (!dt) return false;
    const [tx, ty, tz, rx, ry, rz] = a, rig = this.rig;
    this.rig.anim = null;
    if (!this.spacePivot) this.spacePivot = this.rotCenter?.point || this.visibleBox().getCenter(new THREE.Vector3());
    const PAN = 1.2 * this.height, ZOOM = 1.6, TURN = Math.PI / 0.0075;  // per second at full deflection
    if (tx || tz) rig.pan(tx * PAN * dt, -tz * PAN * dt, this.height);
    if (ty) rig.zoomAt(Math.exp(ty * ZOOM * dt), 0, 0);
    if (rx || rz) rig.rotate(rz * TURN * dt, rx * TURN * dt, this.spacePivot);
    if (ry) rig.roll(-ry * Math.PI * dt);
    this.viewChanged = true;
    return true;
  }

  /** Nothing is coming to wait for: draw the empty scene. */
  release() {
    this.holdUntil = 0;
    this.requestRender();
  }

  render() {
    const r = this.renderer;
    if (this.viewChanged) {
      this.viewChanged = false;
      this._silhouettesSoon();
      this.onViewChange();
    }
    const cam = this.rig.camera;
    this.lightRig.position.copy(cam.position);
    this.lightRig.quaternion.copy(cam.quaternion);
    this.lightRig.updateMatrixWorld(true);
    r.setViewport(0, 0, this.width, this.height);
    r.clear(true, true, true);
    r.render(this.bgScene, this.bgCam);
    r.clearDepth();
    r.render(this.scene, cam);
    this.cube.render(r, this.width, this.height, this.rig.quat, this.showCube);
    this._placeLabels();
  }

  // ================================================================== look
  setTheme(theme) { this.theme = theme; this.cube.setTheme(theme === 'dark' ? 'dark' : 'light'); this._applyStyle(); this.requestRender(); }

  setBackgroundColors([top, bottom], dark) {
    this.bgMat.uniforms.top.value.set(top);
    this.bgMat.uniforms.bottom.value.set(bottom);
    this.container.style.background = bottom;
    this.darkScene = !!dark;
    this._applyStyle();
    this.requestRender();
  }

  setUpAxis(axis) {
    this.upAxis = axis === 'z' ? 'z' : 'y';
    this.rig.up.set(0, this.upAxis === 'y' ? 1 : 0, this.upAxis === 'z' ? 1 : 0);
    this.cube.setUp(this.upAxis);
    this.requestRender();
  }

  // ================================================================== model
  clear() {
    for (const g of [this.modelGroup, this.edgeGroup, this.capGroup, this.overlay, this.annot, this.silGroup, this.pickScene, this.refGroup, this.boxGroup, this.selGroup]) {
      g.traverse((o) => { if (o.geometry && !o.userData.sharedGeo) o.geometry.dispose(); });
      g.clear();
    }
    this.model = null;
    this.bodies = [];
    this.hover = null;
    this.selection = [];
    this.rotCenter = null;
    this.silData = null;
    this.silLines = null;
    this.analysis = null;
    this.bboxShown = false;
    this.planeVis = [false, false, false];
    this.planesVisible = false;
    this.originVisible = false;
    this.clearLabels();
    this.requestRender();
  }

  setModel(meta, blob) {
    this.clear();
    this.resize();
    const buf = (key, T) => { const b = meta.buffers[key]; return new T(blob, b.offset, b.length); };
    const pos = buf('positions', Float32Array), nrm = buf('normals', Float32Array);
    const idx = buf('indices', Uint32Array), segs = buf('segments', Float32Array), verts = buf('vertices', Float32Array);
    const F = meta.faces, E = meta.edges;
    const nF = F.type.length, nE = E.type.length, nV = verts.length / 3;
    this.model = { meta, pos, nrm, idx, segs, verts, nF, nE, nV, faceBody: F.body };

    const edgeBody = new Int32Array(nE);
    for (let e = 0; e < nE; e++) edgeBody[e] = E.faces[e].length ? F.body[E.faces[e][0]] : 0;
    this.model.edgeBody = edgeBody;
    const vertBody = new Int32Array(nV);
    {
      const key = (x, y, z) => `${Math.round(x * 1e4)},${Math.round(y * 1e4)},${Math.round(z * 1e4)}`;
      const map = new Map();
      for (let v = 0; v < nV; v++) map.set(key(verts[v * 3], verts[v * 3 + 1], verts[v * 3 + 2]), v);
      for (let e = 0; e < nE; e++) {
        const s0 = E.sstart[e], sn = E.scount[e];
        for (const k of [s0 * 6, (s0 + sn - 1) * 6 + 3]) {
          const v = map.get(key(segs[k], segs[k + 1], segs[k + 2]));
          if (v !== undefined) vertBody[v] = edgeBody[e];
        }
      }
    }
    this.model.vertBody = vertBody;

    const [x0, y0, z0, x1, y1, z1] = meta.bbox;
    const box = new THREE.Box3(new THREE.Vector3(x0, y0, z0), new THREE.Vector3(x1, y1, z1));
    this.model.box = box;
    this.rig.setScene(box.getCenter(new THREE.Vector3()), Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1e-6));

    meta.bodies.forEach((b, bi) => {
      const [f0, fn] = b.faces;
      if (!fn) { this.bodies.push(null); return; }
      const fl = f0 + fn - 1;
      const v0 = F.vstart[f0], v1 = F.vstart[fl] + F.vcount[fl];
      const t0 = F.tstart[f0], t1 = F.tstart[fl] + F.tcount[fl];
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(pos.subarray(v0 * 3, v1 * 3), 3));
      g.setAttribute('normal', new THREE.BufferAttribute(nrm.subarray(v0 * 3, v1 * 3), 3));
      const li = new Uint32Array(idx.subarray(t0 * 3, t1 * 3));
      for (let i = 0; i < li.length; i++) li[i] -= v0;
      g.setIndex(new THREE.BufferAttribute(li, 1));
      const fid = new Float32Array(v1 - v0);
      for (let f = f0; f <= fl; f++) fid.fill(f, F.vstart[f] - v0, F.vstart[f] - v0 + F.vcount[f]);
      g.setAttribute('faceId', new THREE.BufferAttribute(fid, 1));
      g.setAttribute('color', new THREE.BufferAttribute(new Float32Array((v1 - v0) * 3), 3));
      g.computeBoundingSphere();
      g.computeBoundingBox();
      const mat = new THREE.MeshPhysicalMaterial({
        vertexColors: true, side: THREE.DoubleSide, clearcoatRoughness: 0.12,
        polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1, clippingPlanes: this.clipPlanes,
      });
      const mesh = new THREE.Mesh(g, mat);
      mesh.userData.body = bi;
      this.modelGroup.add(mesh);
      const pick = new THREE.Mesh(g, this.faceIdMat);
      pick.userData.sharedGeo = true;
      this.pickScene.add(pick);
      const finish = b.finish || null;
      const body = { index: bi, meta: b, mesh, material: mat, pick, geometry: g, v0, t0, f0, fn, visible: !b.hidden, // hidden in the SolidWorks assembly
        opacity: finish?.opacity ?? 1, finish, color: b.color || null, closed: b.kind === 'solid' || b.closed };
      this._finishBody(body);
      this.bodies.push(body);
      this._paintBody(body);
    });

    this._buildEdges();
    this._buildVertexPick();
    this._buildSilhouetteData();
    this._buildReferences();
    this._applyStyle();
    this._rebuildCaps();
    if (this.bodies.some((b) => !b.visible)) this._applyVisibility();
    this.fitAll(false, standardViews(this.upAxis).iso);
    this.requestRender();
  }

  /** The body's surface: its file finish (metal, roughness, clear coat) under RealView, else the plain look. */
  _finishBody(body) {
    const fin = this.realView ? body.finish : null;
    const m = body.material;
    m.metalness = fin?.metal ?? PLAIN_FINISH.metal;
    m.roughness = fin?.rough ?? PLAIN_FINISH.rough;
    m.clearcoat = fin?.coat ?? 0;
    // its own environment map, so the reflection strength can differ per body (three.js ignores
    // envMapIntensity for the scene-wide environment)
    m.envMap = this.scene.environment;
    m.envMapIntensity = (fin?.metal ?? 0) >= 0.5 ? METAL_REFLECTIONS : this.scene.environmentIntensity;
    m.needsUpdate = true;
  }

  /** RealView Graphics (SolidWorks' name): show the finishes and materials from the file, or plain shading. */
  setRealView(on) {
    this.realView = !!on;
    for (const b of this.bodies) {
      if (!b) continue;
      this._finishBody(b);
      b.opacity = this.realView ? (b.finish?.opacity ?? 1) : (b.finish?.opacity ? 1 : b.opacity);
      this._paintBody(b);
    }
    this._applyStyle();
    this.requestRender();
  }

  _paintBody(body) {
    const F = this.model.meta.faces;
    const col = body.geometry.attributes.color;
    const c = new THREE.Color();
    // a metal tint stands in for SolidWorks' pale "no appearance" colour while RealView is on
    const base = (this.realView && body.finish?.tint) || body.color;
    for (let f = body.f0; f < body.f0 + body.fn; f++) {
      const rgb = body.override || F.color[f] || base || DEFAULT_COLOR;
      c.setRGB(rgb[0], rgb[1], rgb[2], THREE.SRGBColorSpace);
      const a = F.vstart[f] - body.v0, n = F.vcount[f];
      for (let i = a; i < a + n; i++) col.setXYZ(i, c.r, c.g, c.b);
    }
    col.needsUpdate = true;
  }

  _buildEdges() {
    this.edgeGroup.clear();
    const { meta, segs, nE, edgeBody, nF } = this.model;
    const E = meta.edges;
    const perBody = new Map();
    for (let e = 0; e < nE; e++) {
      if (E.seam[e] && !this.showSeams) continue;
      const b = edgeBody[e];
      if (!perBody.has(b)) perBody.set(b, []);
      perBody.get(b).push(e);
    }
    this.edgeObjs = new Map();
    for (const [b, list] of perBody) {
      let n = 0;
      for (const e of list) n += E.scount[e];
      const arr = new Float32Array(n * 6), ids = new Float32Array(n * 6);
      let k = 0;
      for (const e of list) {
        const s0 = E.sstart[e], sn = E.scount[e];
        arr.set(segs.subarray(s0 * 6, (s0 + sn) * 6), k * 6);
        const [r, g, bl] = idColor(nF + e + 1);
        for (let i = 0; i < sn; i++) ids.set([r, g, bl, r, g, bl], (k + i) * 6);
        k += sn;
      }
      const geo = new LineSegmentsGeometry();
      geo.setPositions(arr);
      const mat = new LineMaterial({ color: 0x0b0d10, linewidth: 1.1, transparent: true, opacity: 0.92, clippingPlanes: this.clipPlanes });
      mat.resolution.set(this.width, this.height);
      const lines = new LineSegments2(geo, mat);
      lines.computeLineDistances();
      lines.renderOrder = 2;
      const hidden = new LineSegments2(geo, new LineMaterial({
        color: 0x8a93a1, linewidth: 1, dashed: true, transparent: true, opacity: 0.8,
        dashSize: this.rig.radius * 0.012, gapSize: this.rig.radius * 0.01, depthFunc: THREE.GreaterDepth, depthWrite: false, clippingPlanes: this.clipPlanes,
      }));
      hidden.material.resolution.set(this.width, this.height);
      hidden.userData.sharedGeo = true;
      hidden.renderOrder = 3;
      hidden.visible = false;
      this.edgeGroup.add(lines, hidden);
      const pgeo = new LineSegmentsGeometry();
      pgeo.setPositions(arr);
      pgeo.setColors(ids);
      const plines = new LineSegments2(pgeo, new LineMaterial({ linewidth: 7, vertexColors: true, clippingPlanes: this.clipPlanes, toneMapped: false }));
      // LineSegments2 sets its resolution from the canvas viewport before drawing; in the 1×1 pick
      // target that would make these lines hair-thin, so pick() sets the resolution itself
      plines.onBeforeRender = () => {};
      this.pickScene.add(plines);
      this.edgeObjs.set(b, { lines, hidden, pick: plines, edges: list });
    }
  }

  _buildVertexPick() {
    const { verts, nV, nF, nE } = this.model;
    if (!nV) { this.vertPick = null; return; }
    const cols = new Float32Array(nV * 3);
    for (let v = 0; v < nV; v++) cols.set(idColor(nF + nE + v + 1), v * 3);
    const mat = dotMaterial({ size: 17, bias: 0.0008, vertexColor: true });
    mat.clippingPlanes = this.clipPlanes;
    this.vertPick = new THREE.Mesh(dotGeometry(verts, cols), mat);
    this.vertPick.frustumCulled = false;
    this.pickScene.add(this.vertPick);
  }

  setShowSeams(on) {
    this.showSeams = on;
    if (!this.model) return;
    this.pickScene.children.filter((o) => o.isLineSegments2).forEach((o) => this.pickScene.remove(o));
    this._buildEdges();
    this._applyStyle();
    this._applyVisibility();
  }

  // ================================================================== silhouettes
  _buildSilhouetteData() {
    const { meta, pos, idx } = this.model;
    const F = meta.faces;
    const a = [], b = [], t1 = [], t2 = [], bodyOf = [];
    let nTri = 0;
    for (let f = 0; f < F.type.length; f++) {
      if (F.type[f] === 'plane') continue;
      const t0 = F.tstart[f], tn = F.tcount[f];
      if (tn < 2) continue;
      nTri += tn;
      const edges = new Map();
      for (let t = t0; t < t0 + tn; t++) {
        for (let k = 0; k < 3; k++) {
          const i = idx[t * 3 + k], j = idx[t * 3 + ((k + 1) % 3)];
          const key = i < j ? i * 4294967296 + j : j * 4294967296 + i;
          const hit = edges.get(key);
          if (hit === undefined) edges.set(key, t);
          else if (hit >= 0) { a.push(Math.min(i, j)); b.push(Math.max(i, j)); t1.push(hit); t2.push(t); bodyOf.push(F.body[f]); edges.set(key, -1); }
        }
      }
    }
    if (!a.length || nTri > 3e6) { this.silData = null; return; }
    const tn = new Float32Array(idx.length), tc = new Float32Array(idx.length);
    for (let t = 0; t < idx.length / 3; t++) {
      const i0 = idx[t * 3] * 3, i1 = idx[t * 3 + 1] * 3, i2 = idx[t * 3 + 2] * 3;
      const ux = pos[i1] - pos[i0], uy = pos[i1 + 1] - pos[i0 + 1], uz = pos[i1 + 2] - pos[i0 + 2];
      const vx = pos[i2] - pos[i0], vy = pos[i2 + 1] - pos[i0 + 1], vz = pos[i2 + 2] - pos[i0 + 2];
      tn[t * 3] = uy * vz - uz * vy; tn[t * 3 + 1] = uz * vx - ux * vz; tn[t * 3 + 2] = ux * vy - uy * vx;
      tc[t * 3] = (pos[i0] + pos[i1] + pos[i2]) / 3; tc[t * 3 + 1] = (pos[i0 + 1] + pos[i1 + 1] + pos[i2 + 1]) / 3; tc[t * 3 + 2] = (pos[i0 + 2] + pos[i1 + 2] + pos[i2 + 2]) / 3;
    }
    this.silData = { a: Int32Array.from(a), b: Int32Array.from(b), t1: Int32Array.from(t1), t2: Int32Array.from(t2), body: Int32Array.from(bodyOf), tn, tc };
    const mat = new LineMaterial({ color: 0x0b0d10, linewidth: 1.1, transparent: true, opacity: 0.92, clippingPlanes: this.clipPlanes });
    mat.resolution.set(this.width, this.height);
    this.silLines = new LineSegments2(new LineSegmentsGeometry(), mat);
    this.silLines.renderOrder = 2;
    this.silLines.frustumCulled = false;
    this.silGroup.add(this.silLines);
  }

  // big models: recompute outlines once the view stops moving, not every frame
  _silhouettesSoon() {
    if (!this.silData || !this.showSilhouettes || !this.silGroup.visible) return;
    if (this.silData.a.length < 120000) { this._updateSilhouettes(); return; }
    this.silLines.visible = false;
    clearTimeout(this._silTimer);
    this._silTimer = setTimeout(() => { this._updateSilhouettes(); this.requestRender(); }, 140);
  }

  _updateSilhouettes() {
    const s = this.silData;
    if (!s || !this.silLines) return;
    const { pos } = this.model;
    const persp = this.rig.perspective, d = this.rig.dir(), eye = this.rig.camera.position;
    const hidden = this.bodies.map((b) => !b || !b.visible);
    const out = [];
    for (let i = 0; i < s.a.length; i++) {
      if (hidden[s.body[i]]) continue;
      const p = s.t1[i] * 3, q = s.t2[i] * 3;
      let dp, dq;
      if (persp) {
        dp = s.tn[p] * (eye.x - s.tc[p]) + s.tn[p + 1] * (eye.y - s.tc[p + 1]) + s.tn[p + 2] * (eye.z - s.tc[p + 2]);
        dq = s.tn[q] * (eye.x - s.tc[q]) + s.tn[q + 1] * (eye.y - s.tc[q + 1]) + s.tn[q + 2] * (eye.z - s.tc[q + 2]);
      } else {
        dp = s.tn[p] * d.x + s.tn[p + 1] * d.y + s.tn[p + 2] * d.z;
        dq = s.tn[q] * d.x + s.tn[q + 1] * d.y + s.tn[q + 2] * d.z;
      }
      if ((dp > 0) !== (dq > 0)) {
        const ia = s.a[i] * 3, ib = s.b[i] * 3;
        out.push(pos[ia], pos[ia + 1], pos[ia + 2], pos[ib], pos[ib + 1], pos[ib + 2]);
      }
    }
    const geo = new LineSegmentsGeometry();
    if (out.length) geo.setPositions(out);
    this.silLines.geometry.dispose();
    this.silLines.geometry = geo;
    this.silLines.visible = out.length > 0;
  }

  // ================================================================== display styles
  setStyle(style) { this.style = style; this._applyStyle(); this.requestRender(); }

  _applyStyle() {
    if (!this.model) return;
    const s = this.style;
    const lightLines = (s !== 'shadedEdges' && s !== 'shaded') && this.darkScene;
    const lineColor = lightLines ? 0xe2e8f0 : 0x0b0d10;
    for (const b of this.bodies) {
      if (!b) continue;
      const shaded = s === 'shadedEdges' || s === 'shaded';
      b.mesh.material = this.analysis ? this.analysisMat : b.material;
      const m = b.material;
      m.colorWrite = shaded;
      m.depthWrite = s !== 'wire';
      m.transparent = shaded && b.opacity < 1;
      m.opacity = shaded ? b.opacity : 1;
      if (m.transparent) m.depthWrite = false;
      m.needsUpdate = true;
    }
    for (const [, o] of this.edgeObjs || []) {
      o.lines.material.color.set(lineColor);
      o.lines.material.opacity = s === 'shadedEdges' ? 0.92 : 1;
      o.lines.material.linewidth = s === 'shadedEdges' ? 1.1 : 1.25;
      o.lines.material.depthTest = s !== 'wire';
    }
    const showLines = s !== 'shaded' || !!this.analysis;
    this.edgeGroup.visible = showLines;
    this.silGroup.visible = this.showSilhouettes && showLines;
    if (this.silLines) { this.silLines.material.color.set(lineColor); this.silLines.material.depthTest = s !== 'wire'; }
    this._applyVisibility();
    this.viewChanged = true;
  }

  // ================================================================== analysis shading
  setAnalysis(cfg) {
    this.analysis = cfg;
    const u = this.analysisMat.uniforms;
    if (cfg?.type === 'draft') { u.mode.value = 0; u.pullDir.value.set(...cfg.dir); u.sinAngle.value = Math.sin(THREE.MathUtils.degToRad(cfg.angle)); }
    if (cfg?.type === 'zebra') { u.mode.value = 1; u.stripes.value = cfg.count; u.stripeWidth.value = cfg.width; }
    if (cfg?.type === 'curvature') { u.mode.value = 2; u.curvScale.value = cfg.scale; }
    this.analysisMat.clippingPlanes = this.clipPlanes;
    this._applyStyle();
    this.requestRender();
  }

  // ================================================================== bodies
  _applyVisibility() {
    if (!this.model) return;
    for (const b of this.bodies) {
      if (!b) continue;
      b.mesh.visible = b.visible && (this.style !== 'wire' || !!this.analysis);
      b.pick.visible = b.visible;
      const eo = this.edgeObjs?.get(b.index);
      if (eo) {
        eo.lines.visible = b.visible;
        eo.hidden.visible = b.visible && this.style === 'hlv' && !this.analysis;
        eo.pick.visible = b.visible;
      }
    }
    if (this.vertPick) {
      const { verts, vertBody, nV, nF, nE } = this.model;
      const pts = [], cols = [];
      for (let v = 0; v < nV; v++) {
        const b = this.bodies[vertBody[v]];
        if (b && !b.visible) continue;
        pts.push(verts[v * 3], verts[v * 3 + 1], verts[v * 3 + 2]);
        cols.push(...idColor(nF + nE + v + 1));
      }
      this.vertPick.geometry.dispose();
      this.vertPick.geometry = dotGeometry(pts, cols);
    }
    this._rebuildCaps();
    this.viewChanged = true;
    this.requestRender();
  }

  setBodyVisible(bi, on) { const b = this.bodies[bi]; if (!b) return; b.visible = on; this._applyVisibility(); }
  showAll() { this.bodies.forEach((b) => b && (b.visible = true)); this._applyVisibility(); }
  isolate(bis) { const keep = new Set(bis); this.bodies.forEach((b) => b && (b.visible = keep.has(b.index))); this._applyVisibility(); }
  setBodyColor(bi, rgb) { const b = this.bodies[bi]; if (!b) return; b.override = rgb; this._paintBody(b); this._rebuildCaps(); this.requestRender(); }
  setBodyOpacity(bi, a) { const b = this.bodies[bi]; if (!b) return; b.opacity = a; this._applyStyle(); this.requestRender(); }

  bodyColor(bi) {
    const b = this.bodies[bi];
    if (!b) return DEFAULT_COLOR;
    return b.override || b.color || this.model.meta.faces.color[b.f0] || DEFAULT_COLOR;
  }

  visibleBox() {
    const box = new THREE.Box3();
    for (const b of this.bodies) if (b && b.visible) box.union(b.geometry.boundingBox);
    return box.isEmpty() ? this.model?.box : box;
  }

  bodyBox(bi) { return this.bodies[bi]?.geometry.boundingBox.clone() || new THREE.Box3(); }

  entityBox(ent) {
    const box = new THREE.Box3();
    const pts = this.entityPoints(ent);
    for (let i = 0; i < pts.length; i += 3) box.expandByPoint(new THREE.Vector3(pts[i], pts[i + 1], pts[i + 2]));
    return box;
  }

  entityPoints(ent) {
    const m = this.model;
    if (ent.kind === 'vertex') return m.verts.subarray(ent.index * 3, ent.index * 3 + 3);
    if (ent.kind === 'point') return new Float32Array(ent.point);
    if (ent.kind === 'edge') { const s0 = m.meta.edges.sstart[ent.index], sn = m.meta.edges.scount[ent.index]; return m.segs.subarray(s0 * 6, (s0 + sn) * 6); }
    const F = m.meta.faces;
    return m.pos.subarray(F.vstart[ent.index] * 3, (F.vstart[ent.index] + F.vcount[ent.index]) * 3);
  }

  // ================================================================== planes and origin
  planeName(i) { return PLANES[i]?.name || 'Plane'; }
  planeNormal(i) { return PLANES[i].n.slice(); }
  planeShown(i) { return !!this.planeVis[i]; }
  showPlane(i, on) { this.planeVis[i] = on; this.planesVisible = this.planeVis.some(Boolean); this._buildReferences(); }
  setPlanesVisible(on) { this.planeVis = [on, on, on]; this.planesVisible = on; this._buildReferences(); }
  setOriginVisible(on) { this.originVisible = on; this._buildReferences(); }

  _planeQuad(i) {
    const p = PLANES[i], box = this.model.box;
    const n = new THREE.Vector3(...p.n), u = new THREE.Vector3(...p.u), v = new THREE.Vector3(...p.v);
    const center = box.getCenter(new THREE.Vector3());
    const c = center.clone().sub(n.clone().multiplyScalar(center.dot(n))); // on the plane, through the origin
    const size = box.getSize(new THREE.Vector3());
    const ext = (dir) => Math.abs(size.x * dir.x) + Math.abs(size.y * dir.y) + Math.abs(size.z * dir.z);
    const hu = Math.max(ext(u) * 0.6, this.rig.radius * 0.15), hv = Math.max(ext(v) * 0.6, this.rig.radius * 0.15);
    const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([a, b]) => c.clone().addScaledVector(u, a * hu).addScaledVector(v, b * hv));
    return { corners, n };
  }

  _buildReferences(highlight = null) {
    this.refGroup.traverse((o) => { if (o.geometry) o.geometry.dispose(); });
    this.refGroup.clear();
    this.labels = this.labels.filter((l) => { if (l.ref) { l.el.remove(); l.lead?.remove(); return false; } return true; });
    if (!this.model) return;
    const sel = new Set(this.selection.filter((s) => s.kind === 'plane').map((s) => s.index));
    const hov = this.hover?.kind === 'plane' ? this.hover.index : -1;
    for (let i = 0; i < 3; i++) {
      const isSel = sel.has(i), isHov = hov === i;
      if (!this.planeVis[i] && !isSel && !isHov && highlight !== i) continue;
      const { corners } = this._planeQuad(i);
      const g = new THREE.BufferGeometry().setFromPoints([corners[0], corners[1], corners[2], corners[0], corners[2], corners[3]]);
      const color = isSel ? SEL : isHov ? PRE : new THREE.Color(0x7c9bd8);
      const quad = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color, transparent: true, opacity: isSel || isHov ? 0.22 : 0.12, side: THREE.DoubleSide, depthWrite: false, toneMapped: false }));
      quad.renderOrder = 8;
      this.refGroup.add(quad);
      const pts = [];
      for (let k = 0; k < 4; k++) pts.push(...corners[k].toArray(), ...corners[(k + 1) % 4].toArray());
      this._fatLine(pts, isSel ? SEL : isHov ? PRE : 0x3a5193, isSel || isHov ? 2 : 1.2, { group: this.refGroup, noClip: true, order: 9 });
      const el = document.createElement('div');
      el.className = 'mlabel plane small';
      el.textContent = PLANES[i].name;
      this.labelLayer.append(el);
      this.labels.push({ el, pos: corners[3].clone(), ref: true });
    }
    if (this.originVisible || this.selection.some((s) => s.kind === 'origin')) {
      const L = this.rig.radius * 0.18;
      const o = new THREE.Vector3();
      this._fatLine([0, 0, 0, L, 0, 0], 0xd93a3a, 2.2, { group: this.refGroup, noClip: true, order: 9, depthTest: false });
      this._fatLine([0, 0, 0, 0, L, 0], 0x2f9e46, 2.2, { group: this.refGroup, noClip: true, order: 9, depthTest: false });
      this._fatLine([0, 0, 0, 0, 0, L], 0x2c63d6, 2.2, { group: this.refGroup, noClip: true, order: 9, depthTest: false });
      const mat = dotMaterial({ size: 6, color: 0x213367, depthTest: false });
      mat.uniforms.resolution.value.set(this.width, this.height);
      const dot = new THREE.Mesh(dotGeometry([0, 0, 0]), mat);
      dot.frustumCulled = false;
      dot.renderOrder = 10;
      this.refGroup.add(dot);
      void o;
    }
    this.requestRender();
  }

  // ================================================================== views
  fitAll(animate = true, view = null) {
    if (!this.model) return;
    const quat = view ? this.rig.orient(view.dir, view.up) : null;
    this.rig.fit(this.visibleBox(), animate, quat);
  }

  fitBox(box) { if (box && !box.isEmpty()) this.rig.fit(box, true); }

  setView(name) {
    const v = standardViews(this.upAxis)[name];
    if (!v) return;
    const quat = this.rig.orient(v.dir, v.up);
    this.rig.animateTo(this.model ? this.rig.fitState(this.visibleBox(), quat) : { quat });
  }

  viewAlong(dir, fit = false) {
    const views = standardViews(this.upAxis);
    let up = views.front.up.clone();
    if (Math.abs(dir.clone().normalize().dot(up)) > 0.99) up = views.top.up.clone().multiplyScalar(Math.sign(dir.dot(views.top.dir)) || 1);
    const quat = this.rig.orient(dir, up);
    if (fit && this.model) this.rig.animateTo(this.rig.fitState(this.visibleBox(), quat));
    else this.rig.animateTo({ quat });
  }

  normalTo(normal, point) {
    const n = new THREE.Vector3(...normal).normalize();
    if (this.rig.dir().dot(n) > 0.9999) n.negate(); // a second press looks from the other side
    const s = { quat: this.rig.orient(n, this.rig.upVec()) };
    if (point) s.target = new THREE.Vector3(...point);
    this.rig.animateTo(s);
  }

  rotateView(axis, deg) {
    const a = axis === 'screenY' ? this.rig.upVec() : axis === 'screenX' ? this.rig.rightVec() : this.rig.dir();
    const quat = this.rig.quat.clone().premultiply(new THREE.Quaternion().setFromAxisAngle(a, THREE.MathUtils.degToRad(deg)));
    this.rig.animateTo({ quat }, 300);
  }

  setPerspective(on) {
    this.rig.perspective = on;
    this.rig.changed();
    this.requestRender();
  }

  // ================================================================== picking
  _renderPick(x, y, target) {
    const cam = this.rig.camera;
    cam.setViewOffset(this.width, this.height, x, y, 1, 1);
    this.pickScene.children.forEach((o) => { if (o.isLineSegments2) o.material.resolution.set(1, 1); });
    if (this.vertPick) this.vertPick.material.uniforms.resolution.value.set(1, 1);
    const r = this.renderer;
    const prevTone = r.toneMapping;
    r.toneMapping = THREE.NoToneMapping;
    r.setRenderTarget(target);
    r.setClearColor(0x000000, 1);
    r.clear(true, true, true);
    r.render(this.pickScene, cam);
    r.setRenderTarget(null);
    r.toneMapping = prevTone;
    cam.clearViewOffset();
    this.rig.update();
  }

  _decode(buf, x, y) {
    const id = buf[0] | (buf[1] << 8) | (buf[2] << 16);
    if (!id) return null;
    const { nF, nE } = this.model;
    if (id <= nF) return { kind: 'face', index: id - 1, point: this._hitPoint(id - 1, x, y) };
    if (id <= nF + nE) return { kind: 'edge', index: id - nF - 1 };
    return { kind: 'vertex', index: id - nF - nE - 1 };
  }

  pick(x, y) {
    if (!this.model) return null;
    this._renderPick(x, y, this.pickTarget);
    this.renderer.readRenderTargetPixels(this.pickTarget, 0, 0, 1, 1, this.pickBuf);
    return this._decode(this.pickBuf, x, y);
  }

  // hover picks read back asynchronously so the GPU never stalls while the mouse moves
  async pickAsync(x, y) {
    if (!this.model) return null;
    if (!this.renderer.readRenderTargetPixelsAsync) return this.pick(x, y);
    this._renderPick(x, y, this.hoverTarget);
    await this.renderer.readRenderTargetPixelsAsync(this.hoverTarget, 0, 0, 1, 1, this.hoverBuf);
    return this.model ? this._decode(this.hoverBuf, x, y) : null;
  }

  ray(x, y) {
    const rc = new THREE.Raycaster();
    rc.setFromCamera(new THREE.Vector2((x / this.width) * 2 - 1, -(y / this.height) * 2 + 1), this.rig.camera);
    return rc.ray;
  }

  _hitPoint(face, x, y) {
    const ray = this.ray(x, y);
    const { pos, idx, meta } = this.model;
    const F = meta.faces;
    const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3(), hit = new THREE.Vector3();
    let best = null, bestD = Infinity;
    for (let t = F.tstart[face]; t < F.tstart[face] + F.tcount[face]; t++) {
      a.fromArray(pos, idx[t * 3] * 3); b.fromArray(pos, idx[t * 3 + 1] * 3); c.fromArray(pos, idx[t * 3 + 2] * 3);
      if (ray.intersectTriangle(a, b, c, false, hit)) {
        const d = hit.distanceToSquared(ray.origin);
        if (d < bestD && this.clipPlanes.every((pl) => pl.distanceToPoint(hit) >= -1e-9)) { bestD = d; best = hit.clone(); }
      }
    }
    return best ? [best.x, best.y, best.z] : null;
  }

  pointAt(x, y) {
    const hit = this.pick(x, y);
    if (!hit) return null;
    if (hit.point) return new THREE.Vector3(...hit.point);
    const pts = this.entityPoints(hit);
    if (hit.kind === 'vertex') return new THREE.Vector3(pts[0], pts[1], pts[2]);
    const ray = this.ray(x, y);
    let best = null, bestD = Infinity;
    const p = new THREE.Vector3();
    for (let i = 0; i < pts.length; i += 3) {
      p.set(pts[i], pts[i + 1], pts[i + 2]);
      const d = ray.distanceSqToPoint(p);
      if (d < bestD) { bestD = d; best = p.clone(); }
    }
    return best;
  }

  // SolidWorks: middle-click a vertex, edge or face to rotate about it (a straight edge is an axis);
  // middle-click empty space to go back to the model's centre
  setRotationCenter(hit) {
    this.rotCenter = null;
    if (!hit) return;
    const v = (a) => new THREE.Vector3(a[0], a[1], a[2]);
    const E = this.model.meta.edges;
    if (hit.kind === 'vertex') this.rotCenter = { point: v(this.entityPoints(hit)) };
    else if (hit.kind === 'edge') {
      const t = E.type[hit.index], p = E.params[hit.index] || {};
      if (t === 'line' && p.start && p.dir) this.rotCenter = { point: v(p.start).lerp(v(p.end), 0.5), axis: v(p.dir).normalize() };
      else if (t === 'circle' && p.center) this.rotCenter = { point: v(p.center) };
      else this.rotCenter = { point: this.entityBox(hit).getCenter(new THREE.Vector3()) };
    } else if (hit.kind === 'face' && hit.point) this.rotCenter = { point: v(hit.point) };
  }

  // every visible face the ray under (x, y) passes through, nearest first (for Select Other)
  facesUnder(x, y) {
    if (!this.model) return [];
    const ray = this.ray(x, y);
    const { pos, idx, meta } = this.model;
    const F = meta.faces;
    const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3(), hit = new THREE.Vector3();
    const out = [];
    for (let f = 0; f < F.type.length; f++) {
      if (!this.bodies[F.body[f]]?.visible) continue;
      let best = Infinity;
      for (let t = F.tstart[f]; t < F.tstart[f] + F.tcount[f]; t++) {
        a.fromArray(pos, idx[t * 3] * 3); b.fromArray(pos, idx[t * 3 + 1] * 3); c.fromArray(pos, idx[t * 3 + 2] * 3);
        if (ray.intersectTriangle(a, b, c, false, hit) && this.clipPlanes.every((pl) => pl.distanceToPoint(hit) >= -1e-9)) {
          best = Math.min(best, hit.distanceToSquared(ray.origin));
        }
      }
      if (best < Infinity) out.push({ index: f, d: best });
    }
    return out.sort((p, q) => p.d - q.d).map((o) => ({ kind: 'face', index: o.index }));
  }

  project(v) {
    const p = v.clone().project(this.rig.camera);
    return { x: (p.x + 1) / 2 * this.width, y: (1 - p.y) / 2 * this.height, behind: p.z > 1 || p.z < -1 };
  }

  // ================================================================== highlights
  setHover(ent) {
    const same = (a, b) => a && b && a.kind === b.kind && a.index === b.index;
    if (same(ent, this.hover) || (!ent && !this.hover)) return;
    const planeInvolved = this.hover?.kind === 'plane' || ent?.kind === 'plane';
    this.hover = ent;
    this._drawHighlights();
    if (planeInvolved) this._buildReferences();
  }

  setSelection(list) {
    this.selection = list.slice();
    this._drawHighlights();
    this._buildReferences();
  }

  _drawHighlights() {
    for (const o of [...this.overlay.children]) { if (o.geometry && !o.userData.sharedGeo) o.geometry.dispose(); this.overlay.remove(o); }
    for (const s of this.selection) this._highlight(s, SEL, false);
    if (this.hover && !this.selection.some((s) => s.kind === this.hover.kind && s.index === this.hover.index)) this._highlight(this.hover, PRE, true);
    this.requestRender();
  }

  _highlight(ent, color, isHover) {
    const m = this.model;
    if (!m || ent.kind === 'plane' || ent.kind === 'origin') return;
    if (ent.kind === 'face' || ent.kind === 'body') {
      const faces = ent.kind === 'body' ? (() => { const b = this.bodies[ent.index]; return b ? Array.from({ length: b.fn }, (_, i) => b.f0 + i) : []; })() : [ent.index];
      const F = m.meta.faces;
      for (const f of faces) {
        const body = this.bodies[m.faceBody[f]];
        if (!body || !body.visible) continue;
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', body.geometry.attributes.position);
        g.setAttribute('normal', body.geometry.attributes.normal);
        g.setIndex(body.geometry.index);
        g.setDrawRange((F.tstart[f] - body.t0) * 3, F.tcount[f] * 3);
        const mesh = new THREE.Mesh(g, new THREE.MeshBasicMaterial({
          color, transparent: true, opacity: isHover ? 0.3 : 0.45, depthWrite: false, side: THREE.DoubleSide,
          polygonOffset: true, polygonOffsetFactor: 0, polygonOffsetUnits: -1, clippingPlanes: this.clipPlanes, toneMapped: false,
        }));
        mesh.renderOrder = 5;
        this.overlay.add(mesh);
      }
      if (ent.kind === 'face') this._outlineFace(ent.index, color, isHover);
      return;
    }
    if (ent.kind === 'edge') { this._fatLine(this.entityPoints(ent), color, isHover ? 2.6 : 3); return; }
    if (ent.kind === 'vertex' || ent.kind === 'point') {
      const p = ent.kind === 'point' ? ent.point : Array.from(this.entityPoints(ent));
      const mat = dotMaterial({ size: 7, color, depthTest: false, ring: true });
      mat.uniforms.resolution.value.set(this.width, this.height);
      const dot = new THREE.Mesh(dotGeometry(p), mat);
      dot.frustumCulled = false;
      dot.renderOrder = 9;
      this.overlay.add(dot);
    }
  }

  _outlineFace(f, color, isHover) {
    const E = this.model.meta.edges;
    const parts = [];
    for (let e = 0; e < E.faces.length; e++) if (!E.seam[e] && E.faces[e].includes(f)) parts.push(this.entityPoints({ kind: 'edge', index: e }));
    if (!parts.length) return;
    const all = new Float32Array(parts.reduce((n, p) => n + p.length, 0));
    let k = 0;
    parts.forEach((p) => { all.set(p, k); k += p.length; });
    this._fatLine(all, color, isHover ? 1.8 : 2.2);
  }

  _fatLine(pts, color, width, opts = {}) {
    const geo = new LineSegmentsGeometry();
    geo.setPositions(pts);
    const mat = new LineMaterial({
      color, linewidth: width, clippingPlanes: opts.noClip ? [] : this.clipPlanes, toneMapped: false,
      depthTest: opts.depthTest ?? true, transparent: !!opts.dashed, dashed: !!opts.dashed, dashSize: opts.dashSize ?? 1, gapSize: opts.gapSize ?? 1,
    });
    mat.resolution.set(this.width, this.height);
    const l = new LineSegments2(geo, mat);
    if (opts.dashed) l.computeLineDistances();
    l.renderOrder = opts.order ?? 6;
    l.frustumCulled = false;
    (opts.group || this.overlay).add(l);
    return l;
  }

  // ================================================================== section view
  setSection(plane) {
    this.clipPlanes.length = 0;
    if (plane) this.clipPlanes.push(plane);
    this.section = plane;
    this._rebuildCaps();
    this.viewChanged = true;
    this.requestRender();
  }

  _rebuildCaps() {
    this.capGroup.traverse((o) => { if (o.geometry && !o.userData.sharedGeo) o.geometry.dispose(); });
    this.capGroup.clear();
    if (!this.section || !this.model) return;
    const plane = this.section;
    const center = this.model.box.getCenter(new THREE.Vector3());
    const onPlane = plane.projectPoint(center, new THREE.Vector3());
    if (this.capsOn !== false) {
      const planeGeo = new THREE.PlaneGeometry(this.rig.radius * 6, this.rig.radius * 6);
      let order = 20;
      for (const b of this.bodies) {
        if (!b || !b.visible || !b.closed) continue;
        const base = { depthWrite: false, depthTest: false, colorWrite: false, stencilWrite: true, stencilFunc: THREE.AlwaysStencilFunc, clippingPlanes: this.clipPlanes };
        const back = new THREE.Mesh(b.geometry, new THREE.MeshBasicMaterial({ ...base, side: THREE.BackSide, stencilFail: THREE.IncrementWrapStencilOp, stencilZFail: THREE.IncrementWrapStencilOp, stencilZPass: THREE.IncrementWrapStencilOp }));
        const front = new THREE.Mesh(b.geometry, new THREE.MeshBasicMaterial({ ...base, side: THREE.FrontSide, stencilFail: THREE.DecrementWrapStencilOp, stencilZFail: THREE.DecrementWrapStencilOp, stencilZPass: THREE.DecrementWrapStencilOp }));
        back.userData.sharedGeo = front.userData.sharedGeo = true;
        back.renderOrder = front.renderOrder = order;
        const capColor = this.capColor ? new THREE.Color(this.capColor) : (() => { const rgb = this.bodyColor(b.index); return new THREE.Color().setRGB(rgb[0], rgb[1], rgb[2], THREE.SRGBColorSpace).multiplyScalar(0.8); })();
        const cap = new THREE.Mesh(planeGeo, new THREE.MeshStandardMaterial({
          color: capColor, metalness: 0.05, roughness: 0.75, side: THREE.DoubleSide,
          stencilWrite: true, stencilRef: 0, stencilFunc: THREE.NotEqualStencilFunc, stencilFail: THREE.ReplaceStencilOp, stencilZFail: THREE.ReplaceStencilOp, stencilZPass: THREE.ReplaceStencilOp,
        }));
        cap.userData.sharedGeo = true;
        cap.position.copy(onPlane);
        cap.lookAt(onPlane.clone().sub(plane.normal));
        cap.renderOrder = order + 1;
        cap.onAfterRender = (r) => r.clearStencil();
        this.capGroup.add(back, front, cap);
        order += 2;
      }
    }
    const half = this.rig.radius * 1.15;
    const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1), plane.normal);
    const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([u, v]) => new THREE.Vector3(u * half, v * half, 0).applyQuaternion(q).add(onPlane));
    const pts = [];
    for (let i = 0; i < 4; i++) pts.push(...corners[i].toArray(), ...corners[(i + 1) % 4].toArray());
    this._fatLine(pts, 0x3a5193, 1.4, { group: this.capGroup, noClip: true, order: 40 });
  }

  // ================================================================== bounding box display
  showBox(b) {
    this.boxGroup.traverse((o) => { if (o.geometry) o.geometry.dispose(); });
    this.boxGroup.clear();
    this.labels = this.labels.filter((l) => { if (l.box) { l.el.remove(); l.lead?.remove(); return false; } return true; });
    this.bboxShown = !!b;
    this.shownBox = null;
    if (!b) { this.requestRender(); return; }
    const ax = b.axes.map((a) => new THREE.Vector3(...a));
    const corner = (i) => ax[0].clone().multiplyScalar(i & 1 ? b.max[0] : b.min[0]).addScaledVector(ax[1], i & 2 ? b.max[1] : b.min[1]).addScaledVector(ax[2], i & 4 ? b.max[2] : b.min[2]);
    const pts = [];
    for (let i = 0; i < 8; i++) for (const bit of [1, 2, 4]) if (!(i & bit)) pts.push(...corner(i).toArray(), ...corner(i | bit).toArray());
    this._fatLine(pts, 0xd99a1c, 1.6, { group: this.boxGroup, noClip: true, order: 30, dashed: true, dashSize: this.rig.radius * 0.03, gapSize: this.rig.radius * 0.015 });
    // its size along each side, on the three edges that meet at the corner nearest the viewer (moved as
    // the view turns, in _placeLabels), the way SolidWorks dimensions it
    const fmt = this.formatLength || ((mm) => `${mm.toFixed(2)} mm`);
    [1, 2, 4].forEach((bit, k) => {
      this.addLabel(corner(0), fmt(b.max[k] - b.min[k]), 'box');
      Object.assign(this.labels[this.labels.length - 1], { box: true, boxBit: bit });
    });
    this.boxCorner = corner;
    this.shownBox = b;
    this.requestRender();
  }

  // the box corner nearest the viewer; when several are equally near (looking straight at a side), the one
  // lowest and furthest left on screen, so the sizes read along the bottom and left like a drawing
  _nearBoxCorner() {
    const eye = this.rig.dir(), c = [...Array(8).keys()].map((i) => this.boxCorner(i));
    const depth = c.map((p) => p.dot(eye)), top = Math.max(...depth), tol = this.rig.radius * 1e-6;
    const score = (i) => { const s = this.project(c[i]); return s.y - s.x; };
    return [...Array(8).keys()].filter((i) => depth[i] > top - tol).reduce((a, i) => (score(i) > score(a) ? i : a));
  }

  // ================================================================== View Selector cube
  setSelector(on) {
    this.selectorOn = on;
    this.selGroup.traverse((o) => { if (o.geometry) o.geometry.dispose(); });
    this.selGroup.clear();
    this.selHover = null;
    if (on && this.model) {
      const c = this.visibleBox().getCenter(new THREE.Vector3());
      const s = this.rig.radius * 2.05;
      const cube = new THREE.Mesh(new THREE.BoxGeometry(s, s, s), new THREE.MeshBasicMaterial({ color: 0x5b7fd0, transparent: true, opacity: 0.1, depthWrite: false, side: THREE.DoubleSide, toneMapped: false }));
      cube.position.copy(c);
      cube.renderOrder = 50;
      this.selCube = cube;
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(cube.geometry), new THREE.LineBasicMaterial({ color: 0x213367, transparent: true, opacity: 0.55 }));
      cube.add(edges);
      this.selHl = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial({ color: 0x1f6fff, transparent: true, opacity: 0.35, depthWrite: false, toneMapped: false }));
      this.selHl.visible = false;
      this.selHl.renderOrder = 51;
      cube.add(this.selHl);
      this.selGroup.add(cube);
    }
    this.requestRender();
  }

  _selectorHit(x, y) {
    if (!this.selectorOn || !this.selCube) return null;
    const rc = new THREE.Raycaster();
    rc.setFromCamera(new THREE.Vector2((x / this.width) * 2 - 1, -(y / this.height) * 2 + 1), this.rig.camera);
    const hit = rc.intersectObject(this.selCube, false)[0];
    if (!hit) return null;
    const half = this.selCube.geometry.parameters.width / 2;
    const local = this.selCube.worldToLocal(hit.point.clone()).divideScalar(half);
    const reg = [local.x, local.y, local.z].map((c) => (Math.abs(c) > 0.98 ? Math.sign(c) : Math.abs(c) > 0.6 ? Math.sign(c) : 0));
    return { key: reg.join(','), reg, dir: new THREE.Vector3(...reg).normalize() };
  }

  _selectorHover(hit) {
    const key = hit?.key || null;
    if (key === this.selHover) return;
    this.selHover = key;
    if (!hit) { this.selHl.visible = false; this.requestRender(); return; }
    const half = this.selCube.geometry.parameters.width / 2;
    const sc = new THREE.Vector3(), c = new THREE.Vector3();
    hit.reg.forEach((v, i) => { sc.setComponent(i, (v ? 0.42 : 1.24) * half); c.setComponent(i, v ? v * (1 - 0.21 + 0.03) * half : 0); });
    this.selHl.scale.copy(sc);
    this.selHl.position.copy(c);
    this.selHl.visible = true;
    this.requestRender();
  }

  // ================================================================== measurement graphics & labels
  clearLabels() { for (const l of this.labels) { l.el.remove(); l.lead?.remove(); } this.labels = []; }

  clearAnnotations() {
    this.annot.traverse((o) => { if (o.geometry) o.geometry.dispose(); });
    this.annot.clear();
    this.labels = this.labels.filter((l) => { if (!l.ref && !l.box && !l.preview) { l.el.remove(); l.lead?.remove(); return false; } return true; });
    this.requestRender();
  }

  addLabel(pos, html, cls = '') {
    const el = document.createElement('div');
    el.className = `mlabel ${cls}`;
    el.innerHTML = html;
    this.labelLayer.append(el);
    this.labels.push({ el, pos: pos.clone() });
    this.requestRender();
    return el;
  }

  // Labels sit on their points unless that would cover another label or something on screen (the
  // heads-up toolbar, view cube, triad, a tool window over the view). The most important go first (the
  // measured value, then other values, then the small dX / dY / dZ and notes); each later one keeps the
  // spot it had last frame if that's still free, so labels don't jump about while the view turns, and
  // otherwise moves to the nearest free spot around its point, with a thin leader line back to it.
  _placeLabels() {
    const rank = (l) => (l.el.classList.contains('primary') ? 0 : l.el.classList.contains('small') ? 2 : 1);
    if (this.shownBox && this.labels.some((l) => l.boxBit)) {
      const near = this._nearBoxCorner();
      for (const l of this.labels) if (l.boxBit) l.pos.copy(this.boxCorner(near)).add(this.boxCorner(near ^ l.boxBit)).multiplyScalar(0.5);
    }
    const items = [];
    for (const l of this.labels) {
      const s = this.project(l.pos);
      if (s.behind) { l.el.style.display = 'none'; if (l.lead) l.lead.style.display = 'none'; continue; }
      l.el.style.display = '';
      items.push({ l, s, w: l.el.offsetWidth, h: l.el.offsetHeight, rank: rank(l) });
    }
    if (!items.length) return;
    items.sort((a, b) => a.rank - b.rank);
    const PAD = 3, placed = this._labelObstacles();
    const overlap = (x, y, w, h) => {
      let sum = 0;
      for (const r of placed) {
        const ox = (w + r.w) / 2 + PAD - Math.abs(x - r.x), oy = (h + r.h) / 2 + PAD - Math.abs(y - r.y);
        if (ox > 0 && oy > 0) sum += ox * oy;
      }
      return sum;
    };
    const clampX = (x, w) => Math.min(Math.max(x, w / 2), this.width - w / 2);
    const clampY = (y, h) => Math.min(Math.max(y, h / 2), this.height - h / 2);
    for (const it of items) {
      const l = it.l, ax = it.s.x, ay = it.s.y;
      let x = clampX(ax, it.w), y = clampY(ay, it.h);
      if (overlap(x, y, it.w, it.h) > 0) {
        const tries = [];
        if (l.off) tries.push(l.off);
        const step = it.h + PAD * 2;
        for (let ring = 1; ring <= 12; ring++) {
          // below / above first (labels are wide), then sideways, then the corners
          const d = ring * step, dx = (it.w / 2 + PAD) * ring;
          tries.push([0, d], [0, -d], [dx + it.w / 2, 0], [-dx - it.w / 2, 0], [dx, d], [-dx, d], [dx, -d], [-dx, -d]);
        }
        let best = null, bestCost = Infinity;
        for (const [ox, oy] of tries) {
          const cx = clampX(ax + ox, it.w), cy = clampY(ay + oy, it.h);
          const cost = overlap(cx, cy, it.w, it.h);
          if (cost === 0) { best = [cx, cy]; break; }
          if (cost < bestCost) { bestCost = cost; best = [cx, cy]; }  // no free spot: the least covered one
        }
        [x, y] = best;
      }
      l.off = x === ax && y === ay ? null : [x - ax, y - ay];
      placed.push({ x, y, w: it.w, h: it.h });
      l.el.style.left = `${x}px`;
      l.el.style.top = `${y}px`;
      const len = Math.hypot(x - ax, y - ay);
      if (len > it.h * 0.6) {
        if (!l.lead) { l.lead = document.createElement('div'); l.lead.className = 'mlead'; this.labelLayer.prepend(l.lead); }
        Object.assign(l.lead.style, { display: '', left: `${ax}px`, top: `${ay}px`, width: `${len}px`,
          transform: `rotate(${Math.atan2(y - ay, x - ax)}rad)` });
      } else if (l.lead) l.lead.style.display = 'none';
    }
  }

  // What labels keep clear of, as centre / size boxes in viewport pixels
  _labelObstacles() {
    const out = [];
    const c = this.canvas.getBoundingClientRect();
    const add = (r) => {
      const x0 = Math.max(r.left, c.left), x1 = Math.min(r.right, c.right), y0 = Math.max(r.top, c.top), y1 = Math.min(r.bottom, c.bottom);
      if (x1 > x0 && y1 > y0) out.push({ x: (x0 + x1) / 2 - c.left, y: (y0 + y1) / 2 - c.top, w: x1 - x0, h: y1 - y0 });
    };
    const hud = this.container.querySelector('.hud');
    if (hud && hud.offsetWidth) add(hud.getBoundingClientRect());
    for (const d of document.querySelectorAll('.dialog')) if (d.offsetWidth) add(d.getBoundingClientRect());  // tool windows over the view
    const box = (r) => out.push({ x: r.x + r.w / 2, y: r.y + r.h / 2, w: r.w, h: r.h });
    box(this.cube.triRect(this.height));
    if (this.showCube) box(this.cube.rect(this.width));
    return out;
  }

  // Align Part: arrows from `origin` along each of `axes` (unit [x, y, z]s) in `colors`, labelled
  showAxesPreview(origin, axes, colors, labels) {
    this.clearAxesPreview();
    if (!origin) return;
    const o = new THREE.Vector3(...origin), len = this.rig.radius * 0.45;
    axes.forEach((d, i) => {
      const dir = new THREE.Vector3(...d).normalize(), tip = o.clone().addScaledVector(dir, len);
      this._fatLine([...o.toArray(), ...tip.toArray()], colors[i], 3, { group: this.preview, depthTest: false, noClip: true, order: 32 });
      const head = new THREE.Mesh(new THREE.ConeGeometry(len * 0.06, len * 0.18, 18),
        new THREE.MeshBasicMaterial({ color: colors[i], depthTest: false, toneMapped: false }));
      head.position.copy(tip);
      head.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
      head.renderOrder = 33;
      this.preview.add(head);
      const el = this.addLabel(o.clone().addScaledVector(dir, len * 1.22), labels[i], `axis ${'xyz'[i]}`);
      this.labels[this.labels.length - 1].preview = true;
      void el;
    });
    const dot = this.annotDots([origin], 0x14265a, 8);
    this.annot.remove(dot);
    this.preview.add(dot);
    this.requestRender();
  }

  // Align Part's pick arrows: [{at, dir, color, widget (an element shown by the arrow's tip)}], plus
  // thin `ghosts` [{at, dir, color, label}] for the axes that follow from them
  showPickArrows(arrows, ghosts = []) {
    this.clearAxesPreview();
    const len = this.rig.radius * 0.4;
    const arrow = (at, d, color, width, scale) => {
      const o = new THREE.Vector3(...at), dir = new THREE.Vector3(...d).normalize(), tip = o.clone().addScaledVector(dir, len * scale);
      this._fatLine([...o.toArray(), ...tip.toArray()], color, width, { group: this.preview, depthTest: false, noClip: true, order: 32 });
      const head = new THREE.Mesh(new THREE.ConeGeometry(len * 0.055 * scale, len * 0.17 * scale, 18),
        new THREE.MeshBasicMaterial({ color, depthTest: false, toneMapped: false }));
      head.position.copy(tip);
      head.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
      head.renderOrder = 33;
      this.preview.add(head);
      return { o, dir };
    };
    for (const a of arrows) {
      if (!a.at || !a.dir) continue;
      const { o, dir } = arrow(a.at, a.dir, a.color, a.width ?? 3.5, 1);
      const el = this.addLabel(o.clone().addScaledVector(dir, len * 1.25), '', 'pickbar');
      el.append(a.widget);
      this.labels[this.labels.length - 1].preview = true;
    }
    if (arrows[0]?.at) {
      const dot = this.annotDots([arrows[0].at], 0x14265a, 9);
      this.annot.remove(dot);
      this.preview.add(dot);
    }
    for (const g of ghosts) {
      const { o, dir } = arrow(g.at, g.dir, g.color, 2, 0.7);
      this.addLabel(o.clone().addScaledVector(dir, len * 0.85), g.label, `axis ghost ${g.cls}`);
      this.labels[this.labels.length - 1].preview = true;
    }
    this.requestRender();
  }

  clearAxesPreview() {
    this.preview.traverse((o) => { if (o.geometry) o.geometry.dispose(); });
    this.preview.clear();
    this.labels = this.labels.filter((l) => { if (l.preview) { l.el.remove(); l.lead?.remove(); return false; } return true; });
    this.requestRender();
  }

  annotLine(p1, p2, color, width = 2, opts = {}) {
    return this._fatLine([...p1, ...p2], color, width, { group: this.annot, depthTest: false, noClip: true, order: 30, ...opts });
  }

  annotDots(points, color, size = 6) {
    const mat = dotMaterial({ size, color, depthTest: false });
    mat.uniforms.resolution.value.set(this.width, this.height);
    const d = new THREE.Mesh(dotGeometry(points.flat()), mat);
    d.frustumCulled = false;
    d.renderOrder = 31;
    this.annot.add(d);
    return d;
  }

  // ================================================================== picture
  screenshot(scale = 2) {
    const r = this.renderer;
    const prev = r.getPixelRatio();
    const k = prev * scale;
    r.setPixelRatio(k);
    r.setSize(this.width, this.height, false);
    this.render();
    const out = document.createElement('canvas');
    out.width = this.canvas.width;
    out.height = this.canvas.height;
    const g = out.getContext('2d');
    g.drawImage(this.canvas, 0, 0);
    const box = this.container.getBoundingClientRect();
    for (const l of this.labels) {
      if (l.el.style.display === 'none') continue;
      const rc = l.el.getBoundingClientRect();
      const cs = getComputedStyle(l.el);
      const x = (rc.left - box.left) * k, y = (rc.top - box.top) * k, w = rc.width * k, hh = rc.height * k;
      g.fillStyle = cs.backgroundColor;
      g.strokeStyle = cs.borderTopColor;
      g.lineWidth = Math.max(1, k);
      g.beginPath();
      g.roundRect(x, y, w, hh, 2 * k);
      g.fill();
      g.stroke();
      g.fillStyle = cs.color;
      g.font = `${cs.fontWeight} ${parseFloat(cs.fontSize) * k}px ${cs.fontFamily}`;
      g.textAlign = 'center';
      g.textBaseline = 'middle';
      g.fillText(l.el.textContent, x + w / 2, y + hh / 2 + k * 0.5);
    }
    const url = out.toDataURL('image/png');
    r.setPixelRatio(prev);
    r.setSize(this.width, this.height, false);
    this.requestRender();
    return url;
  }

  // ================================================================== input
  _local(e) { const r = this.canvas.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }

  _bindInput() {
    const c = this.canvas;
    const pivotDot = this.container.querySelector('#pivot-dot');
    const rubber = this.container.querySelector('#rubber');
    const gestureEl = this.container.querySelector('#gesture');
    let drag = null, hoverBusy = false, hoverQueued = false, lastMove = null, lastMiddleUp = 0;

    const modeFor = (e) => {
      const sw = this.mouseMode === 'sw';
      if (e.button === 1) return e.ctrlKey ? 'pan' : e.shiftKey ? 'zoom' : e.altKey ? 'roll' : 'rotate';
      if (e.button === 2) return sw ? 'gesture' : 'pan';
      if (e.button === 0) {
        if (this.mode === 'zoomArea') return 'area';
        if (sw) return e.altKey ? (e.ctrlKey ? 'pan' : 'rotate') : 'box';
        return e.ctrlKey && e.shiftKey ? 'pan' : e.shiftKey ? 'zoom' : 'rotate';
      }
      return 'rotate';
    };

    const start = (d) => {
      d.mode = modeFor(d.e);
      if (d.mode === 'rotate') {
        this.rig.anim = null;
        // SolidWorks turns about the model's centre, or about the entity last middle-clicked;
        // the other mouse scheme turns about the point under the cursor
        const sw = this.mouseMode === 'sw';
        const pt = !this.model ? null : sw ? (this.rotCenter?.point || this.visibleBox().getCenter(new THREE.Vector3())) : this.pointAt(d.x0, d.y0);
        d.pivot = pt || this.rig.target.clone();
        d.axis = sw ? this.rotCenter?.axis : null;
        if (pt) { const s = this.project(pt); Object.assign(pivotDot.style, { left: `${s.x}px`, top: `${s.y}px`, display: 'block' }); }
      }
      if (d.mode === 'pan') this.container.classList.add('cursor-pan');
      if (d.mode === 'gesture') this._gestureShow(gestureEl, d.x0, d.y0);
      if (d.mode !== 'box' && d.mode !== 'area' && d.mode !== 'gesture') this.rig.pushHistory();
    };

    c.addEventListener('contextmenu', (e) => e.preventDefault());
    c.addEventListener('pointerdown', (e) => {
      c.focus({ preventScroll: true });
      const p = this._local(e);
      if (this.selectorOn && e.button === 0) {
        const hit = this._selectorHit(p.x, p.y);
        if (hit) { this.onSelectorPick(hit.dir); return; }
      }
      if (e.button === 0 && this.showCube && this.cube.contains(p.x, p.y, this.width)) {
        const hit = this.cube.pick(p.x, p.y, this.width);
        if (hit) this.viewAlong(hit.dir, true);
        return;
      }
      if (e.button === 0) {
        const axis = this.cube.pickTriad(p.x, p.y, this.height);
        if (axis) {
          const d = new THREE.Vector3(axis === 'x' ? 1 : 0, axis === 'y' ? 1 : 0, axis === 'z' ? 1 : 0);
          if (this.rig.dir().dot(d) > 0.999) d.negate();
          this.viewAlong(d, false);
          return;
        }
      }
      c.setPointerCapture(e.pointerId);
      drag = { button: e.button, x0: p.x, y0: p.y, x: p.x, y: p.y, moved: false, e };
      if (e.button === 1) e.preventDefault();
    });

    c.addEventListener('pointermove', (e) => {
      const p = this._local(e);
      this.lastPointer = p;
      if (drag) {
        const dx = p.x - drag.x, dy = p.y - drag.y;
        if (!drag.moved && Math.hypot(p.x - drag.x0, p.y - drag.y0) > 3) {
          drag.moved = true;
          start(drag);
          this.setHover(null);
          this.onHover(null);
        }
        if (drag.moved) {
          const m = drag.mode;
          if (m === 'rotate' && drag.axis) this.rig.rotateAbout(drag.axis, drag.pivot, dx, dy);
          else if (m === 'rotate') this.rig.rotate(dx, dy, drag.pivot);
          else if (m === 'pan') this.rig.pan(dx, dy, this.height);
          else if (m === 'roll') this.rig.roll(-dx * 0.008);
          else if (m === 'zoom') this.rig.zoomAt(Math.exp(dy * 0.006), (drag.x0 / this.width) * 2 - 1, -(drag.y0 / this.height) * 2 + 1);
          else if (m === 'area' || m === 'box') {
            const x = Math.min(p.x, drag.x0), y = Math.min(p.y, drag.y0);
            Object.assign(rubber.style, { display: 'block', left: `${x}px`, top: `${y}px`, width: `${Math.abs(p.x - drag.x0)}px`, height: `${Math.abs(p.y - drag.y0)}px` });
            rubber.classList.toggle('crossing', m === 'box' && p.x < drag.x0);
          } else if (m === 'gesture') this._gestureTrack(gestureEl, p.x - drag.x0, p.y - drag.y0);
          if (m === 'rotate' && drag.pivot) { const s = this.project(drag.pivot); pivotDot.style.left = `${s.x}px`; pivotDot.style.top = `${s.y}px`; }
        }
        drag.x = p.x; drag.y = p.y;
        return;
      }
      lastMove = p;
      if (this.selectorOn) { this._selectorHover(this._selectorHit(p.x, p.y)); return; }
      if (this.showCube && this.cube.contains(p.x, p.y, this.width)) {
        if (this.cube.setHover(this.cube.pick(p.x, p.y, this.width))) this.requestRender();
        this.setHover(null);
        this.onHover(null);
        return;
      } else if (this.cube.setHover(null)) this.requestRender();
      if (!hoverQueued) {
        hoverQueued = true;
        requestAnimationFrame(async () => {
          hoverQueued = false;
          if (drag || !lastMove || !this.model || hoverBusy) return;
          hoverBusy = true;
          const at = lastMove;
          try {
            const hit = await this.pickAsync(at.x, at.y);
            if (!drag) this.onHover(hit, at);
          } finally { hoverBusy = false; }
        });
      }
    });

    const end = (e) => {
      if (!drag) return;
      const p = this._local(e);
      const d = drag;
      drag = null;
      pivotDot.style.display = 'none';
      this.container.classList.remove('cursor-pan');
      try { c.releasePointerCapture(e.pointerId); } catch { /* released */ }
      if (d.mode === 'area' && d.moved) {
        rubber.style.display = 'none';
        this._zoomToRect(Math.min(p.x, d.x0), Math.min(p.y, d.y0), Math.abs(p.x - d.x0), Math.abs(p.y - d.y0));
        this.onModeDone?.('zoomArea');
        return;
      }
      if (d.mode === 'box' && d.moved) {
        rubber.style.display = 'none';
        const ents = this._boxSelect(Math.min(p.x, d.x0), Math.min(p.y, d.y0), Math.max(p.x, d.x0), Math.max(p.y, d.y0), p.x < d.x0);
        this.onBoxSelect(ents, d.e.ctrlKey || d.e.shiftKey);
        return;
      }
      if (d.mode === 'gesture' && d.moved) {
        const cmd = this._gestureEnd(gestureEl, p.x - d.x0, p.y - d.y0);
        if (cmd) this.onGesture(cmd);
        return;
      }
      if (d.moved) return;
      if (d.button === 0) this.onClick(this.model ? this.pick(p.x, p.y) : null, e, p);
      if (d.button === 2) this.onContext(this.model ? this.pick(p.x, p.y) : null, e, p);
      if (d.button === 1) {
        const now = performance.now();
        if (now - lastMiddleUp < 350) this.fitAll(true);
        else this.setRotationCenter(this.model ? this.pick(p.x, p.y) : null);
        lastMiddleUp = now;
      }
    };
    c.addEventListener('pointerup', end);
    c.addEventListener('pointercancel', end);
    c.addEventListener('pointerleave', () => { if (!drag) { this.setHover(null); this.onHover(null); if (this.cube.setHover(null)) this.requestRender(); } });
    c.addEventListener('dblclick', (e) => {
      const p = this._local(e);
      if (this.showCube && this.cube.contains(p.x, p.y, this.width)) return;
      this.onDoubleClick?.(this.model ? this.pick(p.x, p.y) : null, e);
    });
    c.addEventListener('wheel', (e) => {
      e.preventDefault();
      const p = this._local(e);
      // SolidWorks: rolling the wheel away from you zooms out, toward you zooms in
      const step = -(e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY) * (this.wheelReverse ? -1 : 1);
      this.rig.anim = null;
      this.rig.zoomAt(Math.exp(step * (e.shiftKey ? 0.0006 : 0.0016)), (p.x / this.width) * 2 - 1, -(p.y / this.height) * 2 + 1);
    }, { passive: false });
  }

  _zoomToRect(x, y, w, h) {
    if (w < 6 || h < 6) return;
    const cx = ((x + w / 2) / this.width) * 2 - 1, cy = -(((y + h / 2) / this.height) * 2 - 1);
    const hh = this.rig.height / 2, hw = hh * this.rig.aspect;
    const target = this.rig.target.clone().addScaledVector(this.rig.rightVec(), cx * hw).addScaledVector(this.rig.upVec(), cy * hh);
    this.rig.animateTo({ target, height: Math.max(h / this.height, w / this.width) * this.rig.height });
  }

  // window (left to right: fully inside) or crossing (right to left: touching) selection of edges and vertices
  _boxSelect(x0, y0, x1, y1, crossing) {
    if (!this.model || x1 - x0 < 3 || y1 - y0 < 3) return [];
    const out = [];
    const E = this.model.meta.edges;
    const v = new THREE.Vector3();
    const inside = (px, py) => px >= x0 && px <= x1 && py >= y0 && py <= y1;
    for (const [b, eo] of this.edgeObjs || []) {
      if (!this.bodies[b]?.visible) continue;
      for (const e of eo.edges) {
        const s0 = E.sstart[e], sn = E.scount[e];
        let any = false, all = true;
        for (let i = s0 * 2; i < (s0 + sn) * 2; i++) {
          v.set(this.model.segs[i * 3], this.model.segs[i * 3 + 1], this.model.segs[i * 3 + 2]);
          if (this.clipPlanes.some((pl) => pl.distanceToPoint(v) < 0)) { all = false; continue; }
          const s = this.project(v);
          const inn = inside(s.x, s.y);
          any = any || inn;
          all = all && inn;
          if (crossing && any) break;
          if (!crossing && !all) break;
        }
        if (crossing ? any : all) out.push({ kind: 'edge', index: e });
      }
    }
    return out;
  }

  _gestureShow(el, x, y) {
    el.replaceChildren(Object.assign(document.createElement('div'), { className: 'g-ring' }), ...GESTURES.map((g) => {
      const it = document.createElement('div');
      it.className = 'g-item';
      it.dataset.dir = g.dir;
      const rad = THREE.MathUtils.degToRad(g.ang);
      it.style.left = `${95 + Math.cos(rad) * 68}px`;
      it.style.top = `${95 + Math.sin(rad) * 68}px`;
      it.innerHTML = `${tool(g.icon).replace('<svg', '<svg width="18" height="18"')}<span>${g.label}</span>`;
      return it;
    }));
    el.style.left = `${x}px`;
    el.style.top = `${y}px`;
    el.classList.add('show');
  }

  _gestureDir(dx, dy) {
    if (Math.hypot(dx, dy) < 28) return null;
    const ang = THREE.MathUtils.radToDeg(Math.atan2(dy, dx));
    let best = null, bestD = 999;
    for (const g of GESTURES) {
      let d = Math.abs(((ang - g.ang + 540) % 360) - 180);
      if (d < bestD) { bestD = d; best = g; }
    }
    return best;
  }

  _gestureTrack(el, dx, dy) {
    const g = this._gestureDir(dx, dy);
    el.querySelectorAll('.g-item').forEach((it) => it.classList.toggle('hot', !!g && it.dataset.dir === g.dir));
  }

  _gestureEnd(el, dx, dy) {
    el.classList.remove('show');
    const g = this._gestureDir(dx, dy);
    return g ? g.cmd : null;
  }
}
