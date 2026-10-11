import { CITY_IDS, CITY_NAME, model } from '../lib/data';
import { fmt } from '../lib/heat';
import { SHAP_LABEL } from '../content';

const W = 720;
const ROW = 46;
const LEFT = 104;
const RIGHT = 24;
const TOP = 34;

export function ModelFigure() {
  const H = TOP + ROW * CITY_IDS.length + 30;
  const x = (r: number) => LEFT + ((r + 1) / 2) * (W - LEFT - RIGHT);
  const ticks = [-1, -0.5, 0, 0.5, 1];

  return (
    <figure className="figure m-0">
      <div className="ui flex flex-wrap gap-x-6 gap-y-2 text-[0.85rem] mb-3" style={{ color: 'var(--ink-2)' }}>
        <Key shape="hollow" label="Simple baseline: greenness + concrete, linear" />
        <Key shape="filled" label="HeatRelief, on a city it never saw" />
        <Key shape="tick" label="HeatRelief, 5 km blocks within each city (optimistic)" />
      </div>
      <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto ui min-w-[32rem]" role="img" aria-labelledby="model-fig-title">
        <title id="model-fig-title">
          Correlation between predicted and observed surface temperature per held-out city. The model scores between {fmt.r(Math.min(...CITY_IDS.map((c) => model.loco[c].pearson_r)))} and {fmt.r(Math.max(...CITY_IDS.map((c) => model.loco[c].pearson_r)))}; the baseline is negative everywhere.
        </title>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={TOP - 8} y2={H - 26} stroke={t === 0 ? 'var(--rule-strong)' : 'var(--rule)'} />
            <text x={x(t)} y={H - 8} textAnchor="middle" fontSize="13" fill="var(--muted)" className="num">
              {t === 0 ? '0' : fmt.r(t).replace('.00', '').replace(/0$/, '')}
            </text>
          </g>
        ))}
        <text x={x(-1)} y={14} fontSize="12.5" fill="var(--muted)">← pattern reversed</text>
        <text x={x(1)} y={14} fontSize="12.5" fill="var(--muted)" textAnchor="end">pattern matches →</text>
        {CITY_IDS.map((c, i) => {
          const y = TOP + i * ROW + ROW / 2;
          const b = model.baseline_r[c];
          const m = model.loco[c].pearson_r;
          const k = model.block_cv[c].pearson_r;
          return (
            <g key={c}>
              <text x={0} y={y + 5} fontSize="15" fontWeight="600" fill="var(--ink)">{CITY_NAME[c]}</text>
              <line x1={x(b)} x2={x(m)} y1={y} y2={y} stroke="var(--rule-strong)" strokeWidth="1.5" />
              <circle cx={x(b)} cy={y} r="6.5" fill="var(--bg)" stroke="var(--muted)" strokeWidth="2" />
              <text x={x(b)} y={y - 12} fontSize="12" textAnchor="middle" fill="var(--muted)" className="num">{fmt.r(b)}</text>
              <line x1={x(k)} x2={x(k)} y1={y - 9} y2={y + 9} stroke="var(--cool)" strokeWidth="2.5" />
              <circle cx={x(m)} cy={y} r="7.5" fill="var(--heat)" />
              <text x={x(m) - 12} y={y - 12} fontSize="12.5" textAnchor="end" fill="var(--heat-ink)" fontWeight="650" className="num">{fmt.r(m)}</text>
            </g>
          );
        })}
      </svg>
      </div>
      <figcaption className="fig-caption">
        <b>Pearson r between predicted and observed surface temperature.</b> Each city was held out in turn: trained on the other three, scored on it. Model {model.version}, {model.n_features} features, {fmt.int(model.n_cells)} cells.
      </figcaption>
    </figure>
  );
}

function Key({ shape, label }: { shape: 'hollow' | 'filled' | 'tick'; label: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <svg width="16" height="16" aria-hidden>
        {shape === 'hollow' && <circle cx="8" cy="8" r="5.5" fill="none" stroke="var(--muted)" strokeWidth="2" />}
        {shape === 'filled' && <circle cx="8" cy="8" r="6" fill="var(--heat)" />}
        {shape === 'tick' && <line x1="8" x2="8" y1="1" y2="15" stroke="var(--cool)" strokeWidth="2.5" />}
      </svg>
      {label}
    </span>
  );
}

export function ErrorTable() {
  return (
    <div className="overflow-x-auto">
      <table className="data-table min-w-[34rem]">
        <caption className="sr-only">Held-out error per city</caption>
        <thead>
          <tr>
            <th>Held-out city</th>
            <th className="r">Cells</th>
            <th className="r">r</th>
            <th className="r">Typical error (RMSE)</th>
            <th className="r">Offset (bias)</th>
            <th className="r">q10–q90 band coverage</th>
          </tr>
        </thead>
        <tbody>
          {CITY_IDS.map((c) => {
            const l = model.loco[c];
            return (
              <tr key={c}>
                <td className="font-semibold">{CITY_NAME[c]}</td>
                <td className="r">{fmt.int(l.n)}</td>
                <td className="r">{l.pearson_r.toFixed(3)}</td>
                <td className="r">{l.rmse.toFixed(1)} °C</td>
                <td className="r" style={{ color: Math.abs(l.bias) > 2.5 ? 'var(--heat-ink)' : undefined, fontWeight: Math.abs(l.bias) > 2.5 ? 650 : undefined }}>
                  {fmt.signed(l.bias)} °C
                </td>
                <td className="r">{Math.round(model.coverage_calibrated[c] * 100)}%</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function ShapFigure() {
  const top = model.shap.slice(0, 8);
  const max = top[0].mean_abs_shap;
  return (
    <figure className="figure m-0">
      <ol className="list-none m-0 p-0 ui grid gap-2.5">
        {top.map((d) => (
          <li key={d.feature} className="grid grid-cols-[minmax(9rem,15rem)_1fr_3.5rem] items-center gap-3 text-[0.92rem]">
            <span style={{ color: 'var(--ink)' }}>{SHAP_LABEL[d.feature] ?? d.feature}</span>
            <span className="h-3.5 rounded-sm" style={{ width: `${(d.mean_abs_shap / max) * 100}%`, background: 'var(--ink)', opacity: 0.35 + 0.65 * (d.mean_abs_shap / max) }} />
            <span className="num text-right" style={{ color: 'var(--ink-2)' }}>{d.mean_abs_shap.toFixed(2)} °C</span>
          </li>
        ))}
      </ol>
      <figcaption className="fig-caption">
        <b>What the model leans on.</b> Mean absolute SHAP value: how far, on average, each feature moves a cell’s predicted temperature. This explains the model, not the city. It is not proof that changing a feature changes the heat.
      </figcaption>
    </figure>
  );
}
