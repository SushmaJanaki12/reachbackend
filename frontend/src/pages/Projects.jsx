import { useEffect, useRef, useState } from 'react'
import Layout from '../components/Layout'
import { useAuth } from '../auth'
import api, { apiError } from '../api'
import { Icon, Modal, Field, Toggle, StatusBadge, Spinner, useToast } from '../components/ui'
import { SMTP_PROVIDER_DEFAULTS, SMTP_PROVIDER_OPTIONS, smtpProviderPasswordHint } from '../smtpProviders'

const BLANK = {
  name: '', email: '', description: '', notes: '', logo_url: '', status: 'active',
  sms_active: false, sms_provider: '', whatsapp_active: false, whatsapp_provider: '',
  smtp_enabled: false, smtp_provider: 'custom', smtp_host: '', smtp_port: 587, smtp_encryption: 'starttls',
  smtp_username: '', smtp_password: '', smtp_from_name: '', smtp_from_email: '', smtp_reply_to: '',
  smtp_fallback_on_failure: false, smtp_max_per_minute: 0,
  smtp_last_tested_at: null, smtp_last_test_status: 'never',
  company_website: '', company_address: '', sender_name: '', sender_designation: '', sender_phone: '',
  badge1_url: '', badge2_url: '', badge3_url: '',
  member_ids: [],
}

export default function Projects() {
  const { can } = useAuth()
  const toast = useToast()
  const [projects, setProjects] = useState(null)
  const [editing, setEditing] = useState(null)

  const load = () => api.get('/projects').then((r) => setProjects(r.data)).catch(() => setProjects([]))
  useEffect(() => { load() }, [])

  const remove = async (p) => {
    if (!window.confirm(`Delete project "${p.name}"? This permanently deletes all its campaigns, recipients and content. This cannot be undone.`)) return
    try { await api.delete(`/projects/${p.id}`); load(); toast.ok('Project deleted') }
    catch (e) { toast.err(apiError(e)) }
  }

  return (
    <Layout title="Projects" crumb="Workspace / Projects">
      <div className="page-head">
        <div>
          <div className="pt">Projects</div>
          <div className="ps">Client projects and their WhatsApp &amp; SMS configuration.</div>
        </div>
        {can('project.create') && (
          <button className="btn btn-primary" onClick={() => setEditing({ ...BLANK })}>
            <Icon.plus width={16} /> New project
          </button>
        )}
      </div>

      {projects === null ? <Spinner /> : projects.length === 0 ? (
        <div className="card empty">
          <div className="ico"><Icon.folder width={26} /></div>
          <h3 style={{ marginBottom: 6 }}>No projects yet</h3>
          <p className="muted" style={{ marginBottom: 16 }}>Create a project to start building campaigns.</p>
          {can('project.create') && <button className="btn btn-primary" onClick={() => setEditing({ ...BLANK })}><Icon.plus width={16} /> New project</button>}
        </div>
      ) : (
        <div className="grid grid-3">
          {projects.map((p) => (
            <div key={p.id} className="card card-pad" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div className="flex between">
                <span className="ico" style={{ width: 42, height: 42, borderRadius: 11, background: 'var(--teal-soft)', color: 'var(--teal)', display: 'grid', placeItems: 'center' }}>
                  <Icon.folder width={20} />
                </span>
                <StatusBadge status={p.status} />
              </div>
              <div>
                <div style={{ fontWeight: 700, fontSize: 16 }}>{p.name}</div>
                <div className="t-sub">{p.email}</div>
              </div>
              {p.description && <p className="muted" style={{ fontSize: 13, margin: 0 }}>{p.description}</p>}
              <div className="wrap-gap">
                <span className={`chchip on`}><Icon.mail width={13} /> Email</span>
                <span className={`chchip ${p.whatsapp_active ? 'on' : ''}`}><Icon.chat width={13} /> WhatsApp</span>
                <span className={`chchip ${p.sms_active ? 'on' : ''}`}><Icon.phone width={13} /> SMS</span>
              </div>
              <div className="flex between mt8" style={{ borderTop: '1px solid var(--border)', paddingTop: 12 }}>
                <span className="t-sub">{p.campaign_count} campaign{p.campaign_count !== 1 ? 's' : ''}</span>
                <div className="flex gap8">
                  {can('project.edit') && (
                    <button className="btn btn-ghost btn-sm" onClick={() => setEditing({ ...BLANK, ...p, member_ids: [] })}>
                      <Icon.settings width={14} /> Configure
                    </button>
                  )}
                  {can('project.delete') && (
                    <button className="btn btn-ghost btn-sm" onClick={() => remove(p)}>
                      <Icon.trash width={13} /> Delete
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <ProjectModal
          initial={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); toast.ok('Project saved') }}
          onError={(m) => toast.err(m)}
        />
      )}
    </Layout>
  )
}

function ProjectModal({ initial, onClose, onSaved, onError }) {
  const { can } = useAuth()
  const toast = useToast()
  const isNew = !initial.id
  const [tab, setTab] = useState('details')
  const [f, setF] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [users, setUsers] = useState([])
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }))

  useEffect(() => {
    if (can('user.manage')) api.get('/users').then((r) => setUsers(r.data)).catch(() => {})
  }, [])

  const save = async () => {
    setBusy(true)
    try {
      if (isNew) await api.post('/projects', f)
      else await api.put(`/projects/${initial.id}`, f)
      onSaved()
    } catch (e) { onError(apiError(e, 'Could not save project')) } finally { setBusy(false) }
  }

  const TABS = [['details', 'Details'], ['email', 'Email / SMTP'], ['sms', 'SMS'], ['whatsapp', 'WhatsApp'], ['branding', 'Branding']]
  if (can('user.manage')) TABS.push(['members', 'Members'])

  return (
    <Modal wide title={isNew ? 'New project' : `Configure — ${initial.name}`} onClose={onClose}
      footer={<>
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={busy || !f.name || !f.email}>
          {busy ? 'Saving…' : isNew ? 'Create project' : 'Save changes'}
        </button>
      </>}>
      <div className="tabs">
        {TABS.map(([k, l]) => <div key={k} className={`tab ${tab === k ? 'active' : ''}`} onClick={() => setTab(k)}>{l}</div>)}
      </div>

      {tab === 'details' && <>
        <div className="row-2">
          <Field label="Project name *"><input className="input" value={f.name} onChange={(e) => set('name', e.target.value)} placeholder="Acme Q3 Outreach" /></Field>
          <Field label="Project email *"><input className="input" type="email" value={f.email} onChange={(e) => set('email', e.target.value)} placeholder="noreply@acme.com" /></Field>
        </div>
        <Field label="Description"><textarea className="textarea" value={f.description} onChange={(e) => set('description', e.target.value)} placeholder="What is this project for?" /></Field>
        <div className="row-2">
          <Field label="Status">
            <select className="select" value={f.status} onChange={(e) => set('status', e.target.value)}>
              <option value="active">Active</option><option value="inactive">Inactive</option><option value="archived">Archived</option>
            </select>
          </Field>
          <LogoField f={f} set={set} projectId={initial.id} toast={toast} />
        </div>
        <Field label="Additional notes"><textarea className="textarea" value={f.notes} onChange={(e) => set('notes', e.target.value)} /></Field>
      </>}

      {tab === 'email' && <SmtpTab f={f} set={set} projectId={initial.id} toast={toast} />}

      {tab === 'branding' && <BrandingTab f={f} set={set} />}

      {tab === 'sms' && <ChannelTab f={f} set={set} channel="sms" label="SMS" activeKey="sms_active" providerKey="sms_provider" />}
      {tab === 'whatsapp' && <ChannelTab f={f} set={set} channel="whatsapp" label="WhatsApp" activeKey="whatsapp_active" providerKey="whatsapp_provider" />}

      {tab === 'members' && (
        <>
          <p className="muted" style={{ fontSize: 13, marginTop: -4, marginBottom: 14 }}>Assign Users who can work within this project.</p>
          {users.length === 0 ? <p className="muted">No users available.</p> : (
            <div className="grid" style={{ gap: 8 }}>
              {users.map((u) => {
                const on = f.member_ids.includes(u.id)
                return (
                  <label key={u.id} className={`perm-item ${on ? 'checked' : ''}`} style={{ justifyContent: 'space-between' }}>
                    <span>{u.name} <span className="t-sub">· {u.email}</span></span>
                    <input type="checkbox" checked={on} onChange={(e) =>
                      set('member_ids', e.target.checked ? [...f.member_ids, u.id] : f.member_ids.filter((x) => x !== u.id))} />
                  </label>
                )
              })}
            </div>
          )}
          <p className="hint mt8">Note: on save, this replaces the project's member list.</p>
        </>
      )}
    </Modal>
  )
}

function LogoField({ f, set, projectId, toast }) {
  const [busy, setBusy] = useState(false)
  const inputRef = useRef(null)

  const upload = async (file) => {
    if (!file) return
    setBusy(true)
    try {
      const body = new FormData()
      body.append('file', file)
      const { data } = await api.post(`/projects/${projectId}/logo`, body)
      set('logo_url', data.logo_url)
      toast.ok('Logo uploaded')
    } catch (e) {
      toast.err(apiError(e, 'Could not upload logo'))
    } finally {
      setBusy(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <Field label="Logo" hint={projectId
      ? 'PNG, JPEG, GIF or WEBP, up to 5MB. Hosted publicly so it renders in the recipient’s inbox, not just in this preview.'
      : 'Save the project first, then upload a logo.'}>
      <div className="flex gap12" style={{ alignItems: 'center' }}>
        {f.logo_url && (
          <img src={f.logo_url} alt="Logo" style={{ height: 36, maxWidth: 120, objectFit: 'contain', borderRadius: 6, background: '#fff', border: '1px solid var(--border)' }} />
        )}
        <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/gif,image/webp"
          disabled={!projectId || busy}
          onChange={(e) => upload(e.target.files[0])} />
        {busy && <span className="t-sub">Uploading…</span>}
      </div>
    </Field>
  )
}

function BrandingTab({ f, set }) {
  return (
    <>
      <p className="muted" style={{ fontSize: 13, marginTop: -4, marginBottom: 16 }}>
        Used by Email templates in the Templates library — set once here, reused across every
        Email template rendered for this project. Company name and logo come from the Details tab.
      </p>
      <div className="row-2">
        <Field label="Company website"><input className="input" value={f.company_website} onChange={(e) => set('company_website', e.target.value)} placeholder="https://acme.com" /></Field>
        <Field label="Company address"><input className="input" value={f.company_address} onChange={(e) => set('company_address', e.target.value)} placeholder="123 Market St, Springfield" /></Field>
      </div>
      <div className="row-2">
        <Field label="Sender name"><input className="input" value={f.sender_name} onChange={(e) => set('sender_name', e.target.value)} placeholder="Jane Doe" /></Field>
        <Field label="Sender designation"><input className="input" value={f.sender_designation} onChange={(e) => set('sender_designation', e.target.value)} placeholder="Growth Lead" /></Field>
      </div>
      <Field label="Sender phone"><input className="input" value={f.sender_phone} onChange={(e) => set('sender_phone', e.target.value)} placeholder="+1 555 0100" /></Field>
      <p className="t-sub" style={{ marginTop: 16, marginBottom: 6 }}>Trust badges (optional, shown when a template enables the badges block)</p>
      <div className="row-3">
        <Field label="Badge 1 URL"><input className="input" value={f.badge1_url} onChange={(e) => set('badge1_url', e.target.value)} placeholder="https://…" /></Field>
        <Field label="Badge 2 URL"><input className="input" value={f.badge2_url} onChange={(e) => set('badge2_url', e.target.value)} placeholder="https://…" /></Field>
        <Field label="Badge 3 URL"><input className="input" value={f.badge3_url} onChange={(e) => set('badge3_url', e.target.value)} placeholder="https://…" /></Field>
      </div>
    </>
  )
}

function ChannelTab({ f, set, channel, label, activeKey, providerKey }) {
  const Ico = channel === 'sms' ? Icon.phone : Icon.chat
  return (
    <>
      <div className="flex between" style={{ padding: '4px 0 16px' }}>
        <div className="flex gap12">
          <span className="ico" style={{ width: 40, height: 40, borderRadius: 10, background: 'var(--teal-soft)', color: 'var(--teal)', display: 'grid', placeItems: 'center' }}><Ico width={20} /></span>
          <div>
            <div style={{ fontWeight: 700 }}>{label} channel</div>
            <div className="t-sub">Enable {label} delivery for campaigns in this project.</div>
          </div>
        </div>
        <Toggle checked={f[activeKey]} onChange={(v) => set(activeKey, v)} label={f[activeKey] ? 'Active' : 'Inactive'} />
      </div>
      <Field label={`${label} provider`} hint="e.g. Twilio, MSG91, Meta Cloud API">
        <input className="input" value={f[providerKey]} onChange={(e) => set(providerKey, e.target.value)}
          placeholder="Provider name" disabled={!f[activeKey]} />
      </Field>
    </>
  )
}

const ENCRYPTION_DEFAULT_PORTS = { none: 25, starttls: 587, ssl: 465 }

function SmtpTab({ f, set, projectId, toast }) {
  const [testing, setTesting] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const provider = f.smtp_provider || 'custom'
  const isKnownProvider = provider !== 'custom'
  const passwordHint = smtpProviderPasswordHint(provider)

  const setProvider = (next) => {
    set('smtp_provider', next)
    const defaults = SMTP_PROVIDER_DEFAULTS[next]
    if (defaults && Object.keys(defaults).length) {
      set('smtp_host', defaults.smtp_host)
      set('smtp_port', defaults.smtp_port)
      set('smtp_encryption', defaults.encryption)
    }
    setAdvancedOpen(false)
  }

  const setEncryption = (enc) => {
    set('smtp_encryption', enc)
    // Only auto-adjust the port if it still matches one of the standard
    // defaults -- don't clobber a deliberately custom port.
    if (Object.values(ENCRYPTION_DEFAULT_PORTS).includes(f.smtp_port)) {
      set('smtp_port', ENCRYPTION_DEFAULT_PORTS[enc])
    }
  }

  const testConnection = async () => {
    setTesting(true)
    try {
      const { data } = await api.post(`/projects/${projectId}/smtp-test`, {
        smtp_host: f.smtp_host, smtp_port: f.smtp_port, smtp_encryption: f.smtp_encryption,
        smtp_username: f.smtp_username, smtp_password: f.smtp_password,
      })
      set('smtp_last_test_status', 'ok')
      set('smtp_last_tested_at', new Date().toISOString())
      toast.ok(data.message || 'SMTP connection successful!')
    } catch (e) {
      set('smtp_last_test_status', 'failed')
      set('smtp_last_tested_at', new Date().toISOString())
      toast.err(apiError(e, 'SMTP test failed'))
    } finally { setTesting(false) }
  }

  return (
    <>
      <div className="flex between" style={{ padding: '4px 0 16px' }}>
        <div>
          <div style={{ fontWeight: 700 }}>Use project SMTP</div>
          <div className="t-sub">When off, campaigns in this project send via the workspace Office 365 sender.</div>
        </div>
        <Toggle checked={f.smtp_enabled} onChange={(v) => set('smtp_enabled', v)} label={f.smtp_enabled ? 'Enabled' : 'Disabled'} />
      </div>

      <Field label="Provider" hint="Drives host/port/encryption auto-fill — still editable under Advanced.">
        <select className="select" value={provider} onChange={(e) => setProvider(e.target.value)} disabled={!f.smtp_enabled}>
          {SMTP_PROVIDER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </Field>

      {isKnownProvider && !advancedOpen ? (
        <div className="flex between" style={{ alignItems: 'center', padding: '8px 12px', marginBottom: 14, border: '1px solid var(--border-strong)', borderRadius: 9 }}>
          <span className="t-sub" style={{ fontFamily: 'var(--mono)', fontSize: 12.5 }}>
            {f.smtp_host}:{f.smtp_port} · {f.smtp_encryption.toUpperCase()}
          </span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAdvancedOpen(true)} disabled={!f.smtp_enabled}>
            Advanced
          </button>
        </div>
      ) : (
        <>
          <div className="row-2">
            <Field label="SMTP host">
              <input className="input" value={f.smtp_host} onChange={(e) => set('smtp_host', e.target.value)}
                placeholder="smtp.gmail.com" disabled={!f.smtp_enabled} />
            </Field>
            <Field label="SMTP port">
              <input className="input" type="number" value={f.smtp_port} onChange={(e) => set('smtp_port', Number(e.target.value))}
                placeholder="587" disabled={!f.smtp_enabled} />
            </Field>
          </div>
          <Field label="Encryption">
            <select className="select" value={f.smtp_encryption} onChange={(e) => setEncryption(e.target.value)} disabled={!f.smtp_enabled}>
              <option value="none">None</option>
              <option value="starttls">STARTTLS</option>
              <option value="ssl">SSL/TLS</option>
            </select>
          </Field>
          {isKnownProvider && (
            <button type="button" className="btn btn-ghost btn-sm" style={{ marginBottom: 14 }}
              onClick={() => setAdvancedOpen(false)}>
              Collapse
            </button>
          )}
        </>
      )}

      <Field label="Max sends / minute" hint="0 = unlimited. Many providers throttle or lock accounts under bulk sending.">
        <input className="input" type="number" min={0} value={f.smtp_max_per_minute}
          onChange={(e) => set('smtp_max_per_minute', Number(e.target.value))} disabled={!f.smtp_enabled} />
      </Field>
      <div className="row-2">
        <Field label="Username">
          <input className="input" value={f.smtp_username} onChange={(e) => set('smtp_username', e.target.value)}
            placeholder="your@email.com" disabled={!f.smtp_enabled} />
        </Field>
        <Field label="Password" hint={passwordHint}>
          <input className="input" type="password" value={f.smtp_password} onChange={(e) => set('smtp_password', e.target.value)}
            placeholder={projectId ? '••••••••• (leave blank to keep)' : ''} disabled={!f.smtp_enabled} />
        </Field>
      </div>
      <div className="row-2">
        <Field label="From name">
          <input className="input" value={f.smtp_from_name} onChange={(e) => set('smtp_from_name', e.target.value)}
            placeholder="Acme" disabled={!f.smtp_enabled} />
        </Field>
        <Field label="From email" hint="Must have SPF/DKIM authorizing this SMTP host, or mail will land in spam.">
          <input className="input" type="email" value={f.smtp_from_email} onChange={(e) => set('smtp_from_email', e.target.value)}
            placeholder="noreply@acme.com" disabled={!f.smtp_enabled} />
        </Field>
      </div>
      <Field label="Reply-to" hint="Optional — defaults to the from address if left blank.">
        <input className="input" type="email" value={f.smtp_reply_to} onChange={(e) => set('smtp_reply_to', e.target.value)}
          placeholder="support@acme.com" disabled={!f.smtp_enabled} />
      </Field>

      <div className="flex between" style={{ padding: '4px 0 16px' }}>
        <div>
          <div style={{ fontWeight: 700 }}>Fall back to Office 365 on failure</div>
          <div className="t-sub">If a send through this SMTP server fails mid-campaign, retry it via the workspace O365 sender instead of failing the recipient.</div>
        </div>
        <Toggle checked={f.smtp_fallback_on_failure} onChange={(v) => set('smtp_fallback_on_failure', v)}
          label={f.smtp_fallback_on_failure ? 'On' : 'Off'} />
      </div>

      {projectId && (
        <div className="flex gap12" style={{ alignItems: 'center' }}>
          <button className="btn btn-ghost" onClick={testConnection} disabled={testing || !f.smtp_host}>
            <Icon.check width={14} /> {testing ? 'Testing…' : 'Test connection'}
          </button>
          {f.smtp_last_test_status !== 'never' && (
            <span className="t-sub">
              Last test: {f.smtp_last_test_status === 'ok' ? 'succeeded' : 'failed'}
              {f.smtp_last_tested_at ? ` · ${new Date(f.smtp_last_tested_at).toLocaleString()}` : ''}
            </span>
          )}
        </div>
      )}
    </>
  )
}

