import { useState, useEffect } from 'react';
import { API_BASE } from '../api';
import { useLang } from '../i18n';
import './Decision.css';

const f = (v) => (v === null || v === undefined ? '—' : v);

export default function ModelCardView() {
  const { t } = useLang();
  const [card, setCard] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/model-card`).then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(setCard).catch(() => setError(t('error')));
  }, [t]);

  if (error) return <div className="page-container"><div className="error-text">{error}</div></div>;
  if (!card) return <div className="page-container"><div className="loading-spinner">{t('loading')}</div></div>;

  const ev = card.evaluation[card.shipped_variant];
  const gate = card.quality_gate;
  return (
    <div className="page-container"><div className="page-content">
      <div className="page-header"><h1>{t('model_title')}</h1><p>{t('model_sub')}</p></div>
      <div className={`glass-panel dec-banner ${gate.passed ? 'ok' : ''}`}>
        {card.model_version} · {card.n_cells.toLocaleString()} cells · {card.cities.join(', ')} · target: {card.target}.
        Quality gate (leave-one-city-out Pearson r ≥ {gate.min_pearson_r_leave_city_out}): <b>{gate.passed ? 'passed' : `NOT passed (${gate.failing_cities.join(', ') || 'n/a'})`}</b>
      </div>

      <div className="dec-grid two">
        <div className="glass-panel dec-card">
          <h3>On a city the model never saw</h3>
          <div className="dec-note">Trained on the other cities, scored on the held-out one ({card.shipped_variant}).</div>
          <table className="dec-table"><thead><tr><th>City</th><th>r</th><th>RMSE °C</th><th>R²</th><th>Bias °C</th><th>Baseline r (NDVI+impervious)</th></tr></thead>
            <tbody>{Object.entries(ev.leave_one_city_out).map(([c, m]) => (
              <tr key={c}><td>{c}</td><td>{f(m.pearson_r)}</td><td>{f(m.rmse)}</td><td>{f(m.r2)}</td><td>{f(m.bias)}</td>
                <td>{f(ev.baseline_linear_ndvi_impervious?.[c]?.pearson_r)}</td></tr>))}</tbody></table>
        </div>
        <div className="glass-panel dec-card">
          <h3>Inside a city (5 km spatial blocks)</h3>
          <div className="dec-note">Uncertainty band (q10–q90) should cover about {Math.round(card.block_cv_5km.nominal_coverage * 100)}% of cells.</div>
          <table className="dec-table"><thead><tr><th>City</th><th>r</th><th>RMSE °C</th><th>Band coverage (raw → calibrated)</th></tr></thead>
            <tbody>{Object.entries(card.block_cv_5km.per_city).map(([c, m]) => (
              <tr key={c}><td>{c}</td><td>{f(m.pearson_r)}</td><td>{f(m.rmse)}</td><td>{Math.round((card.block_cv_5km.q10_q90_coverage[c] ?? 0) * 100)}% → {Math.round((card.block_cv_5km.calibrated_coverage?.[c] ?? 0) * 100)}%</td></tr>))}</tbody></table>
        </div>
      </div>

      <div className="dec-grid two" style={{ marginTop: 20 }}>
        <div className="glass-panel dec-card"><h3>Main drivers (model explanation, not causal)</h3>
          <table className="dec-table"><tbody>{card.top_drivers_shap.map((d) => (
            <tr key={d.feature}><td>{d.feature}</td><td>{d.mean_abs_shap}</td></tr>))}</tbody></table></div>
        <div className="glass-panel dec-card"><h3>Limits</h3>
          <ul className="dec-note" style={{ paddingLeft: 18 }}>{card.limitations.map((l) => <li key={l}>{l}</li>)}</ul></div>
      </div>

      <div className="glass-panel dec-card" style={{ marginTop: 20 }}><h3>Data sources and licences</h3>
        {Object.entries(card.data_cards || {}).slice(0, 1).map(([c, d]) => (
          <table className="dec-table" key={c}><tbody>{Object.entries(d.sources).map(([k, v]) => (
            <tr key={k}><td>{k}</td><td>{v.licence}</td></tr>))}</tbody></table>))}
      </div>
    </div></div>
  );
}
