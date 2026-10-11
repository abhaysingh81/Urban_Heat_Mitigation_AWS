// Colour ramps and formatting shared by every figure.

type RGB = [number, number, number];

const hex = (h: string): RGB => [
  parseInt(h.slice(1, 3), 16),
  parseInt(h.slice(3, 5), 16),
  parseInt(h.slice(5, 7), 16),
];

// matplotlib "inferno": perceptually uniform and readable with colour-blindness.
export const INFERNO = [
  '#000004', '#160b39', '#420a68', '#6a176e', '#932667', '#bc3754',
  '#dd513a', '#f37819', '#fca50a', '#f6d746', '#fcffa4',
].map(hex);

// single-hue ramps for the other layers, light → dark on a dark plate read as "more"
export const GREENS = ['#14231b', '#1d3d29', '#255b36', '#2f7a41', '#4c9a4f', '#7cba68', '#b6d98e', '#e6f2c4'].map(hex);
export const GREYS = ['#191524', '#2c2838', '#433e4f', '#5d5868', '#7a7584', '#9a95a2', '#bdb9c3', '#e4e1e8'].map(hex);
export const VIOLETS = ['#160f2b', '#2a1a4d', '#40256f', '#583290', '#7347ab', '#9568c2', '#bb95d8', '#e4cfef'].map(hex);

export function ramp(stops: RGB[], t: number): RGB {
  const x = Math.min(1, Math.max(0, t)) * (stops.length - 1);
  const i = Math.floor(x);
  const f = x - i;
  const a = stops[i];
  const b = stops[Math.min(i + 1, stops.length - 1)];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

export const css = (c: RGB) => `rgb(${c[0] | 0} ${c[1] | 0} ${c[2] | 0})`;

export const gradientCss = (stops: RGB[]) =>
  `linear-gradient(90deg, ${stops.map((s, i) => `${css(s)} ${(i / (stops.length - 1)) * 100}%`).join(', ')})`;

// One temperature domain for every city so the maps can be compared by eye.
export const LST_DOMAIN: [number, number] = [32, 54];

export const fmt = {
  int: (n: number) => Math.round(n).toLocaleString('en-IN'),
  lakhPeople: (n: number) =>
    n >= 1e6 ? `${(n / 1e6).toFixed(2)} million` : `${(n / 1e5).toFixed(1)} lakh`,
  crore: (lakh: number) => `₹${(lakh / 100).toLocaleString('en-IN')} crore`,
  signed: (n: number, d = 1) => `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n).toFixed(d)}`,
  r: (n: number) => (n < 0 ? `−${Math.abs(n).toFixed(2)}` : n.toFixed(2)),
};
