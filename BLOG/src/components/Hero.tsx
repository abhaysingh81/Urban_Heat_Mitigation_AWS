import { useState } from 'react';
import { CITY_NAME, useGrid } from '../lib/data';
import { INFERNO, LST_DOMAIN, gradientCss } from '../lib/heat';
import { ThermalMap } from './ThermalMap';
import { REPO_URL } from '../content';

export function Hero() {
  const grid = useGrid('new_delhi');
  const [hover, setHover] = useState<number | null>(null);
  const hottest = grid ? Math.floor(grid.lst_stats.max) : null;

  return (
    <section id="top" className="plate relative overflow-hidden">
      <div className="wide-col grid gap-10 lg:gap-14 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] items-center py-16 lg:py-24">
        <div className="hero-in max-w-[36rem]">
          <p className="ui m-0 mb-6 text-[0.9rem]" style={{ color: 'var(--plate-muted)' }}>
            HeatRelief · a field report from Environmental Hacks, Heat &amp; Water track
          </p>
          <h1
            className="font-black m-0"
            style={{ fontSize: 'clamp(3rem, 1.6rem + 6vw, 6rem)', fontStretch: '72%', lineHeight: 0.9, letterSpacing: '-0.02em' }}
          >
            Who gets the shade?
          </h1>
          <p className="mt-7 mb-0" style={{ fontSize: 'clamp(1.15rem, 1rem + 0.5vw, 1.4rem)', lineHeight: 1.5, color: 'var(--plate-ink)' }}>
            {hottest
              ? <>In Delhi’s hottest 500-metre blocks the ground passes <b className="num" style={{ color: '#fca50a' }}>{hottest}&nbsp;°C</b> before the monsoon. </>
              : <>In Delhi’s hottest blocks the ground runs past 50&nbsp;°C before the monsoon. </>}
            Every city has a heat map. What it lacks is a defensible way to decide where a fixed cooling budget goes, and to explain that choice to the people it affects.
          </p>
          <p className="mt-5 mb-0" style={{ color: 'var(--plate-muted)', lineHeight: 1.6 }}>
            We built HeatRelief to close that gap: satellite surface temperature in, a ranked list of wards, a costed plan and a ward brief in Hindi and English out. This is how it works, what the numbers say, and where it is still weak.
          </p>
          <div className="ui mt-9 flex flex-wrap items-center gap-x-6 gap-y-3 text-[0.9rem]" style={{ color: 'var(--plate-muted)' }}>
            <span>Team HeatRelief · 11 October 2026 · 12 min read</span>
            <a href={REPO_URL} className="font-semibold" style={{ color: 'var(--plate-ink)' }}>
              Source code ↗
            </a>
            <a href="#problem" className="font-semibold" style={{ color: 'var(--plate-ink)' }}>
              Start reading ↓
            </a>
          </div>
        </div>

        <figure className="m-0">
          <div className="relative">
            {grid ? (
              <ThermalMap grid={grid} reveal maxHeight={720} onHover={setHover} label={`Land-surface temperature across ${grid.cells.toLocaleString('en-IN')} cells inside Delhi`} />
            ) : (
              <div style={{ aspectRatio: '100 / 106' }} />
            )}
            <div
              className="ui absolute left-0 bottom-0 text-[0.85rem] px-3 py-2 rounded num"
              style={{ background: 'color-mix(in oklch, var(--plate) 85%, transparent)', color: 'var(--plate-ink)', minWidth: '13rem' }}
              aria-live="polite"
            >
              {grid && hover != null ? (
                <>
                  <b style={{ fontSize: '1.15rem' }}>{grid.lst[hover]?.toFixed(1)} °C</b> surface
                  <br />
                  <span style={{ color: 'var(--plate-muted)' }}>
                    {Math.round((grid.imperv[hover] ?? 0) * 100)}% built-up · NDVI {grid.ndvi[hover]?.toFixed(2)}
                  </span>
                </>
              ) : (
                <span style={{ color: 'var(--plate-muted)' }}>Point at any block to read it</span>
              )}
            </div>
          </div>
          <figcaption className="ui mt-4 text-[0.82rem] leading-snug" style={{ color: 'var(--plate-muted)' }}>
            <div className="flex items-center gap-3 mb-2.5 num">
              <span>{LST_DOMAIN[0]} °C</span>
              <span className="h-2 flex-1 max-w-[16rem] rounded-sm" style={{ background: gradientCss(INFERNO) }} />
              <span>{LST_DOMAIN[1]} °C</span>
            </div>
            {CITY_NAME.new_delhi}, land-surface temperature. Each square is one 500 m cell inside the city boundary: the median of the clear Landsat 8/9 scenes from April to June, 2024–2026. Surface temperature, not air temperature.
          </figcaption>
        </figure>
      </div>
    </section>
  );
}
