import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import api, { apiError } from '../api'
import { Field } from '../components/ui'
import reachLogo from '../assets/reach-logo-with-channels.png'

export default function ResetPassword() {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const token = params.get('token') || ''
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [done, setDone] = useState(false)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setErr('')
    if (password !== confirm) { setErr('Passwords do not match'); return }
    setBusy(true)
    try {
      await api.post('/auth/reset-password', { token, new_password: password })
      setDone(true)
    } catch (e2) {
      setErr(apiError(e2, 'This reset link is invalid or has expired. Request a new one.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-wrap">
      <div className="auth-brand">
        <div className="waves" />
        <div className="auth-logo"><img src={reachLogo} alt="Reach — Reach Beyond Channels" className="auth-logo-img" /></div>
        <div className="auth-tag">
          <h2>One campaign. Every channel. A single click.</h2>
          <p>Create projects, import recipients, personalize content, and reach everyone across Email, WhatsApp &amp; SMS.</p>
        </div>
        <div className="auth-foot">Reach · Campaign Management Platform</div>
      </div>

      <div className="auth-form-side">
        <form className="auth-card" onSubmit={submit}>
          <h1>Reset password</h1>
          <p className="sub">Choose a new password for your account.</p>

          {err && <div className="badge red mt8" style={{ marginBottom: 16 }}><span className="d" />{err}</div>}

          {!token ? (
            <div className="badge red mt8" style={{ marginBottom: 16 }}>
              <span className="d" />This link is missing its reset token. Request a new one.
            </div>
          ) : done ? (
            <>
              <div className="badge green mt8" style={{ marginBottom: 16 }}>
                <span className="d" />Password updated — you can now sign in.
              </div>
              <button type="button" className="btn btn-primary" style={{ width: '100%', justifyContent: 'center' }}
                onClick={() => nav('/login')}>
                Go to sign in
              </button>
            </>
          ) : (
            <>
              <Field label="New password" hint="At least 8 characters">
                <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••" minLength={8} required autoFocus />
              </Field>
              <Field label="Confirm new password">
                <input className="input" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)}
                  placeholder="••••••••" minLength={8} required />
              </Field>
              <button className="btn btn-primary" style={{ width: '100%', justifyContent: 'center', marginTop: 6 }}
                disabled={busy}>
                {busy ? 'Saving…' : 'Reset password'}
              </button>
            </>
          )}

          <div className="cred-hint">
            <Link to="/forgot-password">Request a new link</Link> · <Link to="/login">Back to sign in</Link>
          </div>
        </form>
      </div>
    </div>
  )
}
