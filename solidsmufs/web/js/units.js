// Units and number formatting, SolidWorks-style unit systems. The model is always in millimeters.
export const LENGTH = {
  mm: { label: 'mm', factor: 1, decimals: 2 },
  cm: { label: 'cm', factor: 10, decimals: 3 },
  m: { label: 'm', factor: 1000, decimals: 5 },
  in: { label: 'in', factor: 25.4, decimals: 4 },
  ft: { label: 'ft', factor: 304.8, decimals: 5 },
  um: { label: 'µm', factor: 0.001, decimals: 1 },
};
export const MASS = { g: 1, kg: 1000, lb: 453.59237 };
// SolidWorks' unit systems (length / mass); "Custom" keeps whatever the user picked
export const SYSTEMS = {
  MMGS: { length: 'mm', mass: 'g', name: 'MMGS (millimeter, gram, second)' },
  CGS: { length: 'cm', mass: 'g', name: 'CGS (centimeter, gram, second)' },
  MKS: { length: 'm', mass: 'kg', name: 'MKS (meter, kilogram, second)' },
  IPS: { length: 'in', mass: 'lb', name: 'IPS (inch, pound, second)' },
};

export class Units {
  constructor(system = 'MMGS') {
    this.setSystem(system);
  }

  setSystem(system, decimals = null) {
    const s = SYSTEMS[system] || SYSTEMS.MMGS;
    this.system = SYSTEMS[system] ? system : 'MMGS';
    this.unit = s.length;
    this.massUnit = s.mass;
    this.decimals = decimals ?? LENGTH[this.unit].decimals;
    this.angleDecimals = 2;
  }

  setCustom(length, mass, decimals) {
    this.system = 'Custom';
    this.unit = LENGTH[length] ? length : 'mm';
    this.massUnit = MASS[mass] ? mass : 'g';
    this.decimals = decimals ?? LENGTH[this.unit].decimals;
  }

  get u() { return LENGTH[this.unit]; }
  get label() { return this.u.label; }

  num(v, d = this.decimals) {
    if (v === null || v === undefined || Number.isNaN(v)) return '—';
    const s = Number(v).toFixed(d);
    return /^-0\.?0*$/.test(s) ? s.slice(1) : s;
  }

  len(mm, withUnit = true, d) { return this.num(mm / this.u.factor, d) + (withUnit ? this.label : ''); }
  area(mm2, withUnit = true) { return this.num(mm2 / this.u.factor ** 2) + (withUnit ? `${this.label}^2` : ''); }
  vol(mm3, withUnit = true) { return this.num(mm3 / this.u.factor ** 3) + (withUnit ? `${this.label}^3` : ''); }
  angle(deg, withUnit = true) { return this.num(deg, this.angleDecimals) + (withUnit ? '°' : ''); }
  mass(g, withUnit = true) { return this.num(g / MASS[this.massUnit]) + (withUnit ? ` ${this.massName(true)}` : ''); }
  massName(plural) {
    return { g: plural ? 'grams' : 'gram', kg: plural ? 'kilograms' : 'kilogram', lb: plural ? 'pounds' : 'pound' }[this.massUnit];
  }
  lengthName(plural) {
    return { mm: 'millimeter', cm: 'centimeter', m: 'meter', in: 'inch', ft: 'foot', um: 'micron' }[this.unit] + (plural ? (this.unit === 'in' ? 'es' : this.unit === 'ft' ? '' : 's') : '');
  }
  inertia(gmm2) { return this.num(gmm2 / MASS[this.massUnit] / this.u.factor ** 2); }
  densityValue(gcc) { return (gcc / MASS[this.massUnit]) * (this.u.factor / 10) ** 3; } // g/cm³ → mass unit per length unit³
  densityUnit() { return `${this.massName(true)} per cubic ${this.lengthName(false)}`; }
  point(p) { return p ? `${this.len(p[0], false)}, ${this.len(p[1], false)}, ${this.len(p[2], false)}` : '—'; }
  vec(v) { return v ? `${this.num(v[0], 4)}, ${this.num(v[1], 4)}, ${this.num(v[2], 4)}` : '—'; }
  toMm(v) { return v * this.u.factor; }

  value(row) {
    const v = row.value;
    switch (row.kind) {
      case 'length': return this.len(v);
      case 'area': return this.area(v);
      case 'angle': return this.angle(v);
      case 'point': return `X: ${this.len(v[0])}, Y: ${this.len(v[1])}, Z: ${this.len(v[2])}`;
      case 'vector': return this.vec(v);
      case 'number': return String(v);
      default: return v === null || v === undefined ? '—' : String(v);
    }
  }
}
