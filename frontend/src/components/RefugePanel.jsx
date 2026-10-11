import { useCallback, useEffect, useMemo, useState } from 'react';
import { API_BASE } from '../api';
import { useLang } from '../i18n';
import { staffHeaders } from '../platform';

const STATUSES = ['open', 'busy', 'full', 'closed'];

// Ward-officer panel (Feature L): set each cool refuge open / busy / full / closed. The citizen page
// stops sending people to full or closed places; other officer screens update over the live feed
// (`liveUpdates` maps refuge id -> latest shelter.updated payload from the parent's WebSocket).
export default function RefugePanel({ city, liveUpdates }) {
  const { t } = useLang();
  const [q, setQ] = useState('');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(async (query) => {
    try {
      const params = new URLSearchParams({ city, limit: '40' });
      if (query) params.set('q', query);
      const r = await fetch(`${API_BASE}/api/v1/shelters?${params}`);
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || t('error'));
      setData(await r.json()); setError(null);
    } catch (e) { setError(e.message || t('error')); }
  }, [city, t]);

  useEffect(() => {                       // search as you type, without a request per keystroke
    const id = setTimeout(() => load(q.trim()), 300);
    return () => clearTimeout(id);
  }, [q, load]);

  // merge live updates from other officers' screens, keeping whichever is newer
  const rows = useMemo(() => (data?.refuges || []).map((r) => {
    const u = liveUpdates?.[r.id];
    return u && (u.updated_at || '') >= (r.updated_at || '') ? { ...r, ...u } : r;
  }), [data, liveUpdates]);

  const setStatus = async (id, status) => {
    setBusyId(id);
    try {
      const r = await fetch(`${API_BASE}/api/v1/shelters/${id}/status?city=${city}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json', ...staffHeaders() },
        body: JSON.stringify({ status }) });
      const doc = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(doc.detail || t('error'));
      setData((d) => ({ ...d, refuges: d.refuges.map((x) => (x.id === id ? { ...x, ...doc } : x)) }));
    } catch (e) { setError(e.message || t('error')); } finally { setBusyId(null); }
  };

  const when = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '');
  return (
    <div className="glass-panel dec-card" style={{ marginTop: 16 }}>
      <h3>{t('refuges_title')}</h3>
      <div className="dec-note">{t('refuges_sub')}</div>
      {data && (
        <div className="band-row" style={{ marginTop: 8 }}>
          {[...STATUSES, 'unknown'].map((s) => (
            <span key={s} className={`pill ref-${s}`}>{t(`ref_${s}`)}: {data.counts[s] ?? 0}</span>))}
        </div>)}
      <input className="num" style={{ maxWidth: 320, marginTop: 8 }} placeholder={t('refuges_search')}
        value={q} onChange={(e) => setQ(e.target.value)} aria-label={t('refuges_search')} />
      {error && <div className="error-text" style={{ marginTop: 8 }}>{error}</div>}
      {data && (
        <div style={{ overflowX: 'auto' }}>
          <table className="dec-table" style={{ marginTop: 10 }}>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td><b>{r.name}</b><div className="dec-note">{r.type.replace('_', ' ')}</div></td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    <span className={`pill ref-${r.status}`}>{t(`ref_${r.status}`)}</span>
                    <div className="dec-note">{r.stale ? `${t('ref_stale')} (${t(`ref_${r.last_status}`)})`
                      : r.updated_at ? `${t('ref_updated')} ${when(r.updated_at)}` : ''}</div>
                  </td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {STATUSES.map((s) => (
                      <button key={s} className="btn-ghost" disabled={busyId === r.id}
                        aria-pressed={r.status === s}
                        style={{ marginRight: 6, padding: '4px 10px', fontWeight: r.status === s ? 700 : 400 }}
                        onClick={() => setStatus(r.id, s)}>{t(`ref_${s}`)}</button>))}
                  </td>
                </tr>))}
            </tbody>
          </table>
          {rows.length === 0 && <div className="dec-note" style={{ marginTop: 8 }}>—</div>}
        </div>)}
      <div className="dec-note" style={{ marginTop: 8 }}>{t('refuges_stale_note').replace('{h}', data?.stale_after_hours ?? 12)}</div>
    </div>);
}
