import { Fragment, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { API_BASE } from '../api';
import { useLang } from '../i18n';
import CityMap from '../components/CityMap';
import { riskRgb, coolRgb } from '../components/mapColors';
import ConditionsPanel from '../components/ConditionsPanel';
import { DEFAULT_CONDITIONS } from '../components/conditionsDefaults';
import StaffSignIn from '../components/StaffSignIn';
import { loadConfig, staffHeaders } from '../platform';
import './Decision.css';
import './Lab.css';

const GROUPS = [['hazard', 'Heat hazard'], ['exposure', 'Exposure'], ['sensitivity', 'Sensitivity'], ['coping', 'Low coping capacity']];
const OBJECTIVES = [
  ['equity', 'Equity', 'Cool the most vulnerable people per rupee'],
  ['people', 'People', 'Cool the most people per rupee'],
  ['risk', 'Ward risk', 'Put money where ward risk is highest'],
  ['cooling', 'Hottest places', 'Cool the hottest cells, regardless of people'],
];
const cr = (l) => `₹${(l / 100).toLocaleString(undefined, { maximumFractionDigits: 1 })} cr`;
const pct = (x) => `${Math.round(x * 100)}%`;

export default function WardPlanner({ city, cityInfo }) {
  const { t } = useLang();
  const [params] = useSearchParams();
  const [step, setStep] = useState('risk');
  const [grid, setGrid] = useState(null);
  const [lib, setLib] = useState([]);
  const [conditions, setConditions] = useState(DEFAULT_CONDITIONS);
  // risk
  const [preset, setPreset] = useState('balanced');
  const [weights, setWeights] = useState(null);
  const [profile, setProfile] = useState(null);
  const [sel, setSel] = useState(params.get('ward') || null);
  const [mustW, setMustW] = useState([]);
  const [skipW, setSkipW] = useState([]);
  // plan
  const [crore, setCrore] = useState(50);
  const [years, setYears] = useState(3);
  const [objective, setObjective] = useState('equity');
  const [kinds, setKinds] = useState(null);
  const [caps, setCaps] = useState({});
  const [accessShare, setAccessShare] = useState(0.15);
  const [wardMin, setWardMin] = useState(0);
  const [wardMax, setWardMax] = useState(0.25);
  const [typeMax, setTypeMax] = useState(0.4);
  const [waterOn, setWaterOn] = useState(false);
  const [water, setWater] = useState(2000);
  const [survival, setSurvival] = useState(0.7);
  const [plan, setPlan] = useState(null);
  const [status, setStatus] = useState(null);
  const [token, setToken] = useState(() => { try { return sessionStorage.getItem('officer-token') || ''; } catch { return ''; } });
  // how plan approval is protected on this deployment: Cognito sign-in, a shared token, or open (local)
  const [authCfg, setAuthCfg] = useState(null);
  const [, setStaff] = useState(null);   // re-render after sign-in / sign-out
  useEffect(() => { loadConfig().then((c) => setAuthCfg(c.auth)); }, []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [briefWard, setBriefWard] = useState('');
  const [brief, setBrief] = useState(null);
  const [briefBusy, setBriefBusy] = useState(false);

  useEffect(() => {
    let off = false;
    fetch(`${API_BASE}/api/v1/grid?city=${city}`).then((r) => r.json()).then((g) => !off && setGrid(g)).catch(() => {});
    fetch(`${API_BASE}/api/v1/lab/interventions`).then((r) => r.json()).then((d) => {
      if (off) return; setLib(d.interventions); setKinds(d.interventions.map((i) => i.key));
    }).catch(() => {});
    return () => { off = true; };
  }, [city]);

  useEffect(() => {
    let off = false;
    const q = new URLSearchParams({ city, preset, power_cut: conditions.power_cut, water_shortage: conditions.water_shortage });
    if (weights) Object.entries(weights).forEach(([k, v]) => q.set(`w_${k}`, v));
    fetch(`${API_BASE}/api/v1/planner/wards?${q}`).then((r) => (r.ok ? r.json() : Promise.reject(new Error('wards'))))
      .then((d) => { if (!off) { setProfile(d); setSel((s) => s || d.wards[0]?.ward_id); } })
      .catch(() => !off && setError(t('error')));
    return () => { off = true; };
  }, [city, preset, weights, conditions.power_cut, conditions.water_shortage, t]);

  const wardRisk = useMemo(() => Object.fromEntries((profile?.wards || []).map((w) => [w.ward_id, w])), [profile]);
  const planCells = useMemo(() => {
    const m = {};
    (plan?.items || []).forEach((i) => { m[i.grid_id] = Math.min(m[i.grid_id] ?? 0, i.cooling_c.mid); });
    return m;
  }, [plan]);

  if (cityInfo?.data_kind !== 'real') return <div className="page-container"><div className="glass-panel dec-card">{t('real_only')}</div></div>;
  if (!profile) return <div className="page-container"><div className="loading-spinner">{error || t('loading')}</div></div>;

  const chosen = wardRisk[sel];
  const w = weights || profile.weights;
  const toggle = (list, setList, id, other, setOther) => {
    setList(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
    if (other.includes(id)) setOther(other.filter((x) => x !== id));
  };

  const build = async () => {
    setBusy(true); setError(null); setBrief(null);
    try {
      const body = {
        budget_lakh: crore * 100, years, objective, interventions: kinds, access_share: accessShare,
        ward_min_share: wardMin, ward_max_share: wardMax, type_max_share: typeMax,
        unit_caps: Object.fromEntries(Object.entries(caps).filter(([, v]) => v !== '' && v != null).map(([k, v]) => [k, +v])),
        mandatory_wards: mustW, excluded_wards: skipW, water_budget_kl_day: waterOn ? water : null,
        survival, preset, conditions: { ...conditions, tmax_c: conditions.mode === 'custom' ? conditions.tmax_c : null },
        compare: true, save: true,
      };
      const r = await fetch(`${API_BASE}/api/v1/planner/plan?city=${city}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const p = await r.json();
      if (!r.ok) throw new Error(typeof p.detail === 'string' ? p.detail : 'Plan failed — check the inputs.');
      setPlan(p); setStatus(p.status); setBriefWard(p.work_orders[0]?.ward_id || '');
    } catch (e) { setError(String(e.message || e)); } finally { setBusy(false); }
  };

  const setPlanStatus = async (s) => {
    try { sessionStorage.setItem('officer-token', token); } catch { /* storage may be blocked */ }
    const r = await fetch(`${API_BASE}/api/v1/plans/${plan.plan_id}/status`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', ...staffHeaders(token) },
      body: JSON.stringify({ status: s }) });
    const d = await r.json();
    if (r.ok) setStatus(d.status); else setError(d.detail || 'Status change failed');
  };

  const makeBrief = async () => {
    setBriefBusy(true);
    try {
      const r = await fetch(`${API_BASE}/api/v1/brief?city=${city}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ward_id: briefWard, budget_lakh: crore * 100, equity_weight: objective === 'equity' ? 0.8 : 0.3 }) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'failed');
      setBrief(d);
    } catch (e) { setError(String(e.message || e)); } finally { setBriefBusy(false); }
  };

  const ic = plan?.impact_card;
  const pdf = brief?.pdf_url ? (brief.pdf_url.startsWith('http') ? brief.pdf_url : `${API_BASE}${brief.pdf_url}`) : null;

  return (
    <div className="page-container"><div className="page-content">
      <div className="page-header"><h1>Ward Planner</h1>
        <p>Rank wards on 12 heat-risk factors, then turn a phased budget into ward-by-ward work orders.</p></div>

      <div className="steps">
        <button className={step === 'risk' ? 'on' : ''} onClick={() => setStep('risk')}>1 · Ward risk<small>Who needs help first, and why</small></button>
        <button className={step === 'plan' ? 'on' : ''} onClick={() => setStep('plan')}>2 · City plan<small>Budget, rules, work orders{mustW.length + skipW.length ? ` · ${mustW.length} must, ${skipW.length} excluded` : ''}</small></button>
      </div>

      <div className="lab-layout">
        <div className="dec-grid">
          <ConditionsPanel city={city} value={conditions} onChange={setConditions} compact />

          {step === 'risk' && (
            <div className="glass-panel dec-card">
              <h3>How to weigh risk</h3>
              <select value={preset} onChange={(e) => { setPreset(e.target.value); setWeights(null); }} style={{ width: '100%', margin: '6px 0 10px' }}>
                <option value="balanced">Balanced</option><option value="heat_first">Heat first</option>
                <option value="equity_first">Equity first</option><option value="access_first">Access to cooling and water first</option>
              </select>
              {GROUPS.map(([g, label]) => (
                <div key={g} className="field"><label><span>{label}</span><b>{pct(w[g])}</b></label>
                  <input type="range" min="0" max="1" step="0.05" value={w[g]}
                    onChange={(e) => setWeights({ ...w, [g]: +e.target.value })} /></div>))}
              <div className="dec-note">Weights are re-normalised to 100%. A power cut raises the sensitivity weight by half.</div>
            </div>)}

          {step === 'plan' && (<>
            <div className="glass-panel dec-card">
              <h3>Budget and goal</h3>
              <div className="field"><label><span>Capital budget</span><b>₹{crore} cr</b></label>
                <input type="range" min="5" max="1000" step="5" value={crore} onChange={(e) => setCrore(+e.target.value)} /></div>
              <div className="field"><label><span>Phased over</span><b>{years} year{years > 1 ? 's' : ''}</b></label>
                <input type="range" min="1" max="5" value={years} onChange={(e) => setYears(+e.target.value)} /></div>
              <div className="field"><label><span>Objective</span></label>
                <select value={objective} onChange={(e) => setObjective(e.target.value)}>
                  {OBJECTIVES.map(([k, l, d]) => <option key={k} value={k}>{l} — {d}</option>)}</select></div>
            </div>
            <div className="glass-panel dec-card">
              <h3>Rules</h3>
              <div className="field"><label><span>Max share of budget per ward</span><b>{pct(wardMax)}</b></label>
                <input type="range" min="0.02" max="0.5" step="0.01" value={wardMax} onChange={(e) => setWardMax(+e.target.value)} /></div>
              <div className="field"><label><span>Minimum per included ward (equity floor)</span><b>{(wardMin * 100).toFixed(2)}%</b></label>
                <input type="range" min="0" max="0.005" step="0.0005" value={wardMin} onChange={(e) => setWardMin(+e.target.value)} /></div>
              <div className="field"><label><span>Max share per intervention type</span><b>{pct(typeMax)}</b></label>
                <input type="range" min="0.1" max="1" step="0.05" value={typeMax} onChange={(e) => setTypeMax(+e.target.value)} /></div>
              <div className="field"><label><span>Reserved for cooling centres + water points</span><b>{pct(accessShare)}</b></label>
                <input type="range" min="0" max="0.4" step="0.01" value={accessShare} onChange={(e) => setAccessShare(+e.target.value)} /></div>
              <label className="dec-note"><input type="checkbox" checked={waterOn} onChange={(e) => setWaterOn(e.target.checked)} /> Cap extra water use</label>
              {waterOn && <div className="field"><label><span>Water budget</span><b>{water.toLocaleString()} kL/day</b></label>
                <input type="range" min="50" max="20000" step="50" value={water} onChange={(e) => setWater(+e.target.value)} /></div>}
              <div className="field"><label><span>Tree / park survival</span><b>{pct(survival)}</b></label>
                <input type="range" min="0.3" max="1" step="0.05" value={survival} onChange={(e) => setSurvival(+e.target.value)} /></div>
              <div className="dec-note">Mandatory: {mustW.length ? mustW.map((x) => wardRisk[x]?.ward_name || x).join(', ') : 'none'} · Excluded: {skipW.length ? skipW.map((x) => wardRisk[x]?.ward_name || x).join(', ') : 'none'} (set in step 1)</div>
            </div>
            <div className="glass-panel dec-card">
              <h3>Allowed interventions <span className="dec-note">(optional city-wide cap)</span></h3>
              {lib.map((iv) => (
                <div key={iv.key} className="grid2" style={{ alignItems: 'center', marginBottom: 6 }}>
                  <label className="iv-head" style={{ fontSize: 13 }}><input type="checkbox" checked={kinds?.includes(iv.key) || false}
                    onChange={(e) => setKinds((s) => (e.target.checked ? [...s, iv.key] : s.filter((x) => x !== iv.key)))} />{iv.label}</label>
                  {!['cooling_centres', 'water_atms'].includes(iv.key) &&
                    <input className="num" type="number" min="0" placeholder={`max ${iv.unit}`} value={caps[iv.key] ?? ''}
                      onChange={(e) => setCaps((c) => ({ ...c, [iv.key]: e.target.value }))} />}
                </div>))}
              <button className="btn-primary" style={{ width: '100%', marginTop: 8 }} onClick={build} disabled={busy || !kinds?.length}>{busy ? t('building') : t('build_plan')}</button>
              {error && <div className="error-text" style={{ marginTop: 8 }}>{error}</div>}
            </div>
          </>)}
        </div>

        <div className="dec-grid">
          {step === 'risk' && (<>
            <div className="glass-panel dec-card">
              <div className="band-row">{['severe', 'high', 'moderate', 'low'].map((b) => <span key={b} className={`band ${b}`}>{b}: <b>{profile.bands[b]}</b> wards</span>)}</div>
              {grid && <CityMap grid={grid} center={cityInfo?.center} updateKey={JSON.stringify(profile.weights) + sel}
                colorOf={(p) => { const r = wardRisk[p.ward_id]; if (!r) return null; return p.ward_id === sel ? [80, 160, 255] : riskRgb(r.risk_score); }}
                tooltipOf={(p) => { const r = wardRisk[p.ward_id]; return r ? `${r.ward_name} · #${r.rank}\nrisk ${r.risk_score} (${r.band})` : null; }}
                onPick={(p) => p.ward_id && setSel(p.ward_id)} />}
              <div className="dec-note" style={{ marginTop: 6 }}>{profile.method}</div>
            </div>

            {chosen && (
              <div className="glass-panel dec-card">
                <h3>{chosen.ward_name} — #{chosen.rank} of {profile.n_wards} <span className={`band ${chosen.band}`}>{chosen.band}</span></h3>
                <div className="stat-row">
                  <div className="stat"><div className="label">Risk score</div><div className="value">{chosen.risk_score}</div></div>
                  <div className="stat"><div className="label">People</div><div className="value sm">{Math.round(chosen.factors.population).toLocaleString()}</div></div>
                  <div className="stat"><div className="label">Mean surface temp</div><div className="value sm">{chosen.factors.lst_mean?.toFixed(1)}°C</div></div>
                </div>
                <div className="dec-note">Why it ranks here: {chosen.drivers.map((d) => `${d.label} (top ${Math.max(1, Math.round((1 - d.percentile) * 100))}%)`).join(' · ')}</div>
                <div className="group-bars">{GROUPS.map(([g, label]) => (<Fragment key={g}>
                  <span>{label}</span><div className="bar"><span style={{ width: pct(chosen.groups[g]) }} /></div><span>{pct(chosen.groups[g])}</span></Fragment>))}</div>
                <div className="factor-list">{GROUPS.map(([g, label]) => (<Fragment key={g}>
                  <span className="g">{label}</span>
                  {profile.factors.filter((f) => f.group === g).map((f) => (<Fragment key={f.key}>
                    <span>{f.label}</span>
                    <b>{chosen.factors[f.key] == null ? '—' : Number(chosen.factors[f.key]).toLocaleString(undefined, { maximumFractionDigits: 2 })}</b>
                    <div className="bar" title="How this ward compares with the rest of the city (longer = riskier)"><span style={{ width: pct(chosen.percentiles[f.key]) }} /></div></Fragment>))}</Fragment>))}</div>
                <div className="btn-row">
                  <button className="btn-ghost" onClick={() => toggle(mustW, setMustW, chosen.ward_id, skipW, setSkipW)}>{mustW.includes(chosen.ward_id) ? 'Remove from mandatory' : 'Must fund this ward'}</button>
                  <button className="btn-ghost" onClick={() => toggle(skipW, setSkipW, chosen.ward_id, mustW, setMustW)}>{skipW.includes(chosen.ward_id) ? 'Include again' : 'Exclude from plan'}</button>
                  <button className="btn-primary" onClick={() => setStep('plan')}>Plan the city →</button>
                </div>
              </div>)}

            <div className="glass-panel dec-card">
              <table className="dec-table"><thead><tr><th>#</th><th>Ward</th><th>Risk</th><th>Band</th>{GROUPS.map(([g, l]) => <th key={g}>{l}</th>)}<th>People</th></tr></thead>
                <tbody>{profile.wards.slice(0, 30).map((r) => (
                  <tr key={r.ward_id} className={`click${r.ward_id === sel ? ' sel' : ''}`} onClick={() => setSel(r.ward_id)}>
                    <td>{r.rank}</td><td>{r.ward_name}{mustW.includes(r.ward_id) && <span className="tag must">must</span>}{skipW.includes(r.ward_id) && <span className="tag skip">excluded</span>}</td>
                    <td>{r.risk_score}</td><td><span className={`band ${r.band}`}>{r.band}</span></td>
                    {GROUPS.map(([g]) => <td key={g} style={{ minWidth: 70 }}><div className="bar"><span style={{ width: pct(r.groups[g]) }} /></div></td>)}
                    <td>{Math.round(r.factors.population).toLocaleString()}</td></tr>))}</tbody></table>
              <div className="btn-row"><a className="btn-ghost" href={`${API_BASE}/api/v1/risk/wards.csv?city=${city}`}>{t('export_csv')}</a></div>
            </div>
          </>)}

          {step === 'plan' && !plan && <div className="glass-panel dec-card dec-note">Set the budget, objective and rules on the left, then build the plan. Mandatory and excluded wards come from step 1.</div>}
          {step === 'plan' && plan && (<>
            <div className="glass-panel dec-card">
              <div className="stat-row">
                <div className="stat"><div className="label">Spent / budget</div><div className="value sm">{cr(ic.spent_lakh)} / {cr(ic.budget_lakh)}</div></div>
                <div className="stat"><div className="label">{t('people_protected')}</div><div className="value sm">{ic.people_protected.toLocaleString()}</div></div>
                <div className="stat"><div className="label">₹ per person</div><div className="value sm">{ic.cost_per_person_inr?.toLocaleString() ?? '—'}</div></div>
                <div className="stat"><div className="label">Surface cooling</div><div className="value sm">{ic.cooling_c.high} to {ic.cooling_c.low}°C</div></div>
                <div className="stat"><div className="label">Feels-like</div><div className="value sm">{ic.feels_like_c.before}→{ic.feels_like_c.after}°C</div></div>
                <div className="stat"><div className="label">Upkeep / 10-yr cost</div><div className="value sm">{cr(ic.opex_lakh_yr)}/yr · {cr(ic.ten_year_cost_lakh)}</div></div>
                <div className="stat"><div className="label">Water</div><div className="value sm">{ic.water_kl_day.toLocaleString()} kL/day</div></div>
                <div className="stat"><div className="label">Wards funded</div><div className="value sm">{ic.wards_funded}</div></div>
              </div>
              <div className="band-row">{['severe', 'high', 'moderate', 'low'].map((b) => (
                <span key={b} className={`band ${b}`}>{b}: {ic.wards_by_band.before[b] || 0} → <b>{ic.wards_by_band.after[b] || 0}</b></span>))}
                <span className="band">people in hotspots: {ic.people_in_hotspots.before.toLocaleString()} → <b>{ic.people_in_hotspots.after.toLocaleString()}</b></span></div>
              <ul className="dec-note" style={{ paddingLeft: 18 }}>{ic.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
              {authCfg?.mode === 'cognito' && (<>
                <div className="dec-note">{t('planner_sign_in')}</div>
                <StaffSignIn auth={authCfg} onChange={setStaff} />
              </>)}
              <div className="btn-row" style={{ alignItems: 'center' }}>
                <span className="pill">{t('status')}: {status}</span>
                {authCfg?.mode === 'token' && <input className="num" style={{ width: 160 }} type="password" placeholder="Officer token" value={token} onChange={(e) => setToken(e.target.value)} />}
                {status === 'draft' && <button className="btn-ghost" onClick={() => setPlanStatus('approved')}>{t('approve')}</button>}
                {status === 'approved' && <button className="btn-ghost" onClick={() => setPlanStatus('implemented')}>{t('mark_done')}</button>}
                <a className="btn-ghost" href={`${API_BASE}/api/v1/planner/plan/${plan.plan_id}/work-orders.csv`}>Work orders CSV</a>
                <a className="btn-ghost" href={`${API_BASE}/api/v1/plans/${plan.plan_id}/export?format=csv`}>Sites CSV</a>
                <a className="btn-ghost" href={`${API_BASE}/api/v1/plans/${plan.plan_id}/export?format=geojson`}>{t('export_geojson')}</a>
              </div>
            </div>

            {plan.objective_comparison && (
              <div className="glass-panel dec-card">
                <h3>Same budget, different goals</h3>
                <table className="dec-table"><thead><tr><th>Objective</th><th>People protected</th><th>Cooling (mid)</th><th>₹/person</th><th>Spend in vulnerable cells</th><th>Severe wards after</th><th>People in hotspots after</th></tr></thead>
                  <tbody>{plan.objective_comparison.map((o) => (
                    <tr key={o.objective} className={o.objective === objective ? 'sel' : ''}><td>{OBJECTIVES.find((x) => x[0] === o.objective)?.[1]}</td>
                      <td>{o.people_protected.toLocaleString()}</td><td>{o.cooling_mid_c}°C</td><td>{o.cost_per_person_inr?.toLocaleString()}</td>
                      <td>{pct(o.high_vulnerability_spend_share)}</td><td>{o.severe_wards_after}</td><td>{o.people_in_hotspots_after.toLocaleString()}</td></tr>))}</tbody></table>
              </div>)}

            <div className="dec-grid two">
              <div className="glass-panel dec-card"><h3>Where the money goes</h3>
                {grid && <CityMap grid={grid} center={cityInfo?.center} height={300} updateKey={plan.plan_id}
                  colorOf={(p) => (planCells[p.grid_id] !== undefined ? (planCells[p.grid_id] < -0.01 ? coolRgb(planCells[p.grid_id]) : [255, 170, 60]) : null)}
                  tooltipOf={(p) => (planCells[p.grid_id] !== undefined ? `${p.ward_name}\ncooling ${planCells[p.grid_id]}°C` : null)} />}
                <div className="dec-note">Blue = surface cooling, orange = access site (cooling centre / water point).</div></div>
              <div className="glass-panel dec-card"><h3>Budget by year and department</h3>
                <div style={{ height: 130 }}><ResponsiveContainer><BarChart data={plan.budget_by_year}>
                  <XAxis dataKey="year" tickFormatter={(y) => `Y${y}`} /><YAxis /><Tooltip formatter={(v) => cr(v)} /><Bar dataKey="capex_lakh" name="Capital" fill="#3b82f6" />
                </BarChart></ResponsiveContainer></div>
                <table className="dec-table"><tbody>{plan.by_department.map((d) => (
                  <tr key={d.department}><td>{d.department}</td><td>{cr(d.cost_lakh)}</td><td>{d.actions} sites</td></tr>))}</tbody></table>
                <div style={{ height: 120, marginTop: 8 }}><ResponsiveContainer><LineChart data={plan.timeline}>
                  <XAxis dataKey="year" /><YAxis /><Tooltip /><Line dataKey="pop_weighted_cooling_mid_c" name="°C" stroke="#3b82f6" dot={false} />
                </LineChart></ResponsiveContainer></div>
                <div className="dec-note">Cooling over 10 years as trees and parks mature.</div></div>
            </div>

            <div className="glass-panel dec-card">
              <h3>Work orders by ward ({plan.work_orders.length})</h3>
              <div className="dec-note">Sorted by today's ward risk. Quarters count from the plan start.</div>
              {plan.work_orders.slice(0, 40).map((wo) => (
                <details key={wo.ward_id} className="wo">
                  <summary><b>{wo.ward_name}</b><span className={`band ${wo.band_before}`}>risk {wo.risk_before} → {wo.risk_after}</span>
                    <span>{cr(wo.capex_lakh)}</span><span>{wo.people_protected.toLocaleString()} of {wo.people.toLocaleString()} people protected</span>
                    <span className="dec-note">{wo.lines.length} line{wo.lines.length > 1 ? 's' : ''}</span></summary>
                  <table className="dec-table"><thead><tr><th>Work</th><th>Quantity</th><th>Sites</th><th>Capital</th><th>Upkeep/yr</th><th>Water kL/day</th><th>Department</th><th>Quarters</th><th>KPIs</th></tr></thead>
                    <tbody>{wo.lines.map((l) => (
                      <tr key={l.intervention}><td>{l.label}</td><td>{l.units.toLocaleString()} {l.unit}</td><td>{l.n_cells}</td><td>{cr(l.capex_lakh)}</td>
                        <td>{cr(l.opex_lakh_yr)}</td><td>{l.water_kl_day}</td><td>{l.department}</td><td>Q{l.start_quarter}–Q{l.finish_quarter}</td><td className="dec-note">{l.kpis.join('; ')}</td></tr>))}</tbody></table>
                </details>))}
            </div>

            <div className="glass-panel dec-card">
              <h3>{t('brief_for')}</h3>
              <div className="btn-row">
                <select value={briefWard} onChange={(e) => setBriefWard(e.target.value)}>
                  {plan.work_orders.map((x) => <option key={x.ward_id} value={x.ward_id}>{x.ward_name}</option>)}</select>
                <button className="btn-primary" onClick={makeBrief} disabled={briefBusy || !briefWard}>{briefBusy ? t('building') : t('make_brief')}</button>
                {pdf && <a className="btn-ghost" href={pdf} target="_blank" rel="noreferrer">{t('download_pdf')}</a>}
              </div>
              {brief && (<>
                <div className="dec-note" style={{ marginTop: 8 }}>{t('source')}: {brief.source}{brief.note ? ` (${brief.note})` : ''} · numbers verified: {String(brief.numbers_verified)}</div>
                {brief.sources?.length > 0 && <div className="dec-note">{t('guidance_sources')}: {brief.sources.map((n, i) => `[S${i + 1}] ${n}`).join('; ')}</div>}
                <div className="brief-box">{brief.brief_en}</div><div className="brief-box">{brief.brief_hi}</div></>)}
            </div>
          </>)}
        </div>
      </div>
    </div></div>
  );
}
