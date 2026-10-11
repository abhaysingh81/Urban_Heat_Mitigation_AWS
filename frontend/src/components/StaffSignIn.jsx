import { useState } from 'react';
import { useLang } from '../i18n';
import { signIn, setNewPassword, signOut, staffSession } from '../platform';

// Sign-in box for ward officers and city planners (Amazon Cognito). Accounts are issued by an
// administrator; on the first sign-in the temporary password must be replaced.
export default function StaffSignIn({ auth, onChange }) {
  const { t } = useLang();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [challenge, setChallenge] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const session = staffSession();

  if (session) {
    return (
      <div className="btn-row" style={{ alignItems: 'center' }}>
        <span className="dec-note">{t('signed_in_as')} {session.email} · {session.groups.join(', ') || t('no_role')}</span>
        <button className="btn-ghost" onClick={() => { signOut(); onChange?.(null); }}>{t('sign_out')}</button>
      </div>);
  }

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const r = challenge
        ? await setNewPassword(auth, email, password, challenge)
        : await signIn(auth, email, password);
      if (r.challenge) { setChallenge(r.token); setPassword(''); } else { setChallenge(null); setPassword(''); onChange?.(r.session); }
    } catch (err) { setError(err.message || String(err)); } finally { setBusy(false); }
  };

  return (
    <form onSubmit={submit} className="btn-row" style={{ alignItems: 'center' }}>
      {!challenge && <input className="num" style={{ width: 200 }} type="email" required autoComplete="username"
        placeholder={t('email')} aria-label={t('email')} value={email} onChange={(e) => setEmail(e.target.value)} />}
      <input className="num" style={{ width: 190 }} type="password" required minLength={challenge ? 10 : 1}
        autoComplete={challenge ? 'new-password' : 'current-password'}
        placeholder={challenge ? t('new_password') : t('password')} aria-label={challenge ? t('new_password') : t('password')}
        value={password} onChange={(e) => setPassword(e.target.value)} />
      <button className="btn-primary" type="submit" disabled={busy}>{busy ? t('loading') : (challenge ? t('set_password') : t('sign_in'))}</button>
      {challenge && <div className="dec-note" style={{ flexBasis: '100%' }}>{t('new_password_hint')}</div>}
      {error && <div className="error-text" style={{ flexBasis: '100%' }}>{error}</div>}
    </form>);
}
