// Optional AWS features as seen from the browser: which ones this deployment has (asked from the
// API once, so the frontend never needs rebuilding to switch one on) and staff sign-in.
import { API_BASE } from './api';

const DEFAULT_CONFIG = { auth: { mode: 'open', roles: [] }, live: { ws_url: null }, translate: { languages: [] }, sensors: false };
let configPromise = null;

export function loadConfig() {
  if (!configPromise) {
    configPromise = fetch(`${API_BASE}/api/v1/system/config`)
      .then((r) => (r.ok ? r.json() : DEFAULT_CONFIG))
      .catch(() => DEFAULT_CONFIG);
  }
  return configPromise;
}

// ── staff session (Amazon Cognito). Citizens never sign in. ──
const SESSION_KEY = 'heatrelief-staff';

function claims(jwt) {
  try {
    const part = jwt.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(decodeURIComponent(escape(atob(part))));
  } catch { return {}; }
}

export function staffSession() {
  try {
    const s = JSON.parse(sessionStorage.getItem(SESSION_KEY) || 'null');
    if (!s || s.expires_at < Date.now() + 30000) return null;   // expired, or about to
    return s;
  } catch { return null; }
}

export function signOut() {
  try { sessionStorage.removeItem(SESSION_KEY); } catch { /* storage may be blocked */ }
}

async function cognito(region, target, body) {
  const res = await fetch(`https://cognito-idp.${region}.amazonaws.com/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-amz-json-1.1', 'X-Amz-Target': `AWSCognitoIdentityProviderService.${target}` },
    body: JSON.stringify(body),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json.message || 'Sign-in failed');
  return json;
}

function store(email, result) {
  const c = claims(result.AccessToken);
  const s = { email, access_token: result.AccessToken, groups: c['cognito:groups'] || [],
    expires_at: Date.now() + (result.ExpiresIn || 3600) * 1000 };
  try { sessionStorage.setItem(SESSION_KEY, JSON.stringify(s)); } catch { /* storage may be blocked */ }
  return s;
}

// Returns { session } when signed in, or { challenge: 'NEW_PASSWORD_REQUIRED', token } on a first
// sign-in with the temporary password an administrator issued.
export async function signIn(auth, email, password) {
  const r = await cognito(auth.region, 'InitiateAuth', {
    AuthFlow: 'USER_PASSWORD_AUTH', ClientId: auth.client_id, AuthParameters: { USERNAME: email, PASSWORD: password } });
  if (r.AuthenticationResult) return { session: store(email, r.AuthenticationResult) };
  if (r.ChallengeName === 'NEW_PASSWORD_REQUIRED') return { challenge: r.ChallengeName, token: r.Session };
  throw new Error(`Sign-in needs a step this page does not support (${r.ChallengeName || 'unknown'})`);
}

export async function setNewPassword(auth, email, newPassword, challengeToken) {
  const r = await cognito(auth.region, 'RespondToAuthChallenge', {
    ChallengeName: 'NEW_PASSWORD_REQUIRED', ClientId: auth.client_id, Session: challengeToken,
    ChallengeResponses: { USERNAME: email, NEW_PASSWORD: newPassword } });
  if (!r.AuthenticationResult) throw new Error('Could not set the new password');
  return { session: store(email, r.AuthenticationResult) };
}

// Headers for officer/planner calls: the Cognito session if there is one, else the older shared token.
export function staffHeaders(officerToken) {
  const s = staffSession();
  if (s) return { Authorization: `Bearer ${s.access_token}` };
  return officerToken ? { 'X-Officer-Token': officerToken } : {};
}
