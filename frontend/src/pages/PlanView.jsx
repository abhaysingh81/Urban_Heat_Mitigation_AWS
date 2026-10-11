import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { API_BASE } from '../api';
import { useLang } from '../i18n';
import './Decision.css';

const KINDS = [
  ['tree_cover', 'Trees'], ['cool_roofs', 'Cool roofs'], ['shade_structures', 'Shade structures'],
  ['cool_pavement', 'Cool pavements'],
];
const fmtRange = (c) => `${c.high.toFixed(1)} to ${c.low.toFixed(1)}°C`;

export default function PlanView({ city, cityInfo }) {
  const { t } = useLang();
  const [params] = useSearchParams();
  const [crore, setCrore] = useState(50);
  const [equity, setEquity] = useState(0.5);
  const [survival, setSurvival] = useState(0.7);
  const [kinds, setKinds] = useState(KINDS.map(([k]) => k));
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState(null);
  const [ward, setWard] = useState(params.get('ward') || '');
  const [brief, setBrief] = useState(null);
  const [briefBusy, setBriefBusy] = useState(false);
  const real = cityInfo?.data_kind === 'real';

  if (!real) return <div className="page-container"><div className="glass-panel dec-card">{t('real_only')}</div></div>;

  const build = async () => {
    setBusy(true); setError(null); setBrief(null);
    try {
      const r = await fetch(`${API_BASE}/api/v1/plans/optimize?city=${city}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ budget_lakh: crore * 100, equity_weight: equity, tree_survival: survival,
                               interventions: kinds, compare: true, save: true }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || 'failed');
      const p = await r.json();
      setPlan(p); setStatus(p.status);
      if (!ward && p.by_ward[0]) setWard(p.by_ward[0].ward_id);
    } catch (e) { setError(String(e.message || e)); } finally { setBusy(false); }
  };

  const setPlanStatus = async (s) => {
    const r = await fetch(`${API_BASE}/api/v1/plans/${plan.plan_id}/status`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: s }) });
    if (r.ok) setStatus((await r.json()).status);
  };

  const makeBrief = async () => {
    setBriefBusy(true);
    try {
      const r = await fetch(`${API_BASE}/api/v1/brief?city=${city}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ward_id: ward, budget_lakh: crore * 100, equity_weight: equity }) });
      if (!r.ok) throw new Error((await r.json()).detail || 'failed');
      setBrief(await r.json());
    } catch (e) { setError(String(e.message || e)); } finally { setBriefBusy(false); }
  };

  const ic = plan?.impact_card;
  const cmp = plan?.equity_comparison;
  const pdf = brief?.pdf_url ? (brief.pdf_url.startsWith('http') ? brief.pdf_url : `${API_BASE}${brief.pdf_url}`) : null;

  return (
    <div className="page-container"><div className="page-content">
      <div className="page-header"><h1>{t('plan_title')}</h1><p>{t('plan_sub')}</p></div>
      <div className="dec-grid two" style={{ gridTemplateColumns: '340px 1fr' }}>
        <div className="glass-panel dec-card">
          <div className="field"><label><span>{t('budget')}</span><b>₹{crore} cr</b></label>
            <input type="range" min="5" max="500" step="5" value={crore} onChange={(e) => setCrore(+e.target.value)} /></div>
          <div className="field"><label><span>{t('equity')}</span><b>{equity.toFixed(2)}</b></label>
            <input type="range" min="0" max="1" step="0.05" value={equity} onChange={(e) => setEquity(+e.target.value)} />
            <span className="dec-note">{t('equity_hint')}</span></div>
          <div className="field"><label><span>{t('tree_survival')}</span><b>{Math.round(survival * 100)}%</b></label>
            <input type="range" min="0.2" max="1" step="0.05" value={survival} onChange={(e) => setSurvival(+e.target.value)} /></div>
          <div className="field"><label><span>{t('interventions')}</span></label>
            <div className="checks">{KINDS.map(([k, label]) => (
              <label key={k}><input type="checkbox" checked={kinds.includes(k)}
                onChange={(e) => setKinds((s) => e.target.checked ? [...s, k] : s.filter((x) => x !== k))} />{label}</label>))}
            </div></div>
          <button className="btn-primary" onClick={build} disabled={busy || kinds.length === 0}>{busy ? t('building') : t('build_plan')}</button>
          {error && <div className="error-text" style={{ marginTop: 10 }}>{error}</div>}
        </div>

        <div className="dec-grid">
          {!plan && <div className="glass-panel dec-card dec-note">{t('plan_sub')}</div>}
          {plan && (<>
            <div className="glass-panel dec-card">
              <div className="stat-row">
                <div className="stat"><div className="label">{t('spent')}</div><div className="value">₹{(ic.spent_lakh / 100).toFixed(1)} cr</div></div>
                <div className="stat"><div className="label">{t('people_protected')}</div><div className="value">{ic.people_protected.toLocaleString()}</div></div>
                <div className="stat"><div className="label">{t('cost_per_person')}</div><div className="value">{ic.cost_per_person_inr?.toLocaleString() ?? '—'}</div></div>
                <div className="stat"><div className="label">{t('cooling')}</div><div className="value" style={{ fontSize: 17 }}>{fmtRange(ic.cooling_c)}</div></div>
              </div>
              <div className="dec-note">{t('estimate_note')}</div>
              <ul className="dec-note" style={{ marginTop: 6, paddingLeft: 18 }}>{ic.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
              <div className="btn-row">
                <span className="pill">{t('status')}: {status}</span>
                {status === 'draft' && <button className="btn-ghost" onClick={() => setPlanStatus('approved')}>{t('approve')}</button>}
                {status === 'approved' && <button className="btn-ghost" onClick={() => setPlanStatus('implemented')}>{t('mark_done')}</button>}
                <a className="btn-ghost" href={`${API_BASE}/api/v1/plans/${plan.plan_id}/export?format=csv`}>{t('export_csv')}</a>
                <a className="btn-ghost" href={`${API_BASE}/api/v1/plans/${plan.plan_id}/export?format=geojson`}>{t('export_geojson')}</a>
              </div>
            </div>

            {cmp && (
              <div className="glass-panel dec-card dec-grid two">
                {[['efficiency_plan', cmp.efficiency], ['equity_plan', cmp.equity]].map(([label, c]) => (
                  <div key={label}><h3>{t(label)}</h3>
                    <div className="dec-note">{t('people_protected')}: <b>{c.people_protected.toLocaleString()}</b></div>
                    <div className="dec-note">{t('cooling')} (mid): <b>{c.cooling_mid_c}°C</b></div>
                    <div className="dec-note">{t('high_vuln_share')}: <b>{Math.round(c.high_vulnerability_spend_share * 100)}%</b></div>
                    <div className="dec-note">{t('beneficiary_vuln')}: <b>{Math.round(c.beneficiary_vulnerability * 100)}%</b></div>
                  </div>))}
              </div>)}

            <div className="glass-panel dec-card">
              <h3>{t('timeline')}</h3>
              <div style={{ height: 160 }}><ResponsiveContainer>
                <LineChart data={plan.timeline}><XAxis dataKey="year" /><YAxis /><Tooltip />
                  <Line type="monotone" dataKey="pop_weighted_cooling_mid_c" stroke="#3b82f6" dot={false} /></LineChart>
              </ResponsiveContainer></div>
            </div>

            <div className="glass-panel dec-card">
              <h3>{t('brief_for')}</h3>
              <div className="btn-row">
                <select value={ward} onChange={(e) => setWard(e.target.value)}>
                  {plan.by_ward.map((w) => <option key={w.ward_id} value={w.ward_id}>{w.ward_name}</option>)}
                </select>
                <button className="btn-primary" onClick={makeBrief} disabled={briefBusy || !ward}>{briefBusy ? t('building') : t('make_brief')}</button>
                {pdf && <a className="btn-ghost" href={pdf} target="_blank" rel="noreferrer">{t('download_pdf')}</a>}
              </div>
              {brief && (<>
                <div className="dec-note" style={{ marginTop: 8 }}>{t('source')}: {brief.source}{brief.note ? ` (${brief.note})` : ''} · numbers verified: {String(brief.numbers_verified)}</div>
                {brief.sources?.length > 0 && <div className="dec-note">{t('guidance_sources')}: {brief.sources.map((n, i) => `[S${i + 1}] ${n}`).join('; ')}</div>}
                <div className="brief-box">{brief.brief_en}</div>
                <div className="brief-box">{brief.brief_hi}</div>
              </>)}
            </div>

            <div className="glass-panel dec-card">
              <h3>{t('actions')} ({plan.items.length})</h3>
              <table className="dec-table"><thead><tr><th>{t('ward')}</th><th>Action</th><th>₹ lakh</th><th>{t('cooling')}</th></tr></thead>
                <tbody>{plan.items.slice(0, 20).map((i) => (
                  <tr key={i.grid_id + i.intervention}><td>{i.ward_name}</td><td>{i.label}</td><td>{i.cost_lakh}</td>
                    <td>{i.intervention === 'cooling_centre' ? '—' : fmtRange(i.cooling_c)}</td></tr>))}</tbody></table>
            </div>
          </>)}
        </div>
      </div>
    </div></div>
  );
}
