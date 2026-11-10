// Icons. Two families, both drawn for this app:
//  - glyphs: single-color line icons for small UI chrome (currentColor)
//  - tools:  colorful two-tone icons for commands, the CommandManager and the FeatureManager tree
const G = (body, extra = '') =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" ${extra}>${body}</svg>`;
const T = (body) => `<svg viewBox="0 0 32 32" stroke-linejoin="round" stroke-linecap="round">${body}</svg>`;

// palette for the colorful set
const K = '#34425c'; // outline
const NV = '#213367'; // Wagner navy
const B1 = '#7fa9e3'; // blue
const B2 = '#c4d8f5'; // light blue
const Y = '#f3b63f'; // amber
const Y2 = '#fbe2a6';
const GR = '#3aa856';
const RD = '#d9473f';
const M1 = '#cfd5de'; // metal light
const M2 = '#9da6b4'; // metal mid
const M3 = '#6e7888'; // metal dark
const PU = '#8a59c4';

// an isometric block with shaded faces; faces: [top, left, right] colors
const block = (x, y, s, top = M1, left = M2, right = '#b9c0cb', stroke = K) => {
  const t = `${x},${y} ${x + s},${y + s * 0.55} ${x},${y + s * 1.1} ${x - s},${y + s * 0.55}`;
  const l = `${x - s},${y + s * 0.55} ${x},${y + s * 1.1} ${x},${y + s * 2.1} ${x - s},${y + s * 1.55}`;
  const r = `${x},${y + s * 1.1} ${x + s},${y + s * 0.55} ${x + s},${y + s * 1.55} ${x},${y + s * 2.1}`;
  return `<polygon points="${t}" fill="${top}" stroke="${stroke}" stroke-width="1.2"/><polygon points="${l}" fill="${left}" stroke="${stroke}" stroke-width="1.2"/><polygon points="${r}" fill="${right}" stroke="${stroke}" stroke-width="1.2"/>`;
};
const viewCube = (face) => {
  const c = { top: M1, left: '#aab2bf', right: '#c3c9d3' };
  if (face) c[face] = B1;
  return T(block(16, 4, 11, c.top, c.left, c.right));
};
const hiddenFace = (pts) => `<polygon points="${pts}" fill="${B1}" fill-opacity=".55" stroke="${NV}" stroke-width="1" stroke-dasharray="2 1.5"/>`;

const GLYPHS = {
  search: G('<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>'),
  help: G('<circle cx="12" cy="12" r="9"/><path d="M9.6 9.4a2.5 2.5 0 0 1 4.8.9c0 1.7-2.4 2.1-2.4 3.7"/><circle cx="12" cy="17" r=".6" fill="currentColor"/>'),
  open: G('<path d="M3 7.5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M3 10h18"/>'),
  close: G('<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>'),
  check: G('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 'stroke-width="2.6"'),
  cancel: G('<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>', 'stroke-width="2.6"'),
  eye: G('<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>'),
  eyeOff: G('<path d="M10.2 5.7A10 10 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-2.6 3.4M6.6 6.9C4 8.6 2.5 12 2.5 12S6 18.5 12 18.5c1.8 0 3.4-.6 4.7-1.4"/><path d="M3.5 3.5l17 17"/>'),
  chevronLeft: G('<path d="M14.5 6l-6 6 6 6"/>'),
  chevronRight: G('<path d="M9.5 6l6 6-6 6"/>'),
  chevronDown: G('<path d="M6 9.5l6 6 6-6"/>'),
  warn: G('<path d="M10.3 4.3L2.6 17.6A2 2 0 0 0 4.3 20.6h15.4a2 2 0 0 0 1.7-3L13.7 4.3a2 2 0 0 0-3.4 0z"/><path d="M12 9.5v4"/><circle cx="12" cy="16.8" r=".6" fill="currentColor"/>'),
  info: G('<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/><circle cx="12" cy="7.8" r=".6" fill="currentColor"/>'),
  copy: G('<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7.5a2 2 0 0 0 2 2h2.5"/>'),
  trash: G('<path d="M4.5 7h15M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4.5h6V7"/>'),
  triUp: G('<path d="M12 7.5l5 8H7z" fill="currentColor" stroke-width="1.2"/>'),
  triDown: G('<path d="M12 16.5l5-8H7z" fill="currentColor" stroke-width="1.2"/>'),
  triLeft: G('<path d="M7.5 12l8-5v10z" fill="currentColor" stroke-width="1.2"/>'),
  triRight: G('<path d="M16.5 12l-8-5v10z" fill="currentColor" stroke-width="1.2"/>'),
  rotateLeft: G('<path d="M8 4.5L4.5 8 8 11.5"/><path d="M4.5 8H14a5.5 5.5 0 0 1 0 11H9"/>'),
  rotateRight: G('<path d="M16 4.5L19.5 8 16 11.5"/><path d="M19.5 8H10a5.5 5.5 0 0 0 0 11h5"/>'),
  home: G('<path d="M4 11l8-6.5 8 6.5"/><path d="M6 9.5V19h12V9.5"/><path d="M10 19v-5h4v5"/>'),
  pin: G('<path d="M9 4h6l-1 5 3 3H7l3-3z"/><path d="M12 12v8"/>'),
  folder: G('<path d="M3 7.5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'),
  up: G('<path d="M12 19V5M6 11l6-6 6 6"/>'),
  refresh: G('<path d="M20 11a8 8 0 0 0-14.3-4.9L4 8"/><path d="M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.3 4.9L20 16"/><path d="M20 20v-4h-4"/>'),
  plus: G('<path d="M12 5v14M5 12h14"/>'),
  filter: G('<path d="M4 5h16l-6 7.5V19l-4 1v-7.5z"/>'),
  theme: G('<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5a8.5 8.5 0 0 1 0 17z" fill="currentColor"/>'),
  monitor: G('<rect x="3" y="4.5" width="18" height="12" rx="1.5"/><path d="M9 20h6M12 16.5V20"/>'),
};

const TOOLS = {
  // ---- files & app
  open: T(`<path d="M3 9.5a2 2 0 0 1 2-2h6l2.5 2.5H26a2 2 0 0 1 2 2V25a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" fill="${Y}" stroke="#a8761a" stroke-width="1.2"/><path d="M3 14h25" stroke="#a8761a" stroke-width="1.2"/><path d="M15.5 23.5v-7.5M12 19.5l3.5-3.5 3.5 3.5" stroke="${NV}" stroke-width="2.2" fill="none"/>`),
  reload: T(`<path d="M25 13.5A9.5 9.5 0 0 0 8.2 9.3L6 11.5" fill="none" stroke="${GR}" stroke-width="2.8"/><path d="M5.5 5.5v6.5H12" fill="none" stroke="${GR}" stroke-width="2.8"/><path d="M7 18.5a9.5 9.5 0 0 0 16.8 4.2l2.2-2.2" fill="none" stroke="${NV}" stroke-width="2.8"/><path d="M26.5 26.5V20H20" fill="none" stroke="${NV}" stroke-width="2.8"/>`),
  print: T(`<path d="M9 5h11l3 3v5H9z" fill="#fff" stroke="${K}" stroke-width="1.3"/><rect x="4" y="12" width="24" height="10" rx="2" fill="${M1}" stroke="${K}" stroke-width="1.3"/><path d="M9 18h14v9H9z" fill="#fff" stroke="${K}" stroke-width="1.3"/><path d="M11.5 21.5h9M11.5 24h6" stroke="${NV}" stroke-width="1.4"/><circle cx="24" cy="15.5" r="1.2" fill="${B1}" stroke="${NV}" stroke-width=".8"/>`),
  camera: T(`<path d="M4 11.5A2.5 2.5 0 0 1 6.5 9h3.2l2.1-3h8.4l2.1 3h3.2a2.5 2.5 0 0 1 2.5 2.5v12A2.5 2.5 0 0 1 25.5 26h-19A2.5 2.5 0 0 1 4 23.5z" fill="${M1}" stroke="${K}" stroke-width="1.3"/><circle cx="16" cy="17" r="5.4" fill="${B1}" stroke="${NV}" stroke-width="1.4"/><circle cx="14.4" cy="15.4" r="1.5" fill="#fff" opacity=".8"/>`),
  options: T(`<path d="M16 5.5l2 .4.7 2.6 2.3 1 2.3-1.4 2.6 2.6-1.4 2.3 1 2.3 2.6.7v3.6l-2.6.7-1 2.3 1.4 2.3-2.6 2.6-2.3-1.4-2.3 1-.7 2.6h-3.6l-.7-2.6-2.3-1-2.3 1.4-2.6-2.6 1.4-2.3-1-2.3-2.6-.7v-3.6l2.6-.7 1-2.3-1.4-2.3 2.6-2.6 2.3 1.4 2.3-1 .7-2.6z" fill="${M2}" stroke="${K}" stroke-width="1.1"/><circle cx="16" cy="16" r="4.2" fill="#fff" stroke="${K}" stroke-width="1.3"/>`),
  select: T(`<path d="M8 4l15 12.5-6.8 1.2 4.3 8.2-3.3 1.7-4.3-8.3L8 24z" fill="#fff" stroke="${K}" stroke-width="1.5"/>`),
  close: T(`<rect x="5" y="5" width="22" height="22" rx="3" fill="${M1}" stroke="${K}" stroke-width="1.2"/><path d="M11 11l10 10M21 11L11 21" stroke="${RD}" stroke-width="2.6"/>`),
  props: T(`<rect x="6" y="4" width="20" height="24" rx="2" fill="#fff" stroke="${K}" stroke-width="1.3"/><path d="M10 10h12M10 14.5h12M10 19h8" stroke="${B1}" stroke-width="2"/><path d="M10 23.5h5" stroke="${Y}" stroke-width="2"/>`),
  // ---- view
  zoomFit: T(`<path d="M4 11V5h6M22 5h6v6M28 21v6h-6M10 27H4v-6" fill="none" stroke="${NV}" stroke-width="2"/>${block(16, 8.5, 6.5)}`),
  zoomArea: T(`<rect x="4" y="4" width="15" height="15" fill="${B2}" fill-opacity=".6" stroke="${NV}" stroke-width="1.4" stroke-dasharray="2.5 1.8"/><circle cx="17.5" cy="17.5" r="6" fill="#fff" fill-opacity=".85" stroke="${K}" stroke-width="2"/><path d="M22 22l6 6" stroke="${K}" stroke-width="3"/>`),
  prevView: T(`${block(19, 7, 7, M1, M2, '#b9c0cb')}<path d="M13 9H7a4 4 0 0 0-4 4v1" fill="none" stroke="${NV}" stroke-width="2.2"/><path d="M10 5.5L13.5 9 10 12.5" fill="none" stroke="${NV}" stroke-width="2.2"/>`),
  sectionView: T(`${block(16, 4, 11, M1, M2, '#b9c0cb')}<polygon points="5,15 16,21 27,15 27,10 16,16 5,10" fill="${B1}" fill-opacity=".55" stroke="${NV}" stroke-width="1"/><path d="M5 12.5L16 18.5 27 12.5" stroke="${NV}" stroke-width="2.2" fill="none"/>`),
  orientation: viewCube('left'),
  displayStyle: T(block(16, 4, 11, '#d9dee6', '#7f8ba0', '#a9b3c3', '#111')),
  hideShow: T(`<path d="M3 16s5-8 13-8 13 8 13 8-5 8-13 8S3 16 3 16z" fill="#fff" stroke="${K}" stroke-width="1.4"/><circle cx="16" cy="16" r="4.6" fill="${B1}" stroke="${NV}" stroke-width="1.4"/><circle cx="16" cy="16" r="1.8" fill="${NV}"/>`),
  appearance: T(`<circle cx="16" cy="16" r="11" fill="url(#ap)" stroke="${K}" stroke-width="1.2"/><defs><radialGradient id="ap" cx=".35" cy=".3" r=".9"><stop offset="0" stop-color="#fff"/><stop offset=".35" stop-color="${Y}"/><stop offset=".7" stop-color="${RD}"/><stop offset="1" stop-color="${NV}"/></radialGradient></defs>`),
  scene: T(`<rect x="3" y="6" width="26" height="20" rx="2" fill="url(#sc)" stroke="${K}" stroke-width="1.2"/><defs><linearGradient id="sc" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#9fb2cc"/></linearGradient></defs><path d="M3 21l8-6 6 4 4-3 8 5" fill="none" stroke="${NV}" stroke-width="1.5"/><circle cx="22" cy="11" r="2.3" fill="${Y}"/>`),
  viewSettings: T(`<rect x="3" y="5" width="26" height="17" rx="2" fill="${B2}" stroke="${K}" stroke-width="1.3"/><path d="M11 27h10M16 22v5" stroke="${K}" stroke-width="1.6"/><path d="M8 18c3-6 13-6 16 0" fill="none" stroke="${NV}" stroke-width="1.6"/><circle cx="16" cy="15" r="2.4" fill="${NV}"/>`),
  perspective: T(`<path d="M3 9l10-4v22L3 23z" fill="${B2}" stroke="${K}" stroke-width="1.3"/><path d="M13 5l16 4v14l-16 4" fill="none" stroke="${K}" stroke-width="1.3"/><path d="M13 12l16 1.5M13 20l16-1.5" stroke="${B1}" stroke-width="1.3"/>`),
  normalTo: T(`<polygon points="4,12 18,6 28,12 14,18" fill="${B1}" fill-opacity=".7" stroke="${NV}" stroke-width="1.2"/><path d="M16 12v16" stroke="${RD}" stroke-width="2.4"/><path d="M12 24l4 4.5 4-4.5" fill="none" stroke="${RD}" stroke-width="2.4"/>`),
  front: viewCube('left'),
  back: T(block(16, 4, 11, M1, '#aab2bf', '#c3c9d3') + hiddenFace('16,4 27,10 27,21 16,15')),
  left: T(block(16, 4, 11, M1, '#aab2bf', '#c3c9d3') + hiddenFace('5,10 16,4 16,15 5,21')),
  right: viewCube('right'),
  top: viewCube('top'),
  bottom: T(block(16, 4, 11, M1, '#aab2bf', '#c3c9d3') + hiddenFace('5,21 16,15 27,21 16,27')),
  iso: T(block(16, 4, 11, B2, B1, '#a4c2ee')),
  dimetric: T(`<polygon points="16,5 28,9 16,13.5 4,9" fill="${B2}" stroke="${K}" stroke-width="1.2"/><polygon points="4,9 16,13.5 16,27 4,22.5" fill="${B1}" stroke="${K}" stroke-width="1.2"/><polygon points="16,13.5 28,9 28,22.5 16,27" fill="#a4c2ee" stroke="${K}" stroke-width="1.2"/>`),
  trimetric: T(`<polygon points="13,4.5 28,8.5 18,13.5 4,9.5" fill="${B2}" stroke="${K}" stroke-width="1.2"/><polygon points="4,9.5 18,13.5 18,27 4,22.5" fill="${B1}" stroke="${K}" stroke-width="1.2"/><polygon points="18,13.5 28,8.5 28,21.5 18,27" fill="#a4c2ee" stroke="${K}" stroke-width="1.2"/>`),
  stShadedEdges: T(block(16, 4, 11, '#d9dee6', '#8693a8', '#aeb8c8', '#111')),
  stShaded: T(block(16, 4, 11, '#d9dee6', '#8693a8', '#aeb8c8', 'none')),
  stHlr: T(block(16, 4, 11, '#fff', '#fff', '#fff', '#111')),
  stHlv: T(block(16, 4, 11, '#fff', '#fff', '#fff', '#111') + '<path d="M5 21L16 15 27 21M16 4v11" stroke="#8a93a1" stroke-width="1.1" stroke-dasharray="2 1.6"/>'),
  stWire: T(block(16, 4, 11, 'none', 'none', 'none', '#111') + '<path d="M5 21L16 15 27 21M16 4v11" stroke="#111" stroke-width="1.1"/>'),
  showAll: T(`<path d="M3 16s5-8 13-8 13 8 13 8-5 8-13 8S3 16 3 16z" fill="#fff" stroke="${K}" stroke-width="1.4"/><circle cx="16" cy="16" r="4.6" fill="${GR}" stroke="#23733a" stroke-width="1.4"/>`),
  hide: T(`<path d="M3 16s5-8 13-8 13 8 13 8-5 8-13 8S3 16 3 16z" fill="#fff" stroke="${K}" stroke-width="1.4"/><circle cx="16" cy="16" r="4.6" fill="${M2}" stroke="${K}" stroke-width="1.4"/><path d="M5 5l22 22" stroke="${RD}" stroke-width="2.6"/>`),
  isolate: T(`${block(16, 9, 6, Y2, Y, '#f7cc6f')}<rect x="3.5" y="3.5" width="25" height="25" rx="2" fill="none" stroke="${M2}" stroke-width="1.4" stroke-dasharray="3 2"/>`),
  transparency: T(`${block(13, 5, 8, B2, B1, '#a4c2ee')}<g opacity=".55">${block(20, 11, 8, M1, M2, '#b9c0cb')}</g>`),
  // ---- evaluate
  measure: T(`<rect x="2.5" y="11" width="27" height="10" rx="1.5" fill="${Y}" stroke="#a8761a" stroke-width="1.2" transform="rotate(-30 16 16)"/><path d="M7.5 19.2l1.5 2.6M11 17.2l2.2 3.8M14.5 15.2l1.5 2.6M18 13.2l2.2 3.8M21.5 11.2l1.5 2.6" stroke="#7a5512" stroke-width="1.2" transform="rotate(0)"/><path d="M5 27h22" stroke="${NV}" stroke-width="1.8"/><path d="M8 24.5L5 27l3 2.5M24 24.5l3 2.5-3 2.5" fill="none" stroke="${NV}" stroke-width="1.8"/>`),
  massProps: T(`<path d="M16 5v20M10 27h12" stroke="${K}" stroke-width="2"/><path d="M5 9h22" stroke="${K}" stroke-width="2"/><path d="M5 9l-3.5 8h7z M27 9l-3.5 8h7z" fill="${B2}" stroke="${K}" stroke-width="1.2"/><path d="M1.5 17a3.5 2 0 0 0 7 0M23.5 17a3.5 2 0 0 0 7 0" fill="${B1}" stroke="${K}" stroke-width="1.2"/><circle cx="16" cy="5" r="2" fill="${Y}" stroke="${K}" stroke-width="1"/>`),
  sectionProps: T(`<polygon points="3,13 17,6 29,13 15,20" fill="${B1}" fill-opacity=".75" stroke="${NV}" stroke-width="1.3"/><path d="M16 9.5v7M12.5 13h7" stroke="${PU}" stroke-width="2"/><circle cx="16" cy="13" r="1.6" fill="#fff" stroke="${PU}" stroke-width="1.2"/><path d="M3 18l12 7 14-7" fill="none" stroke="${M2}" stroke-width="1.3" stroke-dasharray="2.5 2"/>`),
  bbox: T(`${block(16, 9, 6, M1, M2, '#b9c0cb')}<path d="M16 3l11 6v14l-11 6-11-6V9z" fill="none" stroke="${Y}" stroke-width="1.6" stroke-dasharray="3 2"/>`),
  statistics: T(`<rect x="4" y="18" width="5" height="9" fill="${B1}" stroke="${NV}" stroke-width="1.1"/><rect x="11" y="11" width="5" height="16" fill="${Y}" stroke="#a8761a" stroke-width="1.1"/><rect x="18" y="6" width="5" height="21" fill="${GR}" stroke="#23733a" stroke-width="1.1"/><path d="M3 28h26" stroke="${K}" stroke-width="1.5"/>`),
  check: T(`<circle cx="13" cy="13" r="8.5" fill="#fff" stroke="${K}" stroke-width="2"/><path d="M19.5 19.5L28 28" stroke="${K}" stroke-width="3.2"/><path d="M9 13l3 3 5.5-6" fill="none" stroke="${GR}" stroke-width="2.4"/>`),
  draft: T(`<polygon points="7,27 11,7 21,7 25,27" fill="${GR}" fill-opacity=".85" stroke="${K}" stroke-width="1.2"/><polygon points="7,27 11,7 14,7 11.5,27" fill="${Y}" stroke="${K}" stroke-width="1"/><polygon points="21,7 25,27 20.5,27 18,7" fill="${RD}" fill-opacity=".85" stroke="${K}" stroke-width="1"/><path d="M16 2v4M13.5 4.5L16 2l2.5 2.5" fill="none" stroke="${NV}" stroke-width="1.8"/>`),
  zebra: T(`<defs><clipPath id="zc"><circle cx="16" cy="16" r="11.5"/></clipPath></defs><circle cx="16" cy="16" r="11.5" fill="#fff"/><g clip-path="url(#zc)" fill="#1b2231"><path d="M2 8 C10 4 22 4 30 8 V11 C22 7 10 7 2 11Z"/><path d="M2 15 C10 11 22 11 30 15 V18 C22 14 10 14 2 18Z"/><path d="M2 22 C10 18 22 18 30 22 V25 C22 21 10 21 2 25Z"/></g><circle cx="16" cy="16" r="11.5" fill="none" stroke="${K}" stroke-width="1.3"/>`),
  curvature: T(`<defs><linearGradient id="cv" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#2c63d6"/><stop offset=".35" stop-color="#3aa856"/><stop offset=".65" stop-color="#f3b63f"/><stop offset="1" stop-color="#d9473f"/></linearGradient></defs><path d="M3 24 C8 8 14 6 18 14 S26 22 29 8 V26 H3Z" fill="url(#cv)" stroke="${K}" stroke-width="1.2"/>`),
  holes: T(`${block(16, 5, 11, M1, M2, '#b9c0cb')}<ellipse cx="11" cy="10.2" rx="2.6" ry="1.4" fill="${K}"/><ellipse cx="16" cy="12.9" rx="2.6" ry="1.4" fill="${K}"/><ellipse cx="21" cy="10.2" rx="2.6" ry="1.4" fill="${K}"/><path d="M16 15v10" stroke="${Y}" stroke-width="1.4" stroke-dasharray="2 1.5"/>`),
  stock: T(`${block(16, 7, 9, '#e7d3b5', '#b8946a', '#cfae86', '#6b4f2c')}<path d="M3 27h14M3 25v4M17 25v4" stroke="${NV}" stroke-width="1.4"/><path d="M29 7v14M27 7h4M27 21h4" stroke="${NV}" stroke-width="1.4"/>`),
  quote: T(`<rect x="6" y="5" width="20" height="24" rx="2" fill="#fff" stroke="${K}" stroke-width="1.3"/><rect x="11" y="3" width="10" height="5" rx="1.5" fill="${M2}" stroke="${K}" stroke-width="1.1"/><path d="M10 13h8M10 17.5h6M10 22h7" stroke="${M2}" stroke-width="1.6"/><circle cx="22" cy="21" r="5" fill="${GR}" stroke="#23733a" stroke-width="1.1"/><path d="M22 18v6M20.5 19.5c0-1 3-1 3 0s-3 1-3 2 3 1 3 0" fill="none" stroke="#fff" stroke-width="1.2"/>`),
  centerMass: T(`<circle cx="16" cy="16" r="10" fill="#fff" stroke="${PU}" stroke-width="1.8"/><path d="M16 6a10 10 0 0 1 10 10H16zM16 26A10 10 0 0 1 6 16h10z" fill="${PU}"/>`),
  // ---- feature tree
  part: T(`${block(16, 4, 11, '#f5d48a', '#d79a2b', '#e9b552', '#7a5512')}`),
  assembly: T(`${block(11, 3, 7, '#f5d48a', '#d79a2b', '#e9b552', '#7a5512')}${block(21, 11, 7, B2, B1, '#a4c2ee')}`),
  body: T(block(16, 5, 10, M1, M2, '#b9c0cb')),
  bodyFolder: T(`<path d="M3 9a2 2 0 0 1 2-2h6l2.5 2.5H26a2 2 0 0 1 2 2V25a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" fill="${Y}" stroke="#a8761a" stroke-width="1.2"/>${block(18, 13, 5, M1, M2, '#b9c0cb')}`),
  surfaceBody: T(`<path d="M4 20 C8 10 13 8 16 13 S24 20 28 9 L28 22 C24 30 18 26 16 24 S8 22 4 28Z" fill="${B2}" stroke="${NV}" stroke-width="1.3"/>`),
  meshBody: T(`<path d="M4 25L16 5l12 20z" fill="${B2}" stroke="${NV}" stroke-width="1.3"/><path d="M10 15h12M16 5l-6 20M16 5l6 20M10 15l6 10 6-10" fill="none" stroke="${NV}" stroke-width="1"/>`),
  layer: T(`<path d="M16 17L3 11l13-6 13 6z" fill="${B2}" stroke="${NV}" stroke-width="1.2"/><path d="M3 16l13 6 13-6M3 21l13 6 13-6" fill="none" stroke="${NV}" stroke-width="1.2"/>`), // a drawing's layer
  material: T(`<path d="M6 6h20v4h-7v12h7v4H6v-4h7V10H6z" fill="url(#mt)" stroke="${K}" stroke-width="1.2"/><defs><pattern id="mt" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="4" height="4" fill="${M1}"/><rect width="1.5" height="4" fill="${M2}"/></pattern></defs>`),
  plane: T(`<polygon points="3,20 12,8 29,12 20,24" fill="${B2}" fill-opacity=".85" stroke="${NV}" stroke-width="1.3"/>`),
  origin: T(`<path d="M8 24V7" stroke="${GR}" stroke-width="2"/><path d="M8 24h17" stroke="${RD}" stroke-width="2"/><path d="M8 24l-5 5" stroke="${B1}" stroke-width="2"/><path d="M5 10l3-4 3 4M22 21l4 3-4 3" fill="none" stroke="${K}" stroke-width="1.4"/><circle cx="8" cy="24" r="2" fill="${K}"/>`),
  history: T(`<circle cx="16" cy="16" r="11" fill="#fff" stroke="${K}" stroke-width="1.4"/><path d="M16 9v7l5 3" fill="none" stroke="${NV}" stroke-width="2"/>`),
  annotations: T(`<rect x="4" y="5" width="24" height="20" rx="2" fill="${Y2}" stroke="#a8761a" stroke-width="1.2"/><path d="M10 21l6-12 6 12M12.3 16.5h7.4" fill="none" stroke="${K}" stroke-width="1.8"/>`),
  imported: T(`${block(18, 7, 9, M1, M2, '#b9c0cb')}<path d="M3 6h7M7 3l3 3-3 3" fill="none" stroke="${GR}" stroke-width="2"/>`),
  component: T(`${block(16, 4, 11, '#f5d48a', '#d79a2b', '#e9b552', '#7a5512')}`),
  subassembly: T(`${block(11, 3, 7, '#f5d48a', '#d79a2b', '#e9b552', '#7a5512')}${block(21, 11, 7, '#f5d48a', '#d79a2b', '#e9b552', '#7a5512')}`),
  face: T(`<polygon points="4,12 16,6 28,12 16,18" fill="${B1}" stroke="${NV}" stroke-width="1.2"/><path d="M4 12v10l12 6 12-6V12" fill="none" stroke="${M2}" stroke-width="1.2"/>`),
  edge: T(`<path d="M4 12l12-6 12 6-12 6zM4 12v10l12 6 12-6V12" fill="none" stroke="${M2}" stroke-width="1.2"/><path d="M16 18v10" stroke="${NV}" stroke-width="2.8"/>`),
  vertex: T(`<path d="M4 12l12-6 12 6-12 6zM4 12v10l12 6 12-6V12" fill="none" stroke="${M2}" stroke-width="1.2"/><circle cx="16" cy="18" r="3" fill="${NV}"/>`),
  point: T(`<circle cx="16" cy="16" r="3" fill="${PU}"/><path d="M16 5v6M16 21v6M5 16h6M21 16h6" stroke="${PU}" stroke-width="1.8"/>`),
  displayMgr: T(`<circle cx="12" cy="13" r="7.5" fill="${Y}" stroke="${K}" stroke-width="1.2"/><circle cx="20" cy="13" r="7.5" fill="${B1}" fill-opacity=".85" stroke="${K}" stroke-width="1.2"/><circle cx="16" cy="20" r="7.5" fill="${RD}" fill-opacity=".75" stroke="${K}" stroke-width="1.2"/>`),
  featureMgr: T(`<rect x="4" y="4" width="8" height="6" rx="1" fill="${Y}" stroke="${K}" stroke-width="1.1"/><rect x="14" y="13" width="14" height="5" rx="1" fill="${B1}" stroke="${K}" stroke-width="1.1"/><rect x="14" y="21" width="14" height="5" rx="1" fill="${M1}" stroke="${K}" stroke-width="1.1"/><path d="M8 10v13.5h6M8 15.5h6" fill="none" stroke="${K}" stroke-width="1.3"/>`),
  propertyMgr: T(`<rect x="5" y="4" width="22" height="24" rx="2" fill="#fff" stroke="${K}" stroke-width="1.3"/><path d="M9 10h14" stroke="${NV}" stroke-width="2"/><rect x="9" y="14" width="14" height="4" fill="${B2}" stroke="${NV}" stroke-width="1"/><rect x="9" y="21" width="9" height="4" fill="${B2}" stroke="${NV}" stroke-width="1"/>`),
  // ---- task pane
  tpHome: T(`<path d="M4 15L16 5l12 10" fill="none" stroke="${NV}" stroke-width="2.2"/><path d="M7 13v14h18V13" fill="${B2}" stroke="${NV}" stroke-width="1.6"/><rect x="13" y="18" width="6" height="9" fill="${Y}" stroke="${K}" stroke-width="1.1"/>`),
  tpExplorer: T(`<path d="M3 9a2 2 0 0 1 2-2h6l2.5 2.5H26a2 2 0 0 1 2 2V25a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" fill="${Y}" stroke="#a8761a" stroke-width="1.2"/><circle cx="17" cy="18" r="4" fill="#fff" stroke="${NV}" stroke-width="1.6"/><path d="M20 21l4 4" stroke="${NV}" stroke-width="2"/>`),
  tpAppearance: T(`<circle cx="16" cy="16" r="11" fill="url(#ap2)" stroke="${K}" stroke-width="1.2"/><defs><radialGradient id="ap2" cx=".35" cy=".3" r=".9"><stop offset="0" stop-color="#fff"/><stop offset=".4" stop-color="${B1}"/><stop offset="1" stop-color="${NV}"/></radialGradient></defs>`),
  tpProps: T(`<rect x="6" y="4" width="20" height="24" rx="2" fill="#fff" stroke="${K}" stroke-width="1.3"/><path d="M10 10h12M10 14.5h12M10 19h12M10 23.5h7" stroke="${M2}" stroke-width="1.6"/><circle cx="24" cy="24" r="5" fill="${NV}"/><path d="M24 22v4M24 20.6v.2" stroke="#fff" stroke-width="1.5"/>`),
  tpViews: T(`<rect x="3" y="5" width="12" height="10" rx="1" fill="${B2}" stroke="${K}" stroke-width="1.1"/><rect x="17" y="5" width="12" height="10" rx="1" fill="${B2}" stroke="${K}" stroke-width="1.1"/><rect x="3" y="17" width="12" height="10" rx="1" fill="${B2}" stroke="${K}" stroke-width="1.1"/><rect x="17" y="17" width="12" height="10" rx="1" fill="${Y2}" stroke="${K}" stroke-width="1.1"/>`),
  file: T(`<path d="M8 3h11l6 6v20H8z" fill="#fff" stroke="${K}" stroke-width="1.2"/><path d="M19 3v6h6" fill="${M1}" stroke="${K}" stroke-width="1.2"/>`),
  folder: T(`<path d="M3 9a2 2 0 0 1 2-2h6l2.5 2.5H26a2 2 0 0 1 2 2V25a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" fill="${Y}" stroke="#a8761a" stroke-width="1.2"/>`),
  drive: T(`<rect x="3" y="10" width="26" height="12" rx="2" fill="${M1}" stroke="${K}" stroke-width="1.3"/><circle cx="24" cy="16" r="1.6" fill="${GR}"/><path d="M6 16h12" stroke="${M2}" stroke-width="1.6"/>`),
};

export function icon(name) { return GLYPHS[name] || TOOLS[name] || GLYPHS.info; }
export function tool(name) { return TOOLS[name] || GLYPHS[name] || GLYPHS.info; }
export function hydrate(root = document) {
  root.querySelectorAll('i[data-icon]').forEach((el) => { if (!el.firstChild) el.innerHTML = icon(el.dataset.icon); });
}
export const ic = (name) => `<i data-icon="${name}">${icon(name)}</i>`;
export const ti = (name) => `<span class="ci">${tool(name)}</span>`;
