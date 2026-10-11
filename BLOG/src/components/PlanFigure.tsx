import { CITY_NAME, plans, sites, useGrid, type CityId, type Plan } from '../lib/data';
import { fmt } from '../lib/heat';
import { CityTabs } from './CityTabs';
import { ThermalMap } from './ThermalMap';

export function planAt(city: CityId, budget: number, eq: number): Plan {
  return plans[city].find((p) => p.budget_lakh === budget && p.equity_weight === eq)!;
}

export function PlanFigure({ city, onCity }: { city: CityId; onCity: (c: CityId) => void }) {
  const grid = useGrid(city);
  const s = sites[city];
  const eff = planAt(city, s.budget_lakh, 0);
  const eq = planAt(city, s.budget_lakh, 1);
  const gain = eq.people_protected / eff.people_protected - 1;

  const sides = [
    { key: '0.0' as const, title: 'Most cooling per rupee', note: 'λ = 0', plan: eff },
    { key: '1.0' as const, title: 'Vulnerable people first', note: 'λ = 1', plan: eq },
  ];

  return (
    <figure className="figure plate m-0 py-10 sm:py-14">
      <div className="wide-col">
        <div className="flex flex-wrap items-end justify-between gap-4 mb-8">
          <CityTabs value={city} onChange={onCity} />
          <p className="ui m-0 text-[0.9rem]" style={{ color: 'var(--plate-muted)' }}>
            Budget {fmt.crore(s.budget_lakh)} · {eff.n_actions} actions on each side
          </p>
        </div>

        <div className="grid gap-8 md:grid-cols-2">
          {sides.map((side) => (
            <div key={side.key}>
              <h3 className="text-[1.25rem] font-bold mb-1" style={{ fontStretch: '85%' }}>
                {side.title} <span className="ui font-normal text-[0.9rem]" style={{ color: 'var(--plate-muted)' }}>{side.note}</span>
              </h3>
              <p className="ui m-0 mb-4 num text-[0.95rem]" style={{ color: 'var(--plate-muted)' }}>
                <b className="text-[1.6rem] font-extrabold" style={{ color: side.key === '1.0' ? '#5ee0e6' : 'var(--plate-ink)', fontStretch: '80%' }}>
                  {fmt.lakhPeople(side.plan.people_protected)}
                </b>{' '}
                people within reach · ₹{fmt.int(side.plan.cost_per_person_inr)} per person
              </p>
              <div className="min-h-[16rem]">
                {grid && (
                  <ThermalMap
                    grid={grid}
                    dim
                    sites={s[side.key]}
                    maxHeight={460}
                    label={`${side.title}: ${side.plan.n_actions} sites in ${CITY_NAME[city]}`}
                  />
                )}
              </div>
            </div>
          ))}
        </div>

        <div className="ui flex flex-wrap gap-x-6 gap-y-2 mt-6 text-[0.85rem]" style={{ color: 'var(--plate-muted)' }}>
          <span className="inline-flex items-center gap-2"><svg width="14" height="14" aria-hidden><circle cx="7" cy="7" r="4.5" fill="#5ee0e6" /></svg>Shade structure (bus stop, market)</span>
          <span className="inline-flex items-center gap-2"><svg width="14" height="14" aria-hidden><circle cx="7" cy="7" r="5.5" fill="none" stroke="#fcffa4" strokeWidth="1.5" /></svg>Cooling centre</span>
          <span>Base map: surface temperature, faded</span>
        </div>

        <BudgetCurve city={city} />

        <figcaption className="fig-caption" style={{ color: 'var(--plate-muted)', maxWidth: '54rem' }}>
          <b style={{ color: 'var(--plate-ink)' }}>Same money, same number of sites, {Math.round(gain * 100)}% more people within reach.</b> Both plans come from the optimizer in the repo. “People within reach” counts residents of a cell that gets at least 0.2 °C of estimated cooling, or who live near a cooling centre. Cooling effects come from published ranges and costs are planning placeholders, not quotes.
        </figcaption>
      </div>
    </figure>
  );
}

function BudgetCurve({ city }: { city: CityId }) {
  const budgets = [...new Set(plans[city].map((p) => p.budget_lakh))].sort((a, b) => a - b);
  const W = 640, H = 220, L = 56, R = 110, T = 16, B = 34;
  const maxP = Math.max(...plans[city].map((p) => p.people_protected));
  const x = (b: number) => L + (budgets.indexOf(b) / (budgets.length - 1)) * (W - L - R);
  const y = (p: number) => T + (1 - p / maxP) * (H - T - B);
  const series = [
    { eq: 0, label: 'per rupee', color: 'var(--plate-muted)' },
    { eq: 1, label: 'equity', color: '#5ee0e6' },
  ];
  return (
    <div className="mt-12 max-w-[44rem]">
      <h3 className="text-[1.05rem] font-bold mb-3" style={{ fontStretch: '88%' }}>The gap grows with the budget</h3>
      <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto ui min-w-[30rem]" role="img" aria-label="People within reach at four budgets, for both plans">
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={L} x2={W - R} y1={y(maxP * f)} y2={y(maxP * f)} stroke="var(--plate-rule)" />
            <text x={L - 8} y={y(maxP * f) + 4} textAnchor="end" fontSize="12" fill="var(--plate-muted)" className="num">
              {f === 0 ? '0' : `${((maxP * f) / 1e6).toFixed(1)}M`}
            </text>
          </g>
        ))}
        {budgets.map((b) => (
          <text key={b} x={x(b)} y={H - 10} textAnchor="middle" fontSize="12" fill="var(--plate-muted)" className="num">₹{b / 100} cr</text>
        ))}
        {series.map((s) => {
          const pts = budgets.map((b) => [x(b), y(planAt(city, b, s.eq).people_protected)] as const);
          const last = pts[pts.length - 1];
          return (
            <g key={s.eq}>
              <polyline points={pts.map((p) => p.join(',')).join(' ')} fill="none" stroke={s.color} strokeWidth="2.5" />
              {pts.map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r="3.5" fill={s.color} />)}
              <text x={last[0] + 10} y={last[1] + 4} fontSize="13" fill={s.color} fontWeight="600">{s.label}</text>
            </g>
          );
        })}
      </svg>
      </div>
    </div>
  );
}
