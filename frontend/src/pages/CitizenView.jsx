import { useState, useEffect, useCallback } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { PathLayer, ScatterplotLayer } from '@deck.gl/layers';
import { API_BASE } from '../api';
import BaseMap from '../components/BaseMap';
import { LOCATION_KEY, walkingRoute, viewForPath } from '../location';
import { loadConfig } from '../platform';
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

  // regional languages (Amazon Translate) offered by this deployment; '' = follow the English/Hindi buttons
  const [regionalLangs, setRegionalLangs] = useState([]);
  const [regional, setRegional] = useState(() => { try { return localStorage.getItem('heatrelief-regional') || ''; } catch { return ''; } });
  useEffect(() => { loadConfig().then((c) => setRegionalLangs(c.translate.languages)); }, []);
  const pickRegional = (code) => {
    setRegional(code);
    try { localStorage.setItem('heatrelief-regional', code); } catch { /* storage may be blocked */ }
  };

  // walking route to one cooling place: { key, loading } | { key, error } | { key, path, distance_m, duration_s }
  const [route, setRoute] = useState(null);
  const [photo, setPhoto] = useState(null);
  const [uploading, setUploading] = useState(false);

  const handlePhoto = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement('canvas');
      const max = 1600;
      let w = img.width;
      let h = img.height;
      if (w > max || h > max) {
        if (w > h) { h = h * (max / w); w = max; }
        else { w = w * (max / h); h = max; }
      }
      canvas.width = w; canvas.height = h;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(img, 0, 0, w, h);
      canvas.toBlob((b) => setPhoto(b), 'image/jpeg', 0.8);
    };
    img.src = URL.createObjectURL(file);
  };


  const [subEmail, setSubEmail] = useState('');
  const [subCity, setSubCity] = useState(city);
  const [subMinLevel, setSubMinLevel] = useState('orange');
  const [subConsent, setSubConsent] = useState(false);
  const [subHoneypot, setSubHoneypot] = useState('');
  const [subMessage, setSubMessage] = useState('');

  useEffect(() => { setSubCity(city); }, [city]);

  const load = useCallback((p) => {
    const sim = params.get('simulate');
    const simStr = (sim ? `&simulate=${sim}` : '') + (regional ? `&lang=${regional}` : '');
    fetch(`${API_BASE}/api/v1/citizen?city=${city}&lat=${p.lat}&lon=${p.lon}${simStr}`)
      .then((r) => (r.ok ? r.json() : r.json().then((j) => Promise.reject(new Error(j.detail)))))
      .then((d) => { setError(null); setData(d); }).catch((e) => setError(e.message || t('error')));
  }, [city, t, params, regional]);

  const [recentPhotos, setRecentPhotos] = useState([]);

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/reports/summary?city=${city}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => {
        if (s?.recent_photos) setRecentPhotos(s.recent_photos);
      })
      .catch(() => {});
  }, [city, sent]);

  useEffect(() => {
    if (!info) return;
    const p = pos || { lat: info.center[1], lon: info.center[0] };
    load(p);
  }, [info, pos, load]);

  const locate = () => navigator.geolocation?.getCurrentPosition(
    (g) => setPos({ lat: g.coords.latitude, lon: g.coords.longitude }),
    () => setError('Location permission denied; showing the city centre.'));

  const showRoute = async (spot) => {
    const key = spot.name + spot.lat;
    if (route?.key === key) { setRoute(null); return; }
    setRoute({ key, loading: true });
    const from = pos || { lat: info.center[1], lon: info.center[0] };
    try {
      const r = await walkingRoute(from, { lat: spot.lat, lon: spot.lon });
      setRoute({ key, ...r });
    } catch {
      // no Amazon Location key (local dev) or no route found: still show where the place is,
      // with a straight line, and keep the straight-line estimate
      setRoute({ key, straight: true, failed: Boolean(LOCATION_KEY),
        path: [[from.lon, from.lat], [spot.lon, spot.lat]] });
    }
  };

  const report = async (kind) => {
    setUploading(true);
    let photo_key = null;
    if (photo) {
      try {
        const urlRes = await fetch(`${API_BASE}/api/v1/reports/upload-url?city=${city}`, { method: 'POST' });
        if (urlRes.ok) {
          const resJson = await urlRes.json();
          const upload_url = resJson.upload_url;
          const pk = resJson.photo_key;
          const putRes = await fetch(upload_url, {
            method: 'PUT',
            headers: { 'Content-Type': 'image/jpeg' },
            body: photo
          });
          if (putRes.ok) photo_key = pk;
        }
      } catch (e) { console.error('Upload failed', e); }
    }
    const p = pos || { lat: info.center[1], lon: info.center[0] };
    const r = await fetch(`${API_BASE}/api/v1/reports?city=${city}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...p, kind, photo_key }) });
    if (r.ok) setSent(true);
    setUploading(false);
  };

  const subscribe = async (e) => {
    e.preventDefault();
    if (!subConsent) return;
    const r = await fetch(`${API_BASE}/api/v1/alerts/subscribe`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: subEmail, city: subCity, min_level: subMinLevel, consent: subConsent, website: subHoneypot })
    });
    if (r.ok) {
      setSubMessage(t('subscribe_confirm_msg'));
    } else {
      const j = await r.json();
      alert(j.detail || 'Error');
    }
  };

  return (
    <div className="citizen">
      <div className="lang">
        <Link to="/" className="btn-ghost back-link" aria-label={t('back_to_map')}><ArrowLeft size={18} /><span>{t('back_to_map')}</span></Link>
        {['en', 'hi'].map((l) => <button key={l} className="btn-ghost" style={l === lang ? { background: 'var(--accent-primary)', color: '#fff' } : {}}
          onClick={() => { setLang(l); pickRegional(''); }}>{l === 'en' ? 'English' : 'हिंदी'}</button>)}
        {regionalLangs.length > 0 && (
          <select className="lang-more" aria-label={t('more_languages')} value={regional} onChange={(e) => pickRegional(e.target.value)}>
            <option value="">{t('more_languages')}</option>
            {regionalLangs.map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
          </select>)}
      </div>
      <h1 style={{ fontSize: 22 }}>{t('citizen_title')} — {info?.name}</h1>
      {error && <div className="error-text">{error}</div>}
      {data && (<>
        {data.simulated && <div className="simulation-banner">SIMULATION</div>}
        <div className={`hero ${data.alert_level}`}>
          <span className={`pill ${data.alert_level}`}>{data.alert_level.toUpperCase()}</span>
          <h2>{data.forecast_tmax_c != null ? `${data.forecast_tmax_c}°C` : ''}</h2>
          {data.message_local
            ? (<><p lang={data.message_local_lang}>{data.message_local}</p>
              <div className="dec-note">{t('machine_translated')} · {lang === 'hi' ? data.message_hi : data.message_en}</div></>)
            : <p>{lang === 'hi' ? data.message_hi : data.message_en}</p>}
          {data.stale && <div className="dec-note">{t('stale')}</div>}
        </div>
        {data.ward && <div className="dec-note" style={{ margin: '10px 4px' }}>{t('ward_rank_line')}: #{data.ward.rank} {t('of')} {data.ward.of_wards} — {data.ward.ward_name} {!pos ? t('default_zone') : ''}</div>}
        {(() => {
          // Polly speaks Hindi and Indian English; other languages get the Hindi recording
          const english = lang === 'en' && !regional && data.advisory_audio_url_en;
          const src = english ? data.advisory_audio_url_en : data.advisory_audio_url;
          return src ? (
            <div style={{ marginTop: 10 }}><div className="dec-note">{english ? t('listen_en') : t('listen')}</div>
              <audio controls src={src} style={{ width: '100%' }} /></div>) : null;
        })()}
        <button className="btn-primary big-btn" onClick={locate}>{t('use_location')}</button>

        <h3 style={{ margin: '18px 4px 4px' }}>{t('nearest_cool')}</h3>
        {data.nearest_cooling_spots.length === 0 && <div className="dec-note">—</div>}
        {data.nearest_cooling_spots.length > 0 && data.nearest_cooling_spots[0].distance_m > 1500 && (
          <div className="dec-banner" style={{ borderLeftColor: 'var(--tier-high)', marginBottom: 8, marginTop: 8 }}>{t('too_far')}</div>
        )}
        {data.nearest_cooling_spots.map((s) => {
          const key = s.name + s.lat;
          const shown = route?.key === key ? route : null;
          const routed = shown?.path && !shown.straight;
          return (
            <div key={key}>
              <div className="glass-panel spot">
                <div><b>{s.name}</b><div className="dec-note">{s.type.replace('_', ' ')} · {routed
                  ? `${Math.max(1, Math.round(shown.duration_s / 60))} ${t('walking_min')} · ${shown.distance_m} m`
                  : `${Math.max(1, Math.round(s.distance_m / 84))} ${t('walking_min')} ${t('estimate_tag')}`}</div></div>
                <div className="spot-actions">
                  <button className="btn-ghost" onClick={() => showRoute(s)}>
                    {shown?.path ? t('hide_route') : (LOCATION_KEY ? t('walking_route') : t('show_map'))}</button>
                  <a href={`https://www.google.com/maps/dir/?api=1&destination=${s.lat},${s.lon}&travelmode=walking`} target="_blank" rel="noreferrer">{t('open_google')}</a>
                </div>
              </div>
              {shown?.loading && <div className="dec-note" style={{ margin: '6px 4px' }}>{t('loading')}</div>}
              {shown?.path && (<>
                <div className="route-map">
                  <BaseMap key={key} onTop initialViewState={viewForPath(shown.path)} layers={[
                    new PathLayer({ id: 'route', data: [{ path: shown.path }], getPath: (d) => d.path,
                      getColor: shown.straight ? [120, 124, 140] : [41, 121, 255], widthUnits: 'pixels',
                      getWidth: shown.straight ? 3 : 5, capRounded: true, jointRounded: true }),
                    new ScatterplotLayer({ id: 'route-ends', data: [
                      { position: shown.path[0], color: [90, 90, 100] },
                      { position: shown.path[shown.path.length - 1], color: [0, 160, 80] }],
                      getPosition: (d) => d.position, getFillColor: (d) => d.color, radiusUnits: 'pixels', getRadius: 7,
                      stroked: true, getLineColor: [255, 255, 255], lineWidthUnits: 'pixels', getLineWidth: 2 }),
                  ]} />
                </div>
                <div className="dec-note" style={{ margin: '4px' }}>
                  {shown.straight ? `${shown.failed ? t('route_unavailable') : t('route_straight_line')} ` : ''}
                  {!pos ? `${t('route_from_centre')} ` : ''}{t('map_needs_connection')}</div>
              </>)}
            </div>);
        })}

        <h3 style={{ margin: '18px 4px 4px' }}>{t('report_title')}</h3>
        {sent ? <div className="dec-banner ok glass-panel">{t('thanks')}</div> : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div className="glass-panel" style={{ padding: 12 }}>
              <label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>{t('add_photo')}</label>
              <input type="file" accept="image/*" onChange={handlePhoto} disabled={uploading} />
              {photo && <div style={{ fontSize: 12, marginTop: 4, color: 'var(--tier-normal)' }}>{t('photo_attached')}</div>}
              <div className="dec-note" style={{ marginTop: 4 }}>{t('photo_moderation_note')}</div>
            </div>
            {['no_shade', 'no_water', 'very_hot'].map((k) => (
              <button key={k} className="btn-ghost big-btn" onClick={() => report(k)} disabled={uploading}>
                {uploading ? t('loading') : t(k)}
              </button>
            ))}
          </div>
        )}

        {recentPhotos.length > 0 && (
          <div style={{ marginTop: 24 }}>
            <h3 style={{ margin: '0 4px 8px' }}>{t('community_reports')}</h3>
            <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 8 }}>
              {recentPhotos.map((p) => (
                <div key={p.id} className="glass-panel" style={{ minWidth: 120, padding: 6, textAlign: 'center' }}>
                  <img src={p.photo_url} alt={p.kind} style={{ width: 108, height: 80, objectFit: 'cover', borderRadius: 6 }} />
                  <div style={{ fontSize: 11, marginTop: 4, textTransform: 'capitalize' }}>{p.kind?.replace('_', ' ')}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        <h3 style={{ margin: '30px 4px 4px' }}>{t('get_alerts')}</h3>
        <div className="glass-panel" style={{ padding: '16px 12px' }}>
          {subMessage ? <div className="dec-banner ok">{subMessage}</div> : (
            <form onSubmit={subscribe} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div>
                <label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>{t('email')}</label>
                <input type="email" required value={subEmail} onChange={e => setSubEmail(e.target.value)} style={{ width: '100%', padding: 8 }} />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>{t('city') || 'City'}</label>
                <select value={subCity} onChange={e => setSubCity(e.target.value)} style={{ width: '100%', padding: 8 }}>
                  {cities.filter(c => c.data_kind === 'real').map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>{t('min_level')}</label>
                <select value={subMinLevel} onChange={e => setSubMinLevel(e.target.value)} style={{ width: '100%', padding: 8 }}>
                  <option value="yellow">Yellow</option>
                  <option value="orange">Orange</option>
                  <option value="red">Red</option>
                </select>
              </div>
              <label style={{ display: 'flex', gap: 8, fontSize: 12, alignItems: 'flex-start', marginTop: 4 }}>
                <input type="checkbox" required checked={subConsent} onChange={e => setSubConsent(e.target.checked)} style={{ marginTop: 2 }} />
                <span>{t('consent_desc')}</span>
              </label>
              <input type="text" value={subHoneypot} onChange={e => setSubHoneypot(e.target.value)} style={{ display: 'none' }} tabIndex={-1} autoComplete="off" />
              <button type="submit" className="btn-primary" style={{ marginTop: 8, padding: 10 }}>{t('subscribe')}</button>
            </form>
          )}
        </div>
      </>)}
    </div>
  );
}
