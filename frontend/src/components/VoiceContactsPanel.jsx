import { useCallback, useEffect, useState } from 'react';
import { API_BASE } from '../api';
import { useLang } from '../i18n';
import { staffHeaders } from '../platform';

// Ward-officer panel: people without smartphones who get a heat-alert phone call (Amazon Connect +
// Polly) on red days. Officers add someone only after asking them, and record who agreed and how.
// Numbers come back masked; a contact expires after a year unless re-added.
export default function VoiceContactsPanel({ city, wards }) {
  const { t } = useLang();
  const [data, setData] = useState(null);
  const [form, setForm] = useState({ phone: '', ward_id: '', language: 'hi', consent_note: '' });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const r = await fetch(`${API_BASE}/api/v1/phone-alerts/voice/contacts?city=${city}`, { headers: staffHeaders() });
    const d = await r.json().catch(() => ({}));
    if (r.ok) { setData(d); setError(null); } else setError(d.detail || t('error'));
  }, [city, t]);

  useEffect(() => {
    let active = true;
    Promise.resolve().then(() => active && load());
    return () => { active = false; };
  }, [load]);

  const add = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await fetch(`${API_BASE}/api/v1/phone-alerts/voice/contacts?city=${city}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...staffHeaders() }, body: JSON.stringify(form) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : t('error'));
      setForm((f) => ({ ...f, phone: '', consent_note: '' }));
      await load();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  const remove = async (id) => {
    const r = await fetch(`${API_BASE}/api/v1/phone-alerts/voice/contacts/${encodeURIComponent(id)}`,
      { method: 'DELETE', headers: staffHeaders() });
    if (r.ok) setData((d) => ({ ...d, contacts: d.contacts.filter((c) => c.id !== id) }));
    else setError(t('error'));
  };

  const wardName = (id) => wards.find((w) => w.ward_id === id)?.ward_name || id;
  return (
    <div className="glass-panel dec-card" style={{ marginTop: 16 }}>
      <h3>{t('voice_title')}</h3>
      <div className="dec-note">{t('voice_sub')}</div>
      {data && !data.enabled && <div className="dec-note" style={{ marginTop: 6 }}>{t('voice_off')}</div>}
      <form onSubmit={add} className="grid2" style={{ marginTop: 10, gap: 8, alignItems: 'end' }}>
        <label className="dec-note">{t('mobile_number')}
          <input className="num" type="tel" required value={form.phone} placeholder="98765 43210"
            onChange={(e) => setForm({ ...form, phone: e.target.value })} /></label>
        <label className="dec-note">{t('ward')}
          <select required value={form.ward_id} onChange={(e) => setForm({ ...form, ward_id: e.target.value })} style={{ width: '100%' }}>
            <option value="">—</option>
            {wards.map((w) => <option key={w.ward_id} value={w.ward_id}>{w.ward_name}</option>)}
          </select></label>
        <label className="dec-note">{t('language')}
          <select value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })} style={{ width: '100%' }}>
            <option value="hi">हिंदी</option><option value="en">English</option>
          </select></label>
        <label className="dec-note">{t('voice_consent')}
          <input className="num" required minLength={3} maxLength={200} value={form.consent_note}
            placeholder={t('voice_consent_ph')} onChange={(e) => setForm({ ...form, consent_note: e.target.value })} /></label>
        <button className="btn-primary" type="submit" disabled={busy}>{t('voice_add')}</button>
      </form>
      {error && <div className="error-text" style={{ marginTop: 8 }}>{error}</div>}
      {data?.contacts?.length > 0 && (
        <table className="dec-table" style={{ marginTop: 10 }}>
          <tbody>{data.contacts.map((c) => (
            <tr key={c.id}><td>{c.phone}</td><td>{wardName(c.ward_id)}</td><td>{c.language === 'hi' ? 'हिंदी' : 'English'}</td>
              <td className="dec-note">{t('voice_by')} {c.consent_by}</td>
              <td><button className="btn-ghost" style={{ padding: '4px 10px' }} onClick={() => remove(c.id)}>{t('voice_remove')}</button></td></tr>))}
          </tbody></table>)}
      {data && data.contacts.length === 0 && <div className="dec-note" style={{ marginTop: 8 }}>—</div>}
    </div>);
}
