import { useState } from 'react'
import { Link } from 'react-router-dom'
import api, { apiError } from '../api'
import { Field } from '../components/ui'
import reachLogo from '../assets/reach-logo-with-channels.png'

export default function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setErr(''); setBusy(true)
    try {
      await api.post('/auth/forgot-password', { email })
      // Same response whether or not the email is registered -- see
      // backend app/routers/auth.py::forgot_password.
      setSent(true)
    } catch (e2) {
      setErr(apiError(e2, 'Something went wrong'))
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
          <h1>Forgot password</h1>
          <p className="sub">Enter your account email and we'll send you a reset link.</p>

          {err && <div className="badge red mt8" style={{ marginBottom: 16 }}><span className="d" />{err}</div>}

          {sent ? (
            <div className="badge green mt8" style={{ marginBottom: 16 }}>
              <span className="d" />If that email is registered, a reset link has been sent. It's valid for 30 minutes.
            </div>
          ) : (
            <>
              <Field label="Email address">
                <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@company.com" required autoFocus />
              </Field>
              <button className="btn btn-primary" style={{ width: '100%', justifyContent: 'center', marginTop: 6 }}
                disabled={busy}>
                {busy ? 'Sending…' : 'Send reset link'}
              </button>
            </>
          )}

          <div className="cred-hint">
            <Link to="/login">← Back to sign in</Link>
          </div>
        </form>
      </div>
    </div>
  )
}
