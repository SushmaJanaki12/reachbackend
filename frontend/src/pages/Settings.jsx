import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import Layout from '../components/Layout'
import api, { apiError } from '../api'
import { useAuth } from '../auth'
import { Icon, Field, Modal, StatusBadge, Toggle, Spinner, useToast } from '../components/ui'
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
      {can('system.configure') && <QueueHealthPanel />}
      {can('system.configure') && <ReplyCapturePanel />}
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

function QueueHealthPanel() {
  const [status, setStatus] = useState(null)

  const load = () => api.get('/admin/queue-status').then((r) => setStatus(r.data)).catch(() => setStatus(null))
  // 15s: fast enough that killing the worker process shows up as "not
  // responding" on the next poll rather than requiring a manual refresh.
  useEffect(() => { load(); const interval = setInterval(load, 15000); return () => clearInterval(interval) }, [])

  const healthy = status?.healthy
  const stuck = status?.stuck_campaigns || []

  return (
    <div className="card card-pad" style={{ marginBottom: 20 }}>
      <div className="flex between" style={{ marginBottom: 14 }}>
        <div className="flex gap12">
          <span className="ico" style={{ width: 44, height: 44, borderRadius: 11, background: 'var(--teal-soft)', color: 'var(--teal)', display: 'grid', placeItems: 'center' }}><Icon.chart width={20} /></span>
          <div>
            <div style={{ fontWeight: 750, fontSize: 16 }}>Send queue</div>
            <div className="t-sub">Worker process health and campaign delivery pipeline</div>
          </div>
        </div>
        {status == null ? <div className="spinner" /> :
          <StatusBadge status={healthy ? 'active' : 'failed'} />}
      </div>

      {status == null ? <Spinner /> : (
        <>
          <ConnRow label="Worker" value={healthy ? 'Responding' : 'Not responding'} />
          <ConnRow label="Workers registered" value={status.worker_count} />
          <ConnRow label="Last heartbeat" value={status.last_heartbeat ? new Date(status.last_heartbeat).toLocaleString() : '—'} />
          <ConnRow label="Queue depth" value={status.queue_depth} />
          <ConnRow label="Oldest queued job"
            value={status.oldest_job_age_seconds != null ? `${Math.round(status.oldest_job_age_seconds)}s` : '—'} />

          {!healthy && (
            <div className="empty" style={{ padding: '14px 10px', marginTop: 12, textAlign: 'left' }}>
              <p className="muted">
                No worker has checked in recently. Campaigns will queue but not send until
                <code> python -m app.worker</code> is running again.
              </p>
            </div>
          )}

          {stuck.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div className="t-strong" style={{ marginBottom: 8 }}>Stuck campaigns</div>
              {stuck.map((s) => (
                <div key={s.id} className="flex between" style={{ padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
                  <Link to={`/campaigns/${s.id}`}>{s.name}</Link>
                  <span className="muted">no activity for {s.minutes_stuck}m</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function intervalLabel(secs) {
  if (!secs) return '—'
  if (secs < 60) return `${secs}s`
  const mins = Math.round(secs / 60)
  return `${mins} minute${mins !== 1 ? 's' : ''}`
}

const BLANK_REPLY_CAPTURE = {
  enabled: false, mailbox_address: '', imap_host: '', imap_port: 993, imap_use_ssl: true,
  imap_username: '', imap_password: '', poll_folder: 'INBOX', poll_interval_seconds: 120,
}

function ReplyCapturePanel() {
  const toast = useToast()
  const [settings, setSettings] = useState(null)
  const [editing, setEditing] = useState(null)
  const [busy, setBusy] = useState('')

  const load = () => api.get('/admin/reply-capture').then((r) => setSettings(r.data)).catch(() => setSettings(null))
  useEffect(() => { load() }, [])

  const testConnection = async () => {
    setBusy('test')
    try { await api.post('/admin/reply-capture/test-connection'); toast.ok('IMAP connection successful') }
    catch (e) { toast.err(apiError(e, 'Connection failed')) } finally { setBusy('') }
  }

  const pollNow = async () => {
    setBusy('poll')
    try {
      const { data } = await api.post('/admin/reply-capture/poll-now')
      toast.ok(`Polled now — ${data.matched ?? 0} repl${data.matched === 1 ? 'y' : 'ies'} matched`)
      load()
    } catch (e) { toast.err(apiError(e, 'Poll failed')) } finally { setBusy('') }
  }

  return (
    <div className="card card-pad" style={{ marginBottom: 20 }}>
      <div className="flex between" style={{ marginBottom: 14 }}>
        <div className="flex gap12">
          <span className="ico" style={{ width: 44, height: 44, borderRadius: 11, background: 'var(--teal-soft)', color: 'var(--teal)', display: 'grid', placeItems: 'center' }}><Icon.mail width={20} /></span>
          <div>
            <div style={{ fontWeight: 750, fontSize: 16 }}>Reply capture</div>
            <div className="t-sub">Inbound reply detection for real campaigns, via IMAP polling</div>
          </div>
        </div>
        {settings == null ? <div className="spinner" /> : <StatusBadge status={settings.enabled ? 'active' : 'inactive'} />}
      </div>

      {settings == null ? <Spinner /> : (
        <>
          <ConnRow label="Mailbox" value={settings.mailbox_address} />
          <ConnRow label="IMAP host" value={settings.imap_host ? `${settings.imap_host}:${settings.imap_port}` : ''} />
          <ConnRow label="Checks for replies every" value={intervalLabel(settings.poll_interval_seconds)} />
          <ConnRow label="Last poll" value={settings.last_polled_at
            ? `${settings.last_poll_status === 'ok' ? 'Succeeded' : 'Failed'} · ${new Date(settings.last_polled_at).toLocaleString()}`
            : 'Never'} />
          {settings.last_poll_status === 'failed' && settings.last_poll_error && (
            <p className="hint" style={{ color: 'var(--danger)' }}>⚠ {settings.last_poll_error}</p>
          )}
          {settings.enabled && (
            <p className="hint mt8">
              A real reply can take up to {intervalLabel(settings.poll_interval_seconds)} to be detected here.
              A follow-up step's "No reply" delay shorter than that risks firing on top of a reply that just
              hasn't been picked up yet — keep step delays comfortably longer than this interval, or shorten
              it below if that matters for a campaign.
            </p>
          )}
          <div className="flex gap8 mt16">
            <button className="btn btn-ghost btn-sm" onClick={() => setEditing({ ...BLANK_REPLY_CAPTURE, ...settings, imap_password: '' })}>
              <Icon.edit width={13} /> Edit
            </button>
            {settings.imap_host && (
              <button className="btn btn-ghost btn-sm" onClick={testConnection} disabled={busy === 'test'}>
                {busy === 'test' ? 'Testing…' : <><Icon.check width={14} /> Test connection</>}
              </button>
            )}
            {settings.enabled && (
              <button className="btn btn-ghost btn-sm" onClick={pollNow} disabled={busy === 'poll'}>
                {busy === 'poll' ? 'Polling…' : 'Poll now'}
              </button>
            )}
          </div>
        </>
      )}

      {editing && (
        <ReplyCaptureModal initial={editing} hasPassword={!!settings?.has_password} toast={toast}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); toast.ok('Reply capture settings saved') }} />
      )}
    </div>
  )
}

function ReplyCaptureModal({ initial, hasPassword, toast, onClose, onSaved }) {
  const [f, setF] = useState(initial)
  const [busy, setBusy] = useState(false)
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }))

  const save = async () => {
    setBusy(true)
    const payload = { ...f }
    if (!payload.imap_password) delete payload.imap_password
    try {
      await api.put('/admin/reply-capture', payload)
      onSaved()
    } catch (e) { toast.err(apiError(e)) } finally { setBusy(false) }
  }

  return (
    <Modal title="Reply capture settings" onClose={onClose}
      footer={<>
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
      </>}>
      <Field label="Enabled">
        <Toggle checked={!!f.enabled} onChange={(v) => set('enabled', v)} label={f.enabled ? 'Polling for replies' : 'Disabled'} />
      </Field>
      <Field label="Mailbox address"
        hint="Outbound campaign emails get Reply-To set to a +token alias of this address, so a reply routes back here regardless of which SMTP sent the original message.">
        <input className="input" value={f.mailbox_address} onChange={(e) => set('mailbox_address', e.target.value)} placeholder="replies@yourdomain.com" />
      </Field>
      <div className="row-2">
        <Field label="IMAP host"><input className="input" value={f.imap_host} onChange={(e) => set('imap_host', e.target.value)} placeholder="imap.example.com" /></Field>
        <Field label="IMAP port"><input className="input" type="number" value={f.imap_port} onChange={(e) => set('imap_port', Number(e.target.value))} /></Field>
      </div>
      <Field label="Use SSL">
        <Toggle checked={!!f.imap_use_ssl} onChange={(v) => set('imap_use_ssl', v)} label={f.imap_use_ssl ? 'SSL' : 'Plain'} />
      </Field>
      <div className="row-2">
        <Field label="Username"><input className="input" value={f.imap_username} onChange={(e) => set('imap_username', e.target.value)} /></Field>
        <Field label="Password" hint={hasPassword ? 'Leave blank to keep the saved password' : ''}>
          <input className="input" type="password" value={f.imap_password || ''} onChange={(e) => set('imap_password', e.target.value)}
            placeholder={hasPassword ? '••••••••• (leave blank to keep)' : ''} />
        </Field>
      </div>
      <div className="row-2">
        <Field label="Folder"><input className="input" value={f.poll_folder} onChange={(e) => set('poll_folder', e.target.value)} /></Field>
        <Field label="Poll interval (seconds)" hint="How often the worker checks the mailbox — shown above and referenced in the Follow-ups tab.">
          <input className="input" type="number" min={30} value={f.poll_interval_seconds} onChange={(e) => set('poll_interval_seconds', Number(e.target.value))} />
        </Field>
      </div>
    </Modal>
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

