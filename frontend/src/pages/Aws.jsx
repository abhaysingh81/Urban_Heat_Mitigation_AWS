import { useState, useEffect } from 'react';
import { API_BASE } from '../api';
import { useLang } from '../i18n';
import './Decision.css';

export default function Aws() {
  const { t } = useLang();
  const [data, setData] = useState(null);
  const [headers, setHeaders] = useState(null);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  useEffect(() => {
    let off = false;
    const fetchStatus = () => {
      fetch(`${API_BASE}/api/v1/system/status`)
        .then((r) => {
          if (!r.ok) throw new Error('Status failed');
          if (!off) {
            setHeaders({
              'X-Model-Version': r.headers.get('X-Model-Version'),
              'X-Data-Date': r.headers.get('X-Data-Date')
            });
          }
          return r.json();
        })
        .then((d) => {
          if (!off) {
            setData(d);
            setLastUpdated(new Date().toLocaleTimeString());
            setError(null);
          }
        })
        .catch((e) => {
          if (!off) setError(e.message || t('error'));
        });
    };

    fetchStatus();
    const iv = setInterval(fetchStatus, 60000);
    return () => {
      off = true;
      clearInterval(iv);
    };
  }, [t]);

  return (
    <div className="page-container" style={{ padding: 24, overflowY: 'auto' }}>
      <div className="page-header">
        <h1>{t('aws_title')}</h1>
        <p>{t('aws_sub')} {lastUpdated && `(Last updated: ${lastUpdated})`}</p>
      </div>

      {error && <div className="error-text">{error}</div>}

      <div className="dec-grid two" style={{ marginTop: 24 }}>
        <div className="glass-panel dec-card">
          <h3>{t('aws_features')}</h3>
          {data?.features ? (
            <ul>
              <li>Amazon Location (basemap, walking routes): {data.features.location_map ? 'on' : 'off'}</li>
              <li>Bedrock Knowledge Base (S3 Vectors): {data.features.knowledge_base ? 'on' : 'off'}</li>
              <li>Amazon Translate: {data.features.translate_languages.length ? data.features.translate_languages.join(', ') : 'off'}</li>
              <li>Alert email: {data.features.email_channel}</li>
              <li>Staff sign-in: {data.features.sign_in}</li>
              <li>Live officer updates (WebSocket API): {data.features.live_updates ? 'on' : 'off'}</li>
              <li>Street sensors (AWS IoT Core): {data.features.street_sensors ? 'on' : 'off'}</li>
              <li>AWS WAF on CloudFront: {data.features.waf ? 'on' : 'off'}</li>
              <li>Athena tables: {data.features.analytics ? 'on' : 'off'}</li>
            </ul>
          ) : <div>{data ? 'unavailable' : 'Loading...'}</div>}
        </div>

        <div className="glass-panel dec-card">
          <h3>Compute (Lambda)</h3>
          {data ? (
            <ul>
              <li>Function: {data.compute.function_name}</li>
              <li>Memory: {data.compute.memory_mb} MB</li>
              <li>Region: {data.compute.region}</li>
              <li>Timeout: {data.compute.timeout_s}s</li>
            </ul>
          ) : <div>Loading...</div>}
        </div>

        <div className="glass-panel dec-card">
          <h3>Cold Start</h3>
          {data ? (
            <div>{data.cold_start ? 'True (Server woke up for this request)' : 'False (Container reused)'}</div>
          ) : <div>Loading...</div>}
        </div>

        <div className="glass-panel dec-card">
          <h3>Model & Data (Headers)</h3>
          {headers ? (
            <ul>
              <li>X-Model-Version: {headers['X-Model-Version'] || 'unavailable'}</li>
              <li>X-Data-Date: {headers['X-Data-Date'] || 'unavailable'}</li>
            </ul>
          ) : <div>Loading...</div>}
        </div>

        <div className="glass-panel dec-card">
          <h3>AI (Bedrock)</h3>
          {data ? (
            <ul>
              <li>Model ID: {data.ai.model_id}</li>
              <li>Guardrail: {data.ai.guardrail_version}</li>
              <li>Knowledge Base: {data.ai.knowledge_base}</li>
            </ul>
          ) : <div>Loading...</div>}
        </div>

        <div className="glass-panel dec-card">
          <h3>Storage (DynamoDB Counts)</h3>
          {data ? (
            <ul>
              <li>Plans: {data.storage?.plans ?? 'unavailable'}</li>
              <li>Reports: {data.storage?.reports ?? 'unavailable'}</li>
            </ul>
          ) : <div>Loading...</div>}
        </div>

        <div className="glass-panel dec-card">
          <h3>Alerts (SNS)</h3>
          {data ? (
            data.alerts === 'unavailable' ? <div>unavailable</div> : (
              <ul>
                <li>Confirmed: {data.alerts?.confirmed ?? 0}</li>
                <li>Pending: {data.alerts?.pending ?? 0}</li>
              </ul>
            )
          ) : <div>Loading...</div>}
        </div>

        <div className="glass-panel dec-card">
          <h3>Daily Job</h3>
          {data ? (
            data.daily_job === 'unavailable' ? <div>unavailable</div> : (
              <ul>
                <li>Generated At: {data.daily_job?.generated_at ?? 'unavailable'}</li>
                <li>Stale: {data.daily_job?.stale ? 'True' : 'False'}</li>
              </ul>
            )
          ) : <div>Loading...</div>}
        </div>
      </div>
    </div>
  );
}
