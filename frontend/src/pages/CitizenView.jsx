import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { API_BASE } from '../api';
import { useLang } from '../i18n';
import './Decision.css';

// Mobile-first, standalone page (no sidebar): "what do I do today?"
export default function CitizenView({ cities }) {
  const { lang, setLang, t } = useLang();
  const [params] = useSearchParams();
  const city = params.get('city') || 'new_delhi';
  const info = cities.find((c) => c.id === city);
  const [pos, setPos] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [sent, setSent] = useState(false);

  const load = useCallback((p) => {
    fetch(`${API_BASE}/api/v1/citizen?city=${city}&lat=${p.lat}&lon=${p.lon}`)
      .then((r) => (r.ok ? r.json() : r.json().then((j) => Promise.reject(new Error(j.detail)))))
      .then((d) => { setError(null); setData(d); }).catch((e) => setError(e.message || t('error')));
  }, [city, t]);

  useEffect(() => {
    if (!info) return;
    const p = pos || { lat: info.center[1], lon: info.center[0] };
    load(p);
  }, [info, pos, load]);

  const locate = () => navigator.geolocation?.getCurrentPosition(
    (g) => setPos({ lat: g.coords.latitude, lon: g.coords.longitude }),
    () => setError('Location permission denied; showing the city centre.'));

  const report = async (kind) => {
    const p = pos || { lat: info.center[1], lon: info.center[0] };
    const r = await fetch(`${API_BASE}/api/v1/reports?city=${city}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...p, kind }) });
    if (r.ok) setSent(true);
  };

  return (
    <div className="citizen">
      <div className="lang">
        {['en', 'hi'].map((l) => <button key={l} className="btn-ghost" style={l === lang ? { background: 'var(--accent-primary)', color: '#fff' } : {}}
          onClick={() => setLang(l)}>{l === 'en' ? 'English' : 'हिंदी'}</button>)}
      </div>
      <h1 style={{ fontSize: 22 }}>{t('citizen_title')} — {info?.name}</h1>
      {error && <div className="error-text">{error}</div>}
      {data && (<>
        <div className={`hero ${data.alert_level}`}>
          <span className={`pill ${data.alert_level}`}>{data.alert_level.toUpperCase()}</span>
          <h2>{data.forecast_tmax_c != null ? `${data.forecast_tmax_c}°C` : ''}</h2>
          <p>{lang === 'hi' ? data.message_hi : data.message_en}</p>
          {data.stale && <div className="dec-note">{t('stale')}</div>}
        </div>
        {data.ward && <div className="dec-note" style={{ margin: '10px 4px' }}>{t('ward_rank_line')}: #{data.ward.rank} {t('of')} {data.ward.of_wards} — {data.ward.ward_name}</div>}
        {data.advisory_audio_url && (
          <div style={{ marginTop: 10 }}><div className="dec-note">{t('listen')}</div>
            <audio controls src={data.advisory_audio_url} style={{ width: '100%' }} /></div>)}
        <button className="btn-primary big-btn" onClick={locate}>{t('use_location')}</button>

        <h3 style={{ margin: '18px 4px 4px' }}>{t('nearest_cool')}</h3>
        {data.nearest_cooling_spots.length === 0 && <div className="dec-note">—</div>}
        {data.nearest_cooling_spots.map((s) => (
          <div key={s.name + s.lat} className="glass-panel spot">
            <div><b>{s.name}</b><div className="dec-note">{s.type.replace('_', ' ')} · {s.distance_m} {t('away')}</div></div>
            <a href={`https://www.google.com/maps/dir/?api=1&destination=${s.lat},${s.lon}&travelmode=walking`} target="_blank" rel="noreferrer">{t('directions')}</a>
          </div>))}

        <h3 style={{ margin: '18px 4px 4px' }}>{t('report_title')}</h3>
        {sent ? <div className="dec-banner ok glass-panel">{t('thanks')}</div> : (
          ['no_shade', 'no_water', 'very_hot'].map((k) => (
            <button key={k} className="btn-ghost big-btn" onClick={() => report(k)}>{t(k)}</button>)))}
      </>)}
    </div>
  );
}
