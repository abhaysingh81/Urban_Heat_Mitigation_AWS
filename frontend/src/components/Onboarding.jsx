import { useState } from 'react';
import { useLang } from '../i18n';
import '../pages/Decision.css';

const KEY = 'heatrelief-onboarded';

export default function Onboarding() {
  const { t } = useLang();
  const [open, setOpen] = useState(() => {
    try { return localStorage.getItem(KEY) !== '1'; } catch { return true; }
  });
  if (!open) return null;
  const close = () => { try { localStorage.setItem(KEY, '1'); } catch { /* storage blocked: just close */ } setOpen(false); };
  return (
    <div role="dialog" aria-modal="true" aria-label={t('onb_title')}
         style={{ position: 'fixed', inset: 0, background: 'var(--scrim-bg)', display: 'grid', placeItems: 'center', zIndex: 50 }}>
      <div className="glass-panel dec-card" style={{ maxWidth: 480, background: 'var(--panel-bg-solid)' }}>
        <h3 style={{ fontSize: 20 }}>{t('onb_title')}</h3>
        <ul style={{ paddingLeft: 18, lineHeight: 1.6, margin: '12px 0' }}>
          <li>{t('onb_1')}</li><li>{t('onb_2')}</li><li>{t('onb_3')}</li>
        </ul>
        <button className="btn-primary" onClick={close} autoFocus>{t('onb_ok')}</button>
      </div>
    </div>
  );
}
