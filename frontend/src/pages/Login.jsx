import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { apiError } from '../api'
import { Field } from '../components/ui'
import reachLogo from '../assets/reach-logo-with-channels.png'

export default function Login() {
  const { login, user } = useAuth()
  const nav = useNavigate()
  const [email, setEmail] = useState('admin@reach.io')
  const [password, setPassword] = useState('Admin@123')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  if (user) { nav('/'); return null }

  const submit = async (e) => {
    e.preventDefault()
    setErr(''); setBusy(true)
    try {
      await login(email, password)
      nav('/')
    } catch (e2) {
      setErr(apiError(e2, 'Login failed'))
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
          <h1>Welcome back</h1>
          <p className="sub">Sign in to your Reach workspace.</p>

          {err && <div className="badge red mt8" style={{ marginBottom: 16 }}><span className="d" />{err}</div>}

          <Field label="Email address">
            <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com" required />
          </Field>
          <Field label="Password">
            <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••" required />
          </Field>
          <div style={{ textAlign: 'right', marginTop: -8, marginBottom: 14 }}>
            <Link to="/forgot-password" className="t-sub">Forgot password?</Link>
          </div>

          <button className="btn btn-primary" style={{ width: '100%', justifyContent: 'center', marginTop: 6 }}
            disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>

          <div className="cred-hint">
            <b>Demo accounts</b><br />
            Admin — <code>admin@reach.io</code> / <code>Admin@123</code><br />
            User — <code>user@reach.io</code> / <code>User@123</code>
          </div>
        </form>
      </div>
    </div>
  )
}
