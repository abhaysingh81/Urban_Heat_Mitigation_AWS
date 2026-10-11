import { useEffect, useState } from 'react';
import { INFERNO, gradientCss } from '../lib/heat';

export const CHAPTERS = [
  { id: 'problem', label: 'Problem' },
  { id: 'built', label: 'What we built' },
  { id: 'ground', label: 'Data' },
  { id: 'model', label: 'Model' },
  { id: 'wards', label: 'Wards' },
  { id: 'plans', label: 'Plans' },
  { id: 'briefs', label: 'Briefs' },
  { id: 'aws', label: 'On AWS' },
  { id: 'fought', label: 'What fought back' },
  { id: 'limits', label: 'Limits' },
];

type Theme = 'light' | 'dark' | null;

function readTheme(): Theme {
  try {
    const t = localStorage.getItem('hr-theme');
    return t === 'light' || t === 'dark' ? t : null;
  } catch {
    return null;
  }
}

export function Masthead() {
  const [progress, setProgress] = useState(0);
  const [active, setActive] = useState<string | null>(null);
  const [shown, setShown] = useState(false);
  const [theme, setTheme] = useState<Theme>(readTheme);

  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
  }, [theme]);

  useEffect(() => {
    const onScroll = () => {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      setProgress(max > 0 ? window.scrollY / max : 0);
      setShown(window.scrollY > window.innerHeight * 0.7);
      let current: string | null = null;
      for (const c of CHAPTERS) {
        const el = document.getElementById(c.id);
        if (el && el.getBoundingClientRect().top < window.innerHeight * 0.35) current = c.id;
      }
      setActive(current);
    };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
    };
  }, []);

  const isDark =
    theme === 'dark' ||
    (theme === null && typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches);

  const toggle = () => {
    const next = isDark ? 'light' : 'dark';
    setTheme(next);
    try {
      localStorage.setItem('hr-theme', next);
    } catch {
      /* storage unavailable: theme still applies for this visit */
    }
  };

  return (
    <header
      className="fixed inset-x-0 top-0 ui"
      style={{
        zIndex: 'var(--z-sticky)' as unknown as number,
        background: 'color-mix(in oklch, var(--bg) 92%, transparent)',
        backdropFilter: 'saturate(1.4) blur(10px)',
        borderBottom: '1px solid var(--rule)',
        paddingTop: 'env(safe-area-inset-top, 0px)',
        transform: shown ? 'none' : 'translateY(-100%)',
        transition: 'transform 0.35s var(--ease-out)',
      }}
      aria-hidden={!shown}
    >
      <div className="wide-col flex items-center gap-5 h-14">
        <a href="#top" className="no-underline shrink-0 font-extrabold tracking-tight" style={{ fontStretch: '80%', fontSize: '1.05rem' }} tabIndex={shown ? 0 : -1}>
          HeatRelief
        </a>
        <nav aria-label="Chapters" className="flex-1 overflow-x-auto" style={{ scrollbarWidth: 'none' }}>
          <ul className="flex flex-nowrap gap-1 m-0 p-0 list-none whitespace-nowrap text-[0.85rem]">
            {CHAPTERS.map((c) => (
              <li key={c.id}>
                <a
                  href={`#${c.id}`}
                  tabIndex={shown ? 0 : -1}
                  className="block px-2 py-1 rounded no-underline whitespace-nowrap"
                  aria-current={active === c.id ? 'true' : undefined}
                  style={{
                    color: active === c.id ? 'var(--ink)' : 'var(--muted)',
                    fontWeight: active === c.id ? 650 : 450,
                  }}
                >
                  {c.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <button
          onClick={toggle}
          tabIndex={shown ? 0 : -1}
          className="shrink-0 text-[0.8rem] px-2.5 py-1 rounded border cursor-pointer"
          style={{ borderColor: 'var(--rule)', background: 'transparent', color: 'var(--ink-2)', minHeight: '2rem' }}
          aria-label={`Switch to ${isDark ? 'light' : 'dark'} theme`}
        >
          {isDark ? 'Light' : 'Dark'}
        </button>
      </div>
      <div
        aria-hidden
        style={{
          height: 3,
          background: gradientCss(INFERNO.slice(3)),
          clipPath: `inset(0 ${(1 - progress) * 100}% 0 0)`,
        }}
      />
    </header>
  );
}
