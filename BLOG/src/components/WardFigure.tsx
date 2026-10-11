import { CITY_NAME, wards, type CityId } from '../lib/data';
import { fmt } from '../lib/heat';
import { CityTabs } from './CityTabs';

function Bar({ v, color }: { v: number; color: string }) {
  return (
    <span className="inline-block align-middle h-2 rounded-sm" style={{ width: `${Math.max(4, v * 100)}%`, maxWidth: '100%', background: color }} />
  );
}

export function WardFigure({ city, onCity }: { city: CityId; onCity: (c: CityId) => void }) {
  const w = wards[city];
  const rows = w.top.slice(0, 10);
  return (
    <figure className="figure m-0">
      <div className="mb-5">
        <CityTabs value={city} onChange={onCity} />
      </div>
      <div className="overflow-x-auto">
        <table className="data-table min-w-[40rem]">
          <caption className="sr-only">Top ten zones by heat risk in {CITY_NAME[city]}</caption>
          <thead>
            <tr>
              <th className="r" style={{ width: '3rem' }}>Rank</th>
              <th>Zone</th>
              <th className="r">Surface</th>
              <th className="r">People</th>
              <th style={{ width: '16%' }}>Hazard</th>
              <th style={{ width: '16%' }}>Exposure</th>
              <th style={{ width: '16%' }}>Vulnerability</th>
              <th className="r">Score</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.ward_id}>
                <td className="r num" style={{ color: 'var(--muted)' }}>{r.rank}</td>
                <td className="font-semibold whitespace-nowrap">{r.ward_name}</td>
                <td className="r">{r.lst_mean.toFixed(1)} °C</td>
                <td className="r">{fmt.int(r.population)}</td>
                <td><Bar v={r.hazard} color="var(--heat)" /></td>
                <td><Bar v={r.exposure} color="var(--ink-2)" /></td>
                <td><Bar v={r.vulnerability} color="var(--cool)" /></td>
                <td className="r font-semibold">{r.risk_score.toFixed(0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <figcaption className="fig-caption">
        <b>The ten highest-risk zones of {fmt.int(w.of_wards)} in {CITY_NAME[city]}.</b> Each bar is a percentile against the city’s other zones, so the score is a ranking for setting priorities, not a forecast of harm. Zones are 2 km analysis blocks, not official municipal wards; we did not have ward boundaries for all four cities.
      </figcaption>
    </figure>
  );
}
