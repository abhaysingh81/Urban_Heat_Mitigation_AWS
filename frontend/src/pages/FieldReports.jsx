import { useState, useEffect, useCallback, useRef } from 'react';
import { API_BASE } from '../api';
import { useLang } from '../i18n';
import { loadConfig, staffHeaders, staffSession, signOut } from '../platform';
import StaffSignIn from '../components/StaffSignIn';
import RefugePanel from '../components/RefugePanel';
import VoiceContactsPanel from '../components/VoiceContactsPanel';
import './Decision.css';

const NEXT = { new: ['verified', 'rejected'], verified: ['dispatched', 'resolved'], dispatched: ['resolved'], resolved: [], rejected: [] };
const POLL_MS = 30000;

// Ward-officer screen: citizen reports for the selected city, newest first. Officers verify a
// report, record that help was dispatched, and close it. With the WebSocket API deployed new
// reports appear by themselves; otherwise the list refreshes on a timer.
export default function FieldReports({ city, cityInfo }) {
  const { t } = useLang();
  const [cfg, setCfg] = useState(null);
  const [session, setSession] = useState(staffSession());
  const [reports, setReports] = useState([]);
  const [error, setError] = useState(null);
  const [denied, setDenied] = useState(false);   // signed in, but without an officer or planner role
  const [live, setLive] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [shelterUpdates, setShelterUpdates] = useState({});   // refuge id -> latest live status
  const [wards, setWards] = useState([]);                       // for the phone-call contacts panel
  useEffect(() => {
    if (!cfg?.voice_calls) return undefined;
    let active = true;
    fetch(`${API_BASE}/api/v1/risk/wards?city=${city}`).then((r) => r.json())
      .then((d) => active && setWards(d.wards || [])).catch(() => {});
    return () => { active = false; };
  }, [cfg, city]);
  const cityRef = useRef(city);
  useEffect(() => { cityRef.current = city; }, [city]);

  useEffect(() => { loadConfig().then(setCfg); }, []);
  const cognito = cfg?.auth.mode === 'cognito';
  const needSignIn = (cognito && !session) || denied;

  const load = useCallback(async () => {
    if (!cfg || (cognito && !session)) return;
    try {
      const r = await fetch(`${API_BASE}/api/v1/reports?city=${city}`, { headers: staffHeaders() });
      if (r.status === 401 || r.status === 403) {
        const j = await r.json().catch(() => ({}));
        if (r.status === 401) { signOut(); setSession(null); } else { setDenied(true); }
        setError(r.status === 403 ? j.detail : null); return;
      }
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || t('error'));
      setReports((await r.json()).reports); setDenied(false); setError(null); setLoaded(true);
    } catch (e) { setError(e.message || t('error')); }
  }, [cfg, cognito, session, city, t]);

  useEffect(() => {
    let active = true;
    Promise.resolve().then(() => active && load());   // first load, and again when city or session changes
    return () => { active = false; };
  }, [load]);

  // live feed (Feature L) with a timer as the fallback
  useEffect(() => {
    if (!cfg || needSignIn) return undefined;
    const url = cfg.live.ws_url;
    if (!url) { const iv = setInterval(load, POLL_MS); return () => clearInterval(iv); }
    let ws, ping, retry, closed = false;
    const connect = () => {
      const s = staffSession();
      ws = new WebSocket(s ? `${url}?token=${encodeURIComponent(s.access_token)}` : url);
      ws.onopen = () => { setLive(true); ping = setInterval(() => ws.readyState === 1 && ws.send('{"action":"ping"}'), 240000); };
      ws.onmessage = (m) => {
        let ev; try { ev = JSON.parse(m.data); } catch { return; }
        if (ev.type === 'shelter.updated') {
          if (ev.city_id === cityRef.current && ev.shelter) setShelterUpdates((m) => ({ ...m, [ev.shelter.id]: ev.shelter }));
          return;
        }
        const rep = ev.report;
        if (!rep || rep.city_id !== cityRef.current) return;
        setReports((old) => (ev.type === 'report.created' && !old.some((r) => r.id === rep.id)
          ? [{ note: '', audit: [], ...rep }, ...old]
          : old.map((r) => (r.id === rep.id ? { ...r, ...rep } : r))));
      };
      ws.onclose = () => { setLive(false); clearInterval(ping); if (!closed) retry = setTimeout(connect, 5000); };
      ws.onerror = () => ws.close();
    };
    connect();
    const iv = setInterval(load, POLL_MS * 4);   // slow safety net behind the live feed
    return () => { closed = true; clearInterval(ping); clearInterval(iv); clearTimeout(retry); ws?.close(); };
  }, [cfg, needSignIn, load]);

  const setStatus = async (id, status) => {
    const r = await fetch(`${API_BASE}/api/v1/reports/${id}/status`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', ...staffHeaders() }, body: JSON.stringify({ status }) });
    if (r.ok) { const doc = await r.json(); setReports((old) => old.map((x) => (x.id === id ? doc : x))); }
    else { setError((await r.json().catch(() => ({}))).detail || t('error')); }
  };

  const open = reports.filter((r) => !['resolved', 'rejected'].includes(r.status)).length;
  return (
    <div className="page-container" style={{ padding: 24, overflowY: 'auto', height: '100%' }}>
      <div className="page-header">
        <h1>{t('reports_title')} — {cityInfo?.name}</h1>
        <p>{t('reports_sub')}</p>
      </div>
      {cognito && <div className="glass-panel dec-card" style={{ marginTop: 16 }}>
        <StaffSignIn auth={cfg.auth} onChange={(s) => { setSession(s); setDenied(false); if (!s) setReports([]); }} />
        {!session && <div className="dec-note" style={{ marginTop: 6 }}>{t('reports_sign_in')}</div>}
      </div>}
      {error && <div className="error-text" style={{ marginTop: 12 }}>{error}</div>}
      {!needSignIn && (
        <div className="glass-panel dec-card" style={{ marginTop: 16 }}>
          <div className="dec-note">
            {reports.length} {t('reports_count')} · {open} {t('reports_open')} · {live ? t('live_on') : t('live_off')}
          </div>
          {loaded && reports.length === 0 && <div className="dec-note" style={{ marginTop: 10 }}>{t('reports_none')}</div>}
          {reports.length > 0 && (
            <div style={{ overflowX: 'auto' }}>
              <table className="dec-table" style={{ marginTop: 10 }}>
                <thead><tr><th>{t('rep_time')}</th><th>{t('rep_kind')}</th><th>{t('rep_cell')}</th><th>{t('rep_status')}</th><th>{t('rep_action')}</th></tr></thead>
                <tbody>
                  {reports.map((r) => (
                    <tr key={r.id}>
                      <td style={{ whiteSpace: 'nowrap' }}>{new Date(r.created_at).toLocaleString()}</td>
                      <td>{t(r.kind)}{r.has_photo ? ' · 📷' : ''}{r.note ? <div className="dec-note">{r.note}</div> : null}</td>
                      <td>{r.grid_id}</td>
                      <td><span className={`pill rep-${r.status}`}>{t(`st_${r.status}`)}</span></td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        {(NEXT[r.status] || []).map((s) => (
                          <button key={s} className="btn-ghost" style={{ marginRight: 6, padding: '4px 10px' }} onClick={() => setStatus(r.id, s)}>{t(`do_${s}`)}</button>))}
                      </td>
                    </tr>))}
                </tbody>
              </table>
            </div>)}
          <div className="dec-note" style={{ marginTop: 10 }}>{t('reports_privacy')}</div>
        </div>)}
      {!needSignIn && <RefugePanel key={city} city={city} liveUpdates={shelterUpdates} />}
      {/* only collected where calls are actually switched on: no phone numbers without a purpose */}
      {!needSignIn && cfg?.voice_calls && <VoiceContactsPanel key={`v-${city}`} city={city} wards={wards} />}
    </div>);
}
