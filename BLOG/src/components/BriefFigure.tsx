import { useMemo, useState } from 'react';
import { brief } from '../lib/data';
import { Seg } from './CityTabs';

// Same rule as agent/numbers_check.py: a number is allowed only if the tool facts contain it.
const NUMBER = /\d[\d,]*(?:\.\d+)?/g;
const DEVANAGARI = '०१२३४५६७८९';
const norm = (t: string) => {
  let s = t.replace(/,/g, '');
  if (s.includes('.')) s = s.replace(/0+$/, '').replace(/\.$/, '');
  return s.replace(/^0+(?=\d)/, '') || '0';
};
const toAscii = (s: string) => s.replace(/[०-९]/g, (d) => String(DEVANAGARI.indexOf(d)));

function highlight(text: string, allowed: Set<string>) {
  const out: (string | { n: string; ok: boolean })[] = [];
  let last = 0;
  const ids = [...text.matchAll(/Zone \d+-\d+/g)].map((m) => [m.index!, m.index! + m[0].length]);
  for (const m of toAscii(text).matchAll(NUMBER)) {
    const i = m.index!;
    if (ids.some(([a, b]) => i >= a && i < b)) continue;
    out.push(text.slice(last, i));
    out.push({ n: text.slice(i, i + m[0].length), ok: allowed.has(norm(m[0])) });
    last = i + m[0].length;
  }
  out.push(text.slice(last));
  return out;
}

// An invented sentence of the kind a language model produces when left alone with numbers.
const DRAFT =
  'Shade structures at 3 sites will lower temperatures by 4 °C and protect 2,00,000 residents of Zone 20-16.';

export function BriefFigure() {
  const [lang, setLang] = useState<'en' | 'hi'>('en');
  const allowed = useMemo(() => {
    const s = new Set<string>();
    for (const m of toAscii(brief.en + ' ' + brief.hi).matchAll(NUMBER)) s.add(norm(m[0]));
    return s;
  }, []);
  const lines = (lang === 'en' ? brief.en : brief.hi).split('\n');

  return (
    <figure className="figure m-0">
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)] items-start">
        <div className="rounded-md border p-5 sm:p-7" style={{ borderColor: 'var(--rule-strong)', background: 'var(--surface)' }}>
          <div className="flex items-center justify-between gap-4 mb-5">
            <span className="ui text-[0.85rem]" style={{ color: 'var(--muted)' }}>Ward brief · generated from tool output</span>
            <Seg label="Language" value={lang} onChange={setLang} options={[{ id: 'en', label: 'English' }, { id: 'hi', label: 'हिन्दी' }]} />
          </div>
          <div lang={lang} className={lang === 'hi' ? 'hindi' : ''} style={{ fontSize: '1rem', color: 'var(--ink)' }}>
            {lines.map((line, i) => (
              <p key={i} className="m-0 mb-2.5" style={{ paddingLeft: line.startsWith('- ') ? '1rem' : 0 }}>
                {highlight(line, allowed).map((part, j) =>
                  typeof part === 'string' ? part : (
                    <mark key={j} className="num" style={{ background: 'var(--cool-wash)', color: 'var(--cool-ink)', padding: '0 2px', borderRadius: 2 }}>
                      {part.n}
                    </mark>
                  ),
                )}
              </p>
            ))}
          </div>
        </div>

        <div>
          <p className="ui m-0 mb-3 text-[0.95rem] font-semibold">What the numbers check catches</p>
          <p className="m-0 mb-4 p-4 rounded-md" style={{ background: 'var(--sunk)', border: '1px solid var(--rule)', fontSize: '1rem' }}>
            {highlight(DRAFT, allowed).map((part, j) =>
              typeof part === 'string' ? part : part.ok ? (
                <mark key={j} className="num" style={{ background: 'var(--cool-wash)', color: 'var(--cool-ink)', padding: '0 2px', borderRadius: 2 }}>{part.n}</mark>
              ) : (
                <mark key={j} className="num" style={{ background: 'var(--heat-wash)', color: 'var(--heat-ink)', textDecoration: 'line-through', padding: '0 2px', borderRadius: 2 }}>{part.n}</mark>
              ),
            )}
          </p>
          <p className="ui m-0 text-[0.9rem] leading-relaxed" style={{ color: 'var(--ink-2)' }}>
            An example draft, written by us to show the check. “3 sites” is in the plan, so it passes. “4 °C” and “2,00,000” appear in no tool result, so the draft is sent back once with the offending numbers named. If the retry also fails, or the model runs past its 20-second budget, the officer gets the deterministic template on the left instead.
          </p>
        </div>
      </div>
      <figcaption className="fig-caption">
        <b>A real brief for the highest-ranked zone in Delhi,</b> produced by the template path with the repo’s own tools. {brief.forecast_note} Highlighted numbers are the ones the check traced back to tool output.
      </figcaption>
    </figure>
  );
}
