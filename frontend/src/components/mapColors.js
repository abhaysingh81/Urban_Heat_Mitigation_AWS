// Colour ramps used by the decision pages.
export const riskRgb = (v) => {           // 0–100 risk: pale yellow -> deep red
  const t = Math.max(0, Math.min(1, (v - 20) / 70));
  return [255, Math.round(230 - 200 * t), Math.round(120 - 110 * t)];
};
export const coolRgb = (d) => {           // °C change: 0 = transparent-ish grey, more negative = deeper blue
  const t = Math.max(0, Math.min(1, -d / 2));
  return [Math.round(200 - 170 * t), Math.round(210 - 90 * t), 255];
};
