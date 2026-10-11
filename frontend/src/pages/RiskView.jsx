import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ScatterChart, Scatter, XAxis, YAxis, ZAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { API_BASE } from '../api';
import { useLang } from '../i18n';
import './Decision.css';

const riskColor = (v) => `hsl(${Math.round(55 - v * 0.55)}, 90%, 50%)`; // yellow -> red

export default function RiskView({ city, cityInfo }) {
  const { t } = useLang();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [data, setData] = useState(null);
  const [today, setToday] = useState(null);
  const [error, setError] = useState(null);
  const [sel, setSel] = useState(null);
  const real = cityInfo?.data_kind === 'real';

  useEffect(() => {
    if (!real) return;
    let off = false;
    const sim = params.get('simulate');
    const simStr = sim ? `&simulate=${sim}` : '';
    fetch(`${API_BASE}/api/v1/risk/wards?city=${city}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('risk'))))
      .then((d) => { if (!off) { setData(d); setSel(d.wards[0]?.ward_id); } })
      .catch(() => !off && setError(t('error')));
    fetch(`${API_BASE}/api/v1/risk/today?city=${city}${simStr}`)
      .then((r) => (r.ok ? r.json() : null)).then((d) => !off && setToday(d)).catch(() => {});
    return () => { off = true; };
  }, [city, real, t]);

  if (!real) return <div className="page-container"><div className="glass-panel dec-card">{t('real_only')}</div></div>;
  if (error) return <div className="page-container"><div className="error-text">{error}</div></div>;
  if (!data) return <div className="page-container"><div className="loading-spinner">{t('loading')}</div></div>;

  const wards = data.wards;
  const chosen = wards.find((w) => w.ward_id === sel);

  return (
    <div className="page-container"><div className="page-content">
      <div className="page-header"><h1>{data.method.boundary_type === 'official_boundaries' ? t('risk_title') : t('zone_title')}</h1><p>{t('risk_sub')}</p></div>

      {today && (
        <div className="glass-panel dec-card" style={{ marginBottom: 16 }}>
          {today.simulated && <div className="simulation-banner">SIMULATION</div>}
          <b>{t('today')}: </b><span className={`pill ${today.alert_level}`}>{today.alert_level.toUpperCase()}</span>{' '}
          {t('forecast_high')} {today.forecast_tmax_c}°C
          {today.stale && <span className="dec-note"> · {t('stale')} ({today.source})</span>}
        </div>
      )}

      <div className="dec-grid two">
        <div className="glass-panel dec-card">
          <h3>{data.method.boundary_type === 'official_boundaries' ? t('ward') : t('zone')}</h3>
          <div className="dec-note" style={{ marginBottom: 8 }}>{data.zones}</div>
          <div style={{ height: 320 }}>
            <ResponsiveContainer>
              <ScatterChart margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
                <XAxis type="number" dataKey="lon" domain={['dataMin', 'dataMax']} hide />
                <YAxis type="number" dataKey="lat" domain={['dataMin', 'dataMax']} hide />
                <ZAxis type="number" dataKey="population" range={[30, 260]} />
                <Tooltip cursor={false} content={({ payload }) => payload?.length ? (
                  <div className="glass-panel" style={{ padding: 10 }}>
                    <b>{payload[0].payload.ward_name}</b><br />{t('risk')}: {payload[0].payload.risk_score}
                  </div>) : null} />
                <Scatter data={wards} onClick={(p) => setSel(p.ward_id)}>
                  {wards.map((w) => <Cell key={w.ward_id} fill={riskColor(w.risk_score)}
                    stroke={w.ward_id === sel ? '#fff' : 'none'} strokeWidth={2} />)}
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <div className="dec-note">{data.method.formula}</div>
        </div>

        <div className="glass-panel dec-card">
          {chosen && (<>
            <h3>{chosen.ward_name} — #{chosen.rank} {t('of')} {data.n_wards}</h3>
            <div className="stat-row">
              <div className="stat"><div className="label">{t('risk')}</div><div className="value">{chosen.risk_score}</div></div>
              <div className="stat"><div className="label">{t('avg_temp')}</div><div className="value">{chosen.lst_mean.toFixed(1)}°C</div></div>
              <div className="stat"><div className="label">{t('people')}</div><div className="value">{chosen.population.toLocaleString()}</div></div>
            </div>
            {['hazard', 'exposure', 'vulnerability'].map((k) => (
              <div key={k} className="field"><label><span>{k}</span><span>{Math.round(chosen[k] * 100)}%</span></label>
                <div className="bar"><span style={{ width: `${chosen[k] * 100}%` }} /></div></div>
            ))}
            <div className="dec-note">Not included: {data.method.not_included.join(', ')}.</div>
            <div className="btn-row">
              <button className="btn-primary" onClick={() => navigate(`/plan?ward=${chosen.ward_id}`)}>{t('select_ward')}</button>
              <a className="btn-ghost" href={`${API_BASE}/api/v1/risk/wards.csv?city=${city}`}>{t('export_csv')}</a>
            </div>
          </>)}
        </div>
      </div>

      <div className="glass-panel dec-card" style={{ marginTop: 20 }}>
        <table className="dec-table">
          <thead><tr><th>{t('rank')}</th><th>{data.method.boundary_type === 'official_boundaries' ? t('ward') : t('zone')}</th><th>{t('risk')}</th><th>{t('heat')}</th><th>{t('people')}</th><th>{t('vulnerability')}</th></tr></thead>
          <tbody>
            {wards.slice(0, 25).map((w) => (
              <tr key={w.ward_id} className={`click${w.ward_id === sel ? ' sel' : ''}`} onClick={() => setSel(w.ward_id)}>
                <td>{w.rank}</td><td>{w.ward_name}</td>
                <td style={{ minWidth: 120 }}><div className="bar"><span style={{ width: `${w.risk_score}%` }} /></div></td>
                <td>{w.lst_mean.toFixed(1)}°C</td><td>{w.population.toLocaleString()}</td><td>{Math.round(w.vulnerability * 100)}%</td>
              </tr>))}
          </tbody>
        </table>
      </div>
    </div></div>
  );
}
