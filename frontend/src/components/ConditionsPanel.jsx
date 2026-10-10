import { useEffect, useState } from 'react';
import { API_BASE } from '../api';

/** "What day are we planning for?" — shared by the Scenario Lab and the Ward Planner. */
export default function ConditionsPanel({ city, value, onChange, compact = false }) {
  const [resolved, setResolved] = useState(null);
  const set = (patch) => onChange({ ...value, ...patch });

  useEffect(() => {
    let off = false;
    const id = setTimeout(() => {
      const body = { ...value, tmax_c: value.mode === 'custom' ? value.tmax_c : null };
      fetch(`${API_BASE}/api/v1/lab/conditions?city=${city}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        .then((r) => (r.ok ? r.json() : null)).then((d) => !off && setResolved(d)).catch(() => {});
    }, 300);
    return () => { off = true; clearTimeout(id); };
  }, [city, value]);

  return (
    <div className="glass-panel dec-card">
      <h3>Planning conditions</h3>
      <div className="seg">{[['today', 'Today (forecast)'], ['hot_season', 'Typical hot day'], ['custom', 'Custom']].map(([m, l]) => (
        <button key={m} className={value.mode === m ? 'on' : ''} onClick={() => set({ mode: m })}>{l}</button>))}</div>
      {value.mode === 'custom' && (
        <div className="field" style={{ marginTop: 10 }}><label><span>Max air temperature</span><b>{value.tmax_c}°C</b></label>
          <input type="range" min="34" max="50" step="0.5" value={value.tmax_c} onChange={(e) => set({ tmax_c: +e.target.value })} /></div>)}
      <div className="field" style={{ marginTop: 10 }}><label><span>Climate shift</span><b>{value.climate_shift_c > 0 ? '+' : ''}{value.climate_shift_c}°C</b></label>
        <div className="seg">{[0, 1, 1.5, 2, 3].map((c) => (
          <button key={c} className={value.climate_shift_c === c ? 'on' : ''} onClick={() => set({ climate_shift_c: c })}>{c ? `+${c}` : 'Now'}</button>))}</div></div>
      {!compact && (
        <div className="field"><label><span>Humidity override</span><b>{value.humidity_pct == null ? 'from data' : `${value.humidity_pct}%`}</b></label>
          <input type="range" min="10" max="90" step="5" value={value.humidity_pct ?? (resolved?.humidity_pct || 40)}
            onChange={(e) => set({ humidity_pct: +e.target.value })} /></div>)}
      <div className="checks">
        <label><input type="checkbox" checked={value.power_cut} onChange={(e) => set({ power_cut: e.target.checked })} /> Power cut (no fans / AC)</label>
        <label><input type="checkbox" checked={value.water_shortage} onChange={(e) => set({ water_shortage: e.target.checked })} /> Water shortage</label>
      </div>
      {resolved && (
        <div className="cond-out">
          <span className={`pill ${resolved.alert_level}`}>{resolved.alert_level.toUpperCase()}</span>
          <span>Max {resolved.tmax_c}°C · humidity {resolved.humidity_pct}% · feels like {resolved.heat_index_c}°C</span>
          <div className="dec-note">{resolved.source}{resolved.notes.length ? ` · ${resolved.notes.join(' ')}` : ''}</div>
        </div>)}
    </div>
  );
}
