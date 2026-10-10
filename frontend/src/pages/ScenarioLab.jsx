import { useEffect, useMemo, useState } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { API_BASE } from '../api';
import { useLang } from '../i18n';
import CityMap from '../components/CityMap';
import { coolRgb } from '../components/mapColors';
import ConditionsPanel from '../components/ConditionsPanel';
import { DEFAULT_CONDITIONS } from '../components/conditionsDefaults';
import './Decision.css';
import './Lab.css';

const ACCESS = new Set(['cooling_centres', 'water_atms']);
const PRESETS = [
  { id: 'roofs', name: 'Cool-roof drive', actions: { cool_roofs: 0.6 } },
  { id: 'green', name: 'Green city', actions: { street_trees: 0.6, pocket_parks: 0.5, green_roofs: 0.2 } },
  { id: 'heatwave', name: 'Heatwave readiness', actions: { shade_structures: 0.6, misting_points: 0.5, cooling_centres: 25, water_atms: 40 } },
  { id: 'blue', name: 'Water & shade', actions: { water_bodies: 0.6, shade_structures: 0.5, street_trees: 0.4, water_atms: 30 } },
  { id: 'all', name: 'Everything, moderate', actions: { street_trees: 0.4, cool_roofs: 0.4, cool_pavement: 0.3, shade_structures: 0.4, pocket_parks: 0.3, cooling_centres: 15, water_atms: 20 } },
];
const lakhToCr = (l) => `₹${(l / 100).toLocaleString(undefined, { maximumFractionDigits: 1 })} cr`;
const rng = (c) => `${c.high.toFixed(2)} to ${c.low.toFixed(2)} °C`;

export default function ScenarioLab({ city, cityInfo }) {
  const { t } = useLang();
  const [lib, setLib] = useState([]);
  const [grid, setGrid] = useState(null);
  const [wards, setWards] = useState([]);
  const [conditions, setConditions] = useState(DEFAULT_CONDITIONS);
  const [acts, setActs] = useState({});          // key -> {on, intensity, count, params}
  const [target, setTarget] = useState({ mode: 'hotspots', ward_ids: [] });
  const [survival, setSurvival] = useState(0.7);
  const [result, setResult] = useState(null);
  const [pinned, setPinned] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [view, setView] = useState('delta');

  useEffect(() => {
    let off = false;
    fetch(`${API_BASE}/api/v1/lab/interventions`).then((r) => r.json()).then((d) => {
      if (off) return;
      setLib(d.interventions);
      setActs(Object.fromEntries(d.interventions.map((i) => [i.key, { on: false, intensity: 0.5, count: 10, params: {} }])));
    }).catch(() => !off && setError(t('error')));
    fetch(`${API_BASE}/api/v1/grid?city=${city}`).then((r) => r.json()).then((g) => !off && setGrid(g)).catch(() => {});
    fetch(`${API_BASE}/api/v1/planner/wards?city=${city}`).then((r) => r.json())
      .then((w) => !off && setWards(w.wards || [])).catch(() => {});
    return () => { off = true; };
  }, [city, t]);

  const setAct = (k, patch) => setActs((s) => ({ ...s, [k]: { ...s[k], ...patch } }));
  const setParam = (k, p, v) => setActs((s) => ({ ...s, [k]: { ...s[k], params: { ...s[k].params, [p]: v } } }));

  const applyPreset = (p) => {
    setActs((s) => Object.fromEntries(Object.entries(s).map(([k, v]) => {
      const x = p.actions[k];
      if (x === undefined) return [k, { ...v, on: false }];
      return [k, ACCESS.has(k) ? { ...v, on: true, count: x } : { ...v, on: true, intensity: x }];
    })));
  };

  const actions = Object.entries(acts).filter(([, v]) => v.on).map(([key, v]) => (
    ACCESS.has(key) ? { key, params: { ...v.params, count: v.count } } : { key, intensity: v.intensity, params: v.params }));

  const run = async () => {
    if (!actions.length) { setError('Turn on at least one intervention.'); return; }
    if (target.mode === 'wards' && !target.ward_ids.length) { setError('Pick at least one ward to target.'); return; }
    setBusy(true); setError(null);
    try {
      const r = await fetch(`${API_BASE}/api/v1/lab/simulate?city=${city}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conditions, actions, target, survival }) });
      const body = await r.json();
      if (!r.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Simulation failed');
      setResult(body);
    } catch (e) { setError(String(e.message || e)); } finally { setBusy(false); }
  };

  const pin = () => {
    if (!result) return;
    const name = `Scenario ${pinned.length + 1}: ${actions.map((a) => a.key.replace(/_/g, ' ')).join(', ')}`;
    setPinned((p) => [...p.slice(-2), { name, s: result.summary, c: result.conditions }]);
  };

  const cellDelta = useMemo(() => Object.fromEntries((result?.cell_results || []).map((c) => [c.grid_id, c])), [result]);

  if (cityInfo?.data_kind !== 'real') return null;
  const s = result?.summary;

  return (
    <div className="page-container"><div className="page-content">
      <div className="page-header"><h1>Scenario Lab</h1>
        <p>Pick the day you are planning for, choose what to build and where, and see the estimated effect on heat, people, cost and water.</p></div>

      <div className="lab-layout">
        <div className="dec-grid">
          <ConditionsPanel city={city} value={conditions} onChange={setConditions} />

          <div className="glass-panel dec-card">
            <h3>Where</h3>
            <div className="seg">{[['hotspots', 'Hotspot cells'], ['wards', 'Chosen wards'], ['city', 'Whole city']].map(([m, l]) => (
              <button key={m} className={target.mode === m ? 'on' : ''} onClick={() => setTarget((x) => ({ ...x, mode: m }))}>{l}</button>))}</div>
            {target.mode === 'wards' && (
              <select multiple size={6} style={{ width: '100%', marginTop: 8 }} value={target.ward_ids}
                onChange={(e) => setTarget((x) => ({ ...x, ward_ids: [...e.target.selectedOptions].map((o) => o.value) }))}>
                {wards.map((w) => <option key={w.ward_id} value={w.ward_id}>#{w.rank} {w.ward_name} · risk {w.risk_score}</option>)}
              </select>)}
            {target.mode === 'wards' && <div className="dec-note">Ctrl/Cmd-click to pick several. Highest-risk wards are listed first.</div>}
          </div>

          <div className="glass-panel dec-card">
            <h3>What to build</h3>
            <div className="chips">{PRESETS.map((p) => <button key={p.id} className="chip" onClick={() => applyPreset(p)}>{p.name}</button>)}</div>
            {lib.map((iv) => {
              const a = acts[iv.key]; if (!a) return null;
              return (
                <div key={iv.key} className={`iv ${a.on ? 'on' : ''}`}>
                  <label className="iv-head"><input type="checkbox" checked={a.on} onChange={(e) => setAct(iv.key, { on: e.target.checked })} />
                    <b>{iv.label}</b><span className="dec-note">{iv.department}</span></label>
                  {a.on && (<div className="iv-body">
                    {ACCESS.has(iv.key) ? (
                      <div className="field"><label><span>Number of sites</span><b>{a.count}</b></label>
                        <input type="range" min="1" max="150" value={a.count} onChange={(e) => setAct(iv.key, { count: +e.target.value })} /></div>
                    ) : (
                      <div className="field"><label><span>Share of each target cell's capacity</span><b>{Math.round(a.intensity * 100)}%</b></label>
                        <input type="range" min="0.05" max="1" step="0.05" value={a.intensity} onChange={(e) => setAct(iv.key, { intensity: +e.target.value })} /></div>
                    )}
                    {iv.key === 'cool_roofs' && (
                      <div className="field"><label><span>Roof albedo (reflectance)</span><b>{(a.params.albedo ?? 0.75).toFixed(2)}</b></label>
                        <input type="range" min="0.55" max="0.9" step="0.05" value={a.params.albedo ?? 0.75} onChange={(e) => setParam(iv.key, 'albedo', +e.target.value)} /></div>)}
                    {iv.key === 'green_roofs' && (
                      <label className="dec-note"><input type="checkbox" checked={a.params.irrigated !== false} onChange={(e) => setParam(iv.key, 'irrigated', e.target.checked)} /> Irrigated (more cooling, uses water)</label>)}
                    {iv.key === 'street_trees' && (
                      <select value={a.params.species || 'native_shade'} onChange={(e) => setParam(iv.key, 'species', e.target.value)}>
                        <option value="native_shade">Native shade trees (neem, peepal) · 8 yrs to full shade</option>
                        <option value="fast_shade">Fast-growing shade · 5 yrs, more water, lower survival</option>
                      </select>)}
                    <div className="dec-note">₹{iv.capex_inr_per_unit.toLocaleString()} per {iv.unit.replace(/s$/, '')} · upkeep ₹{iv.opex_inr_per_unit_yr.toLocaleString()}/yr · water {iv.water_l_per_unit_day} L/day{iv.years_to_full ? ` · full effect in ${iv.years_to_full} yrs` : ''}{iv.notes ? ` · ${iv.notes}` : ''}</div>
                  </div>)}
                </div>);
            })}
            <div className="field" style={{ marginTop: 10 }}><label><span>Tree / park survival</span><b>{Math.round(survival * 100)}%</b></label>
              <input type="range" min="0.3" max="1" step="0.05" value={survival} onChange={(e) => setSurvival(+e.target.value)} /></div>
            <button className="btn-primary" style={{ width: '100%' }} onClick={run} disabled={busy}>{busy ? 'Simulating…' : 'Run scenario'}</button>
            {error && <div className="error-text" style={{ marginTop: 8 }}>{error}</div>}
          </div>
        </div>

        <div className="dec-grid">
          {!s && <div className="glass-panel dec-card dec-note">Choose conditions and interventions on the left, or start from a preset, then run the scenario.</div>}
          {s && (<>
            <div className="glass-panel dec-card">
              <div className="stat-row">
                <div className="stat"><div className="label">Surface cooling (treated areas)</div><div className="value sm">{rng(s.surface_cooling_c)}</div></div>
                <div className="stat"><div className="label">Feels-like on this day</div><div className="value">{s.feels_like_c.before}→{s.feels_like_c.after}°C</div></div>
                <div className="stat"><div className="label">People in hotspots</div><div className="value sm">{s.people_in_hotspots.before.toLocaleString()} → {s.people_in_hotspots.after.toLocaleString()}</div></div>
                <div className="stat"><div className="label">Capital / 10-yr cost</div><div className="value sm">{lakhToCr(s.cost.capex_lakh)} / {lakhToCr(s.cost.ten_year_lakh)}</div></div>
                <div className="stat"><div className="label">Water needed</div><div className="value sm">{s.water_kl_day.toLocaleString()} kL/day</div></div>
              </div>
              <div className="band-row">
                {['severe', 'high', 'moderate', 'low'].map((b) => (
                  <span key={b} className={`band ${b}`}>{b}: {s.wards_by_band.before[b] || 0} → <b>{s.wards_by_band.after[b] || 0}</b> wards</span>))}
              </div>
              <div className="dec-note">{s.feels_like_c.note} {t('estimate_note')}</div>
              <div className="btn-row"><button className="btn-ghost" onClick={pin}>Pin for comparison</button></div>
            </div>

            {grid && (
              <div className="glass-panel dec-card">
                <div className="seg" style={{ marginBottom: 8 }}>{[['delta', 'Cooling achieved'], ['after', 'Surface temp after']].map(([v, l]) => (
                  <button key={v} className={view === v ? 'on' : ''} onClick={() => setView(v)}>{l}</button>))}</div>
                <CityMap grid={grid} center={cityInfo?.center} updateKey={`${view}-${result?.summary?.cells_treated}`}
                  colorOf={(p) => {
                    const c = cellDelta[p.grid_id]; if (!c) return null;
                    if (view === 'delta') return c.delta_t < -0.01 ? coolRgb(c.delta_t) : [120, 120, 120];
                    const v = Math.max(0, Math.min(1, (c.lst_after - 35) / 18));
                    return [255, Math.round(220 - 190 * v), Math.round(90 - 80 * v)];
                  }}
                  tooltipOf={(p) => { const c = cellDelta[p.grid_id]; return c ? `${p.ward_name || p.grid_id}\n${c.lst_before}°C → ${c.lst_after}°C (${c.delta_t}°C)` : null; }} />
              </div>)}

            <div className="glass-panel dec-card">
              <h3>What each intervention contributes</h3>
              <table className="dec-table"><thead><tr><th>Intervention</th><th>Quantity</th><th>Cells</th><th>Capital</th><th>Upkeep / yr</th><th>Water kL/day</th><th>Cooling alone</th><th>Dept</th></tr></thead>
                <tbody>{result.breakdown.map((b) => (
                  <tr key={b.key}><td>{b.label}</td><td>{b.units.toLocaleString()} {b.unit}</td><td>{b.cells}</td>
                    <td>{lakhToCr(b.capex_lakh)}</td><td>{lakhToCr(b.opex_lakh_yr)}</td><td>{b.water_kl_day}</td>
                    <td>{b.cooling_mid_c_alone ? `${b.cooling_mid_c_alone} °C` : 'access'}</td><td>{b.department}</td></tr>))}</tbody></table>
            </div>

            <div className="dec-grid two">
              <div className="glass-panel dec-card"><h3>Effect as trees and parks mature</h3>
                <div style={{ height: 170 }}><ResponsiveContainer><LineChart data={result.timeline}>
                  <XAxis dataKey="year" /><YAxis /><Tooltip /><Line dataKey="surface_cooling_mid_c" name="°C (mid)" stroke="#3b82f6" dot={false} />
                </LineChart></ResponsiveContainer></div></div>
              <div className="glass-panel dec-card"><h3>Wards that improve most</h3>
                <table className="dec-table"><tbody>{result.ward_changes.slice(0, 6).map((w) => (
                  <tr key={w.ward_id}><td>{w.ward_name}</td><td>{w.risk_score_before} → <b>{w.risk_score_after}</b></td><td>{w.band_before} → {w.band_after}</td></tr>))}</tbody></table></div>
            </div>
            <div className="glass-panel dec-card"><ul className="dec-note" style={{ paddingLeft: 18 }}>{result.assumptions.map((a) => <li key={a}>{a}</li>)}</ul></div>
          </>)}

          {pinned.length > 0 && (
            <div className="glass-panel dec-card">
              <h3>Compare pinned scenarios</h3>
              <table className="dec-table"><thead><tr><th></th>{pinned.map((p) => <th key={p.name}>{p.name}</th>)}</tr></thead>
                <tbody>
                  <tr><td>Conditions</td>{pinned.map((p) => <td key={p.name}>{p.c.tmax_c}°C, {p.c.alert_level}{p.c.power_cut ? ', power cut' : ''}{p.c.water_shortage ? ', water shortage' : ''}</td>)}</tr>
                  <tr><td>Surface cooling (mid)</td>{pinned.map((p) => <td key={p.name}>{p.s.surface_cooling_c.mid} °C</td>)}</tr>
                  <tr><td>Feels-like</td>{pinned.map((p) => <td key={p.name}>{p.s.feels_like_c.before}→{p.s.feels_like_c.after}°C</td>)}</tr>
                  <tr><td>People in hotspots after</td>{pinned.map((p) => <td key={p.name}>{p.s.people_in_hotspots.after.toLocaleString()}</td>)}</tr>
                  <tr><td>Severe wards after</td>{pinned.map((p) => <td key={p.name}>{p.s.wards_by_band.after.severe || 0}</td>)}</tr>
                  <tr><td>Capital</td>{pinned.map((p) => <td key={p.name}>{lakhToCr(p.s.cost.capex_lakh)}</td>)}</tr>
                  <tr><td>10-year cost</td>{pinned.map((p) => <td key={p.name}>{lakhToCr(p.s.cost.ten_year_lakh)}</td>)}</tr>
                  <tr><td>Water kL/day</td>{pinned.map((p) => <td key={p.name}>{p.s.water_kl_day.toLocaleString()}</td>)}</tr>
                </tbody></table>
              <div className="btn-row"><button className="btn-ghost" onClick={() => setPinned([])}>Clear</button></div>
            </div>)}
        </div>
      </div>
    </div></div>
  );
}
