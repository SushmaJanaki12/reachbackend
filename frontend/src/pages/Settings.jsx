import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import Layout from '../components/Layout'
import api, { apiError } from '../api'
import { useAuth } from '../auth'
import { Icon, Field, Modal, StatusBadge, Spinner, useToast } from '../components/ui'
import { SMTP_PROVIDER_DEFAULTS, SMTP_PROVIDER_OPTIONS, smtpProviderPasswordHint } from '../smtpProviders'

export default function Settings() {
  const { can } = useAuth()
  return (
    <Layout title="Settings" crumb="Administration / Settings">
      <div className="page-head">
        <div>
          <div className="pt">Channel settings</div>
          <div className="ps">Connection status and test tools for your communication channels.</div>
        </div>
      </div>
      <div className="grid grid-2" style={{ alignItems: 'start', marginBottom: 20 }}>
        <EmailPanel />
        <SmsPanel />
      </div>
      {can('system.configure') && <AdminSmtpSettings />}
    </Layout>
  )
}

function ConnRow({ label, value }) {
  return (
    <div className="flex between" style={{ padding: '9px 0', borderBottom: '1px solid var(--border)' }}>
      <span className="muted">{label}</span>
      <span className="t-strong" style={{ textAlign: 'right' }}>{value || '—'}</span>
    </div>
  )
}

function EmailPanel() {
  const toast = useToast()
  const [status, setStatus] = useState(null)
  const [testTo, setTestTo] = useState('')
  const [busy, setBusy] = useState('')

  useEffect(() => { api.get('/email/status').then((r) => setStatus(r.data)).catch(() => setStatus({ configured: false })) }, [])

  const verify = async () => {
    setBusy('verify')
    try { const { data } = await api.post('/email/verify'); toast.ok(`Connected · ${data.sender}`) }
    catch (e) { toast.err(apiError(e)) } finally { setBusy('') }
  }
  const sendTest = async () => {
    if (!testTo) return toast.err('Enter a recipient email')
    setBusy('test')
    try { await api.post('/email/test', { to: testTo }); toast.ok(`Test email sent to ${testTo}`) }
    catch (e) { toast.err(apiError(e)) } finally { setBusy('') }
  }

  const configured = status?.configured

  return (
    <div className="card card-pad">
      <div className="flex between" style={{ marginBottom: 14 }}>
        <div className="flex gap12">
          <span className="ico" style={{ width: 44, height: 44, borderRadius: 11, background: 'var(--teal-soft)', color: 'var(--teal)', display: 'grid', placeItems: 'center' }}><Icon.mail width={20} /></span>
          <div>
            <div style={{ fontWeight: 750, fontSize: 16 }}>Email</div>
            <div className="t-sub">Office 365 · Microsoft Graph</div>
          </div>
        </div>
        {status == null ? <div className="spinner" /> :
          <StatusBadge status={configured ? 'active' : 'inactive'} />}
      </div>

      {status == null ? <Spinner /> : configured ? (
        <>
          <ConnRow label="Provider" value={status.provider} />
          <ConnRow label="From address" value={status.from_email} />
          <div className="flex gap8 mt16">
            <button className="btn btn-ghost btn-sm" onClick={verify} disabled={busy}>
              {busy === 'verify' ? 'Verifying…' : <><Icon.check width={14} /> Verify connection</>}
            </button>
          </div>
          <div className="field mt16">
            <label>Send a test email</label>
            <div className="flex gap8">
              <input className="input" type="email" placeholder="you@company.com" value={testTo} onChange={(e) => setTestTo(e.target.value)} />
              <button className="btn btn-primary" onClick={sendTest} disabled={busy}>
                {busy === 'test' ? 'Sending…' : <><Icon.send width={14} /> Send</>}
              </button>
            </div>
          </div>
        </>
      ) : (
        <div className="empty" style={{ padding: '24px 10px' }}>
          <p className="muted">Not configured. Set the Office 365 credentials in the backend <code>.env</code> and restart.</p>
        </div>
      )}
    </div>
  )
}

function SmsPanel() {
  const toast = useToast()
  const [status, setStatus] = useState(null)
  const [testTo, setTestTo] = useState('')
  const [msg, setMsg] = useState('Test SMS from the Reach platform.')
  const [busy, setBusy] = useState(false)

  useEffect(() => { api.get('/sms/status').then((r) => setStatus(r.data)).catch(() => setStatus({ configured: false })) }, [])

  const sendTest = async () => {
    if (!testTo) return toast.err('Enter a recipient mobile number')
    setBusy(true)
    try { const { data } = await api.post('/sms/test', { to: testTo, message: msg }); toast.ok(`Test SMS accepted · ${data.response}`) }
    catch (e) { toast.err(apiError(e)) } finally { setBusy(false) }
  }

  const configured = status?.configured

  return (
    <div className="card card-pad">
      <div className="flex between" style={{ marginBottom: 14 }}>
        <div className="flex gap12">
          <span className="ico" style={{ width: 44, height: 44, borderRadius: 11, background: 'var(--teal-soft)', color: 'var(--teal)', display: 'grid', placeItems: 'center' }}><Icon.phone width={20} /></span>
          <div>
            <div style={{ fontWeight: 750, fontSize: 16 }}>SMS</div>
            <div className="t-sub">HTTP SMS gateway</div>
          </div>
        </div>
        {status == null ? <div className="spinner" /> :
          <StatusBadge status={configured ? 'active' : 'inactive'} />}
      </div>

      {status == null ? <Spinner /> : configured ? (
        <>
          <ConnRow label="Sender ID" value={status.sender} />
          <ConnRow label="DLT template" value={status.template_id} />
          <p className="t-sub mt8">Manage registered DLT templates under <Link to="/templates">Templates</Link>.</p>
          <div className="field mt16">
            <label>Send a test SMS</label>
            <input className="input" placeholder="Mobile number" value={testTo} onChange={(e) => setTestTo(e.target.value)} style={{ marginBottom: 8 }} />
            <textarea className="textarea" style={{ minHeight: 70 }} value={msg} onChange={(e) => setMsg(e.target.value)} />
            <button className="btn btn-primary mt8" onClick={sendTest} disabled={busy} style={{ alignSelf: 'flex-start' }}>
              {busy ? 'Sending…' : <><Icon.send width={14} /> Send test</>}
            </button>
          </div>
        </>
      ) : (
        <div className="empty" style={{ padding: '24px 10px' }}>
          <p className="muted">Sender <b>{status?.sender || '—'}</b> is set, but the gateway URL is missing. Add <code>SMS_API_URL</code> to the backend <code>.env</code> and restart to enable live SMS.</p>
        </div>
      )}
    </div>
  )
}

const BLANK_SMTP_CONFIG = {
  provider: 'custom', smtp_host: '', smtp_port: 587, encryption: 'starttls',
  username: '', password: '', from_email: '', from_name: '', reply_to: '', max_per_minute: 0,
}

function AdminSmtpSettings() {
  const toast = useToast()
  const [items, setItems] = useState(null)
  const [editing, setEditing] = useState(null)

  const load = () => api.get('/admin/smtp-settings').then((r) => setItems(r.data)).catch(() => setItems([]))
  useEffect(() => { load() }, [])

  const activate = async (row) => {
    try { await api.post(`/admin/smtp-settings/${row.id}/activate`); load(); toast.ok(`${row.smtp_host} is now the active sender`) }
    catch (e) { toast.err(apiError(e)) }
  }

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <div className="card-pad flex between">
        <div>
          <h3 style={{ fontSize: 16 }}>Admin SMTP settings</h3>
          <p className="t-sub">
            Workspace-wide default sender for campaigns with no project-level SMTP override. When no
            configuration here is active, sending falls back to Office 365.
          </p>
        </div>
        <button className="btn btn-primary btn-sm" onClick={() => setEditing({ ...BLANK_SMTP_CONFIG })}>
          <Icon.plus width={14} /> Add configuration
        </button>
      </div>
      {items === null ? <Spinner /> : items.length === 0 ? (
        <div className="empty" style={{ padding: '30px 20px' }}><p className="muted">No SMTP configurations yet. Campaigns fall back to Office 365.</p></div>
      ) : (
        <div className="table-wrap" style={{ border: 'none', borderRadius: 0, boxShadow: 'none' }}>
          <table>
            <thead><tr><th>Provider</th><th>Host</th><th>From</th><th>Status</th><th>Last test</th><th></th></tr></thead>
            <tbody>
              {items.map((row) => (
                <tr key={row.id}>
                  <td className="t-strong" style={{ textTransform: 'capitalize' }}>{row.provider}</td>
                  <td className="muted" style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>{row.smtp_host}:{row.smtp_port}</td>
                  <td className="muted">{row.from_name ? `${row.from_name} <${row.from_email}>` : row.from_email}</td>
                  <td><StatusBadge status={row.is_active ? 'active' : 'inactive'} /></td>
                  <td className="muted" style={{ fontSize: 12.5 }}>
                    {row.last_test_status === 'never' ? '—' : row.last_test_status === 'ok' ? 'Succeeded' : 'Failed'}
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <div className="flex gap8" style={{ justifyContent: 'flex-end' }}>
                      {!row.is_active && (
                        <button className="btn btn-ghost btn-sm" onClick={() => activate(row)}>Activate</button>
                      )}
                      <button className="btn btn-ghost btn-sm" onClick={() => setEditing(row)}><Icon.edit width={13} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && (
        <AdminSmtpModal initial={editing} toast={toast} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); toast.ok('SMTP configuration saved') }}
          onError={(m) => toast.err(m)} />
      )}
    </div>
  )
}

function AdminSmtpModal({ initial, toast, onClose, onSaved, onError }) {
  const isNew = !initial.id
  const [f, setF] = useState({ ...initial, password: '' })
  const [busy, setBusy] = useState(false)
  const [testing, setTesting] = useState(false)
  const [sendingTest, setSendingTest] = useState(false)
  const [testTo, setTestTo] = useState('')
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }))

  const setProvider = (provider) => {
    set('provider', provider)
    const defaults = SMTP_PROVIDER_DEFAULTS[provider]
    if (defaults) {
      set('smtp_host', defaults.smtp_host)
      set('smtp_port', defaults.smtp_port)
      set('encryption', defaults.encryption)
    }
  }

  const payload = () => ({
    provider: f.provider, smtp_host: f.smtp_host, smtp_port: f.smtp_port, encryption: f.encryption,
    username: f.username, password: f.password, from_email: f.from_email, from_name: f.from_name,
    reply_to: f.reply_to, max_per_minute: f.max_per_minute,
  })

  const save = async () => {
    setBusy(true)
    try {
      if (isNew) await api.post('/admin/smtp-settings', payload())
      else await api.put(`/admin/smtp-settings/${initial.id}`, payload())
      onSaved()
    } catch (e) { onError(apiError(e)) } finally { setBusy(false) }
  }

  const testConnection = async () => {
    setTesting(true)
    try {
      const { data } = await api.post(`/admin/smtp-settings/${initial.id}/test-connection`)
      toast.ok(data.message || 'SMTP connection successful!')
    } catch (e) { toast.err(apiError(e, 'SMTP test failed')) } finally { setTesting(false) }
  }

  const sendTestEmail = async () => {
    if (!testTo) return toast.err('Enter a recipient email for the test')
    setSendingTest(true)
    try {
      await api.post(`/admin/smtp-settings/${initial.id}/send-test-email`, { to: testTo })
      toast.ok(`Test email sent to ${testTo}`)
    } catch (e) { toast.err(apiError(e, 'Send test email failed')) } finally { setSendingTest(false) }
  }

  const providerHint = smtpProviderPasswordHint(f.provider)

  return (
    <Modal title={isNew ? 'Add SMTP configuration' : `Edit — ${initial.smtp_host}`} onClose={onClose}
      footer={<>
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={busy || !f.smtp_host || !f.from_email}>
          {busy ? 'Saving…' : 'Save'}
        </button>
      </>}>
      <Field label="Provider" hint="Drives host/port/encryption auto-fill — still editable after.">
        <select className="select" value={f.provider} onChange={(e) => setProvider(e.target.value)}>
          {SMTP_PROVIDER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </Field>
      <div className="row-2">
        <Field label="SMTP host"><input className="input" value={f.smtp_host} onChange={(e) => set('smtp_host', e.target.value)} placeholder="smtp.example.com" /></Field>
        <Field label="SMTP port"><input className="input" type="number" value={f.smtp_port} onChange={(e) => set('smtp_port', Number(e.target.value))} /></Field>
      </div>
      <Field label="Encryption">
        <select className="select" value={f.encryption} onChange={(e) => set('encryption', e.target.value)}>
          <option value="none">None</option>
          <option value="starttls">STARTTLS</option>
          <option value="ssl">SSL/TLS</option>
        </select>
      </Field>
      <div className="row-2">
        <Field label="Username"><input className="input" value={f.username} onChange={(e) => set('username', e.target.value)} /></Field>
        <Field label="Password" hint={providerHint}>
          <input className="input" type="password" value={f.password} onChange={(e) => set('password', e.target.value)}
            placeholder={!isNew && initial.has_password ? '••••••••• (leave blank to keep)' : ''} />
        </Field>
      </div>
      <div className="row-2">
        <Field label="From name"><input className="input" value={f.from_name} onChange={(e) => set('from_name', e.target.value)} placeholder="Acme" /></Field>
        <Field label="From email"><input className="input" type="email" value={f.from_email} onChange={(e) => set('from_email', e.target.value)} placeholder="noreply@acme.com" /></Field>
      </div>
      <div className="row-2">
        <Field label="Reply-to" hint="Optional"><input className="input" type="email" value={f.reply_to} onChange={(e) => set('reply_to', e.target.value)} /></Field>
        <Field label="Max sends / minute" hint="0 = unlimited"><input className="input" type="number" min={0} value={f.max_per_minute} onChange={(e) => set('max_per_minute', Number(e.target.value))} /></Field>
      </div>

      {!isNew && (
        <div className="flex gap12" style={{ alignItems: 'center', flexWrap: 'wrap', padding: '4px 0' }}>
          <button className="btn btn-ghost" onClick={testConnection} disabled={testing}>
            <Icon.check width={14} /> {testing ? 'Testing…' : 'Test connection'}
          </button>
          <div className="flex gap8">
            <input className="input" type="email" placeholder="you@company.com" value={testTo}
              onChange={(e) => setTestTo(e.target.value)} style={{ width: 200 }} />
            <button className="btn btn-ghost" onClick={sendTestEmail} disabled={sendingTest}>
              <Icon.send width={14} /> {sendingTest ? 'Sending…' : 'Send test email'}
            </button>
          </div>
          {initial.last_test_status !== 'never' && (
            <span className="t-sub">
              Last test: {initial.last_test_status === 'ok' ? 'succeeded' : 'failed'}
              {initial.last_tested_at ? ` · ${new Date(initial.last_tested_at).toLocaleString()}` : ''}
            </span>
          )}
        </div>
      )}
    </Modal>
  )
}

