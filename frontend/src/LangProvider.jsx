import { useState, useCallback } from 'react';
import { LangContext, STRINGS } from './i18n';

export function LangProvider({ children }) {
  const [lang, setLangState] = useState(() => localStorage.getItem('heatrelief-lang') || 'en');
  const setLang = useCallback((l) => { localStorage.setItem('heatrelief-lang', l); setLangState(l); }, []);
  const t = useCallback((k) => STRINGS[lang][k] ?? STRINGS.en[k] ?? k, [lang]);
  return <LangContext.Provider value={{ lang, setLang, t }}>{children}</LangContext.Provider>;
}
