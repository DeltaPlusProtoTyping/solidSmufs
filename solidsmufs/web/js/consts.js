// Shared names and tables (kept apart from main.js so modules don't import each other in a circle).
export const PRODUCT = 'SolidSmurfs';

export const STYLES = [
  { id: 'shadedEdges', label: 'Shaded With Edges', icon: 'stShadedEdges' },
  { id: 'shaded', label: 'Shaded', icon: 'stShaded' },
  { id: 'hlr', label: 'Hidden Lines Removed', icon: 'stHlr' },
  { id: 'hlv', label: 'Hidden Lines Visible', icon: 'stHlv' },
  { id: 'wire', label: 'Wireframe', icon: 'stWire' },
];

export const SCENES = [
  // follows the interface: a soft steel gradient by day, a deep studio gradient at night
  { id: 'auto', label: 'Match Interface', bg: ['#f9fafc', '#c3cbd7'], night: ['#3b4456', '#12161e'] },
  { id: 'steel', label: 'Wagner Steel', bg: ['#fbfcfd', '#c3cbd6'] },
  { id: 'classic', label: 'Gradient Blue', bg: ['#ffffff', '#a9bcd8'] },
  { id: 'white', label: 'Plain White', bg: ['#ffffff', '#ffffff'] },
  { id: 'navy', label: 'Wagner Navy', bg: ['#3a5193', '#121d3d'], dark: true },
  { id: 'graphite', label: 'Graphite', bg: ['#4a515c', '#1c2026'], dark: true },
  { id: 'studio', label: 'Studio', bg: ['#3b4552', '#151a21'], dark: true },
];

// densities in g/cm³ (SolidWorks-style material library, the ones a machine shop sees most)
export const MATERIALS = [
  { group: 'Steel', items: [['1018 Steel', 7.87], ['1045 Steel', 7.85], ['4140 Alloy Steel', 7.85], ['4340 Alloy Steel', 7.85], ['A2 Tool Steel', 7.86], ['D2 Tool Steel', 7.7], ['O1 Tool Steel', 7.81], ['12L14 Steel', 7.87], ['Cast Iron (Gray)', 7.2]] },
  { group: 'Stainless', items: [['303 Stainless', 8.0], ['304 Stainless', 8.0], ['316 Stainless', 8.0], ['17-4 PH Stainless', 7.8], ['410 Stainless', 7.75], ['440C Stainless', 7.65]] },
  { group: 'Aluminum', items: [['6061-T6 Aluminum', 2.7], ['7075-T6 Aluminum', 2.81], ['2024-T3 Aluminum', 2.78], ['5052 Aluminum', 2.68], ['MIC-6 Cast Plate', 2.65]] },
  { group: 'Copper alloys', items: [['360 Brass', 8.5], ['C110 Copper', 8.94], ['932 Bearing Bronze', 8.8], ['954 Aluminum Bronze', 7.45], ['Beryllium Copper', 8.25]] },
  { group: 'High-performance', items: [['Ti-6Al-4V Titanium', 4.43], ['CP Titanium Gr 2', 4.51], ['Inconel 718', 8.19], ['Inconel 625', 8.44], ['Hastelloy C-276', 8.89], ['Kovar', 8.36], ['Tungsten Carbide', 15.6], ['Tungsten', 19.3]] },
  { group: 'Plastics', items: [['Acetal (Delrin)', 1.41], ['Nylon 6/6', 1.14], ['PEEK', 1.32], ['Ultem (PEI)', 1.27], ['UHMW-PE', 0.93], ['PTFE (Teflon)', 2.2], ['Polycarbonate', 1.2], ['Acrylic', 1.19], ['ABS', 1.05], ['PVC', 1.38], ['G-10 / FR-4', 1.85]] },
];

/** "AISI 304 (8 g/cm³)"; a material without one density (an assembly weighed part by part) is just its name. */
export const materialLabel = (mat) => (mat ? (mat.density != null ? `${mat.name} (${mat.density} g/cm³)` : mat.name) : '');
export const escapeHtml = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
export const clean = (s) => ({ kind: s.kind, index: s.index, point: s.point, face: s.face });
export function mergeSel(a, b) {
  const key = (s) => `${s.kind}:${s.index}`;
  const seen = new Set(a.map(key));
  return [...a, ...b.filter((s) => !seen.has(key(s)))];
}
