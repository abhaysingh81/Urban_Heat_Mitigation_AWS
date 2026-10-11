import { useState } from 'react';
import { CITY_NAME, useGrid, type CityId } from '../lib/data';
import { fmt, gradientCss } from '../lib/heat';
import { CityTabs, Seg } from './CityTabs';
import { LAYERS, ThermalMap, type Layer } from './ThermalMap';

export function CityExplorer({ city, onCity }: { city: CityId; onCity: (c: CityId) => void }) {
  const [layer, setLayer] = useState<Layer>('lst');
  const [hover, setHover] = useState<number | null>(null);
  const grid = useGrid(city);
  const spec = LAYERS[layer];

  return (
    <figure className="figure plate m-0 py-10 sm:py-14">
      <div className="wide-col">
        <div className="flex flex-wrap items-center gap-3 mb-6">
          <CityTabs value={city} onChange={(c) => { setHover(null); onCity(c); }} />
          <Seg
            label="Layer"
            value={layer}
            onChange={setLayer}
            options={(Object.keys(LAYERS) as Layer[]).map((id) => ({ id, label: LAYERS[id].label }))}
          />
        </div>

        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_17rem] items-start">
          <div className="min-h-[24rem]">
            {grid && (
              <ThermalMap
                grid={grid}
                layer={layer}
                maxHeight={640}
                onHover={setHover}
                label={`${spec.label} across ${CITY_NAME[city]}, ${grid.cells} cells`}
              />
            )}
          </div>

          <div className="ui text-[0.9rem]" style={{ color: 'var(--plate-muted)' }}>
            <div className="flex items-center gap-2.5 mb-6 num text-[0.8rem]">
              <span>{spec.legend[0]}</span>
              <span className="h-2 flex-1 rounded-sm" style={{ background: gradientCss(spec.stops) }} />
              <span>{spec.legend[1]}</span>
            </div>

            <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 num" aria-live="polite">
              {grid && hover != null ? (
                <>
                  <dt>Surface</dt>
                  <dd className="m-0 text-right font-semibold" style={{ color: 'var(--plate-ink)' }}>{grid.lst[hover]?.toFixed(1)} °C</dd>
                  <dt>Greenness</dt>
                  <dd className="m-0 text-right" style={{ color: 'var(--plate-ink)' }}>{grid.ndvi[hover]?.toFixed(2)}</dd>
                  <dt>Built-up</dt>
                  <dd className="m-0 text-right" style={{ color: 'var(--plate-ink)' }}>{Math.round((grid.imperv[hover] ?? 0) * 100)}%</dd>
                  <dt>People / km²</dt>
                  <dd className="m-0 text-right" style={{ color: 'var(--plate-ink)' }}>{fmt.int(grid.pop[hover] ?? 0)}</dd>
                </>
              ) : grid ? (
                <>
                  <dt>Cells</dt>
                  <dd className="m-0 text-right" style={{ color: 'var(--plate-ink)' }}>{fmt.int(grid.cells)}</dd>
                  <dt>Coolest</dt>
                  <dd className="m-0 text-right" style={{ color: 'var(--plate-ink)' }}>{grid.lst_stats.min.toFixed(1)} °C</dd>
                  <dt>Average</dt>
                  <dd className="m-0 text-right" style={{ color: 'var(--plate-ink)' }}>{grid.lst_stats.mean.toFixed(1)} °C</dd>
                  <dt>Hottest</dt>
                  <dd className="m-0 text-right font-semibold" style={{ color: '#fca50a' }}>{grid.lst_stats.max.toFixed(1)} °C</dd>
                </>
              ) : null}
            </dl>
            <p className="mt-6 mb-0 leading-snug text-[0.85rem]">
              {hover != null ? 'Move away from the map to see city totals.' : 'Point at the map to read a single 500 m cell.'} Switch layers to see why the hot cells are hot: little green, mostly concrete.
            </p>
          </div>
        </div>

        <figcaption className="fig-caption" style={{ color: 'var(--plate-muted)', maxWidth: '52rem' }}>
          <b style={{ color: 'var(--plate-ink)' }}>The four real-data cities, cell by cell.</b> Surface temperature is the April–June Landsat median. All four maps share one colour scale, so Jaipur’s ground really is hotter than Bengaluru’s. Cells outside each city’s OpenStreetMap boundary are left out.
        </figcaption>
      </div>
    </figure>
  );
}
