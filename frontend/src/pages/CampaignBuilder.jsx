import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import Layout from '../components/Layout'
import { useAuth } from '../auth'
import api, { apiError } from '../api'
import { Icon, Field, Modal, StatusBadge, Toggle, Spinner, useToast } from '../components/ui'
import { ValidationPanel } from '../components/DatasetValidation'

const CHANNELS = [
  { key: 'email', label: 'Email', icon: 'mail', enField: 'email_enabled', hasSubject: true },
  { key: 'whatsapp', label: 'WhatsApp', icon: 'chat', enField: 'whatsapp_enabled', hasSubject: false },
  { key: 'sms', label: 'SMS', icon: 'phone', enField: 'sms_enabled', hasSubject: false },
]

function isContentAuthored(val) {
  return !!(val && val.body)
}

export default function CampaignBuilder() {
  const { id } = useParams()
  const { can } = useAuth()
  const toast = useToast()
  const nav = useNavigate()

  const [campaign, setCampaign] = useState(null)
  const [project, setProject] = useState(null)
  const [recipients, setRecipients] = useState([])
  const [contents, setContents] = useState({})
  const [step, setStep] = useState('recipients')

  const load = async () => {
    const { data: c } = await api.get(`/campaigns/${id}`)
    setCampaign(c)
    const [{ data: recs }, { data: cont }, { data: proj }] = await Promise.all([
      // /recipients now returns one page at a time (see app/pagination.py);
      // this page already only ever displays/lists the first 100 (see
      // RecipientsStep below), so fetching that many up front avoids a
      // regression from the new default of 25. campaign.recipient_count
      // (below) is the server-computed true total, used for the count
      // label instead of this array's length.
      api.get(`/campaigns/${id}/recipients`, { params: { page_size: 100 } }),
      api.get(`/campaigns/${id}/content`),
      api.get(`/projects/${c.project_id}`),
    ])
    setRecipients(recs)
    setProject(proj)
    const map = {}
    cont.forEach((x) => { map[x.channel] = { subject: x.subject, body: x.body } })
    setContents(map)
  }
  useEffect(() => { load() }, [id])

  if (!campaign || !project) return <Layout title="Campaign"><Spinner /></Layout>

  const steps = [
    ['recipients', 'Recipients', 'upload'], ['content', 'Content', 'edit'],
    ['followups', 'Follow-ups', 'repeat'], ['send', 'Review & Send', 'send'],
  ]

  return (
    <Layout title={campaign.name} crumb={<span style={{ cursor: 'pointer' }} onClick={() => nav('/campaigns')}>← Campaigns</span>}>
      <div className="page-head">
        <div>
          <div className="flex gap12">
            <div className="pt">{campaign.name}</div>
            <StatusBadge status={campaign.status} />
            {campaign.is_test_campaign && <span className="badge amber"><span className="d" />TEST</span>}
          </div>
          <div className="ps">{project.name} · {campaign.recipient_count} recipient{campaign.recipient_count !== 1 ? 's' : ''}</div>
        </div>
      </div>

      <div className="tabs">
        {steps.map(([k, l, ico]) => {
          const Ico = Icon[ico]
          return <div key={k} className={`tab ${step === k ? 'active' : ''}`} onClick={() => setStep(k)}>
            <span className="flex gap8"><Ico width={15} /> {l}</span>
          </div>
        })}
      </div>

      {step === 'recipients' && (
        <RecipientsStep campaignId={id} recipients={recipients} setRecipients={setRecipients} columns={campaign.columns}
          recipientCount={campaign.recipient_count}
          canEdit={can('dataset.upload')} canOverrideWarnings={can('dataset.override_warnings')}
          onUploaded={(c) => { load(); toast.ok(`${c.recipient_count} recipients imported`) }}
          onChange={load} toast={toast} onError={(m) => toast.err(m)} />
      )}
      {step === 'content' && (
        <ContentStep campaign={campaign} campaignId={id} columns={campaign.columns} contents={contents} setContents={setContents}
          recipients={recipients} canEdit={can('content.edit')} toast={toast} onCampaignChange={load} />
      )}
      {step === 'followups' && (
        <FollowUpsStep campaign={campaign} project={project} campaignId={id} columns={campaign.columns} canEdit={can('content.edit')} toast={toast} />
      )}
      {step === 'send' && (
        <SendStep campaign={campaign} project={project} contents={contents}
          canSend={can('campaign.send')} onChange={load} toast={toast} nav={nav} />
      )}
    </Layout>
  )
}

/* ---------------- Recipients ---------------- */
const BLANK_REC = { name: '', email: '', mobile: '' }
const SAMPLE_CSV = 'FirstName,LastName,Email,Phone,Company,JobTitle,City,State,Country\n'
  + 'Jane,Doe,jane.doe@example.com,+14155551234,Acme Inc,Marketing Manager,San Francisco,CA,United States\n'
  + 'John,Smith,john.smith@example.com,+442071234567,Beta Ltd,Sales Director,London,,United Kingdom\n'

function downloadBlob(content, type, filename) {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename
  document.body.appendChild(a); a.click(); a.remove()
  URL.revokeObjectURL(url)
}

function RecipientsStep({ campaignId, recipients, setRecipients, columns, recipientCount, canEdit, canOverrideWarnings, onUploaded, onChange, toast, onError }) {
  const fileRef = useRef()
  const [busy, setBusy] = useState(false)
  const [showAdd, setShowAdd] = useState(false)
  const [rec, setRec] = useState(BLANK_REC)
  const [adding, setAdding] = useState(false)
  const [validationSession, setValidationSession] = useState(null)
  const setF = (k, v) => setRec((s) => ({ ...s, [k]: v }))
  const extraCols = columns.filter((c) => !['name', 'email address', 'mobile number', 'email', 'mobile', 'phone'].includes(c.toLowerCase())).slice(0, 3)

  const upload = async (file) => {
    if (!file) return
    setBusy(true)
    const fd = new FormData()
    fd.append('file', file)
    try {
      const { data } = await api.post(`/campaigns/${campaignId}/dataset/validate`, fd, { headers: { 'Content-Type': 'multipart/form-data' } })
      setValidationSession(data)
    } catch (e) { onError(apiError(e)) } finally { setBusy(false); if (fileRef.current) fileRef.current.value = '' }
  }

  const removeDataset = async () => {
    if (!window.confirm('Remove the current recipient dataset? This cannot be undone.')) return
    setBusy(true)
    try {
      await api.delete(`/campaigns/${campaignId}/dataset`)
      onChange()
      toast.ok('Recipient dataset removed')
    } catch (e) { onError(apiError(e)) } finally { setBusy(false) }
  }

  const addOne = async () => {
    setAdding(true)
    try {
      await api.post(`/campaigns/${campaignId}/recipients`, rec)
      setRec(BLANK_REC); setShowAdd(false)
      onChange(); toast.ok('Recipient added')
    } catch (e) { onError(apiError(e)) } finally { setAdding(false) }
  }

  const setActive = async (id, active) => {
    const prev = recipients
    setRecipients((rs) => rs.map((r) => (r.id === id ? { ...r, active } : r)))
    try { await api.patch(`/campaigns/${campaignId}/recipients/${id}`, { active }) }
    catch (e) { setRecipients(prev); onError(apiError(e)) }
  }

  return (
    <>
      {validationSession && (
        <ValidationPanel campaignId={campaignId} session={validationSession} setSession={setValidationSession}
          canEdit={canEdit} canOverrideWarnings={canOverrideWarnings} toast={toast}
          onImported={(c) => { setValidationSession(null); onUploaded(c) }}
          onCancel={() => setValidationSession(null)} />
      )}

      {!validationSession && canEdit && (
        <div className="card card-pad" style={{ marginBottom: 20 }}>
          <div className="flex between wrap-gap">
            <div className="flex gap12">
              <span className="ico" style={{ width: 44, height: 44, borderRadius: 11, background: 'var(--teal-soft)', color: 'var(--teal)', display: 'grid', placeItems: 'center' }}><Icon.upload width={20} /></span>
              <div>
                <div style={{ fontWeight: 700 }}>Upload recipient dataset</div>
                <div className="t-sub">CSV, XLS or XLSX — only <b>Email</b> is required. AI-powered validation runs after upload: you'll review a quality score and issue report, confirm column mapping, and fix or exclude bad rows before anything is imported. Choosing a new file replaces the existing recipients.</div>
              </div>
            </div>
            <div className="flex gap8">
              <button className="btn btn-ghost" onClick={() => downloadBlob(SAMPLE_CSV, 'text/csv', 'sample-contacts.csv')}>
                <Icon.download width={15} /> Download Sample CSV
              </button>
              <button className="btn btn-ghost" onClick={() => setShowAdd((s) => !s)}><Icon.userplus width={15} /> Add recipient</button>
              {recipients.length > 0 && (
                <button className="btn btn-ghost" disabled={busy} onClick={removeDataset}><Icon.trash width={15} /> Remove dataset</button>
              )}
              <input ref={fileRef} type="file" accept=".csv,.xls,.xlsx" style={{ display: 'none' }} onChange={(e) => upload(e.target.files[0])} />
              <button className="btn btn-primary" disabled={busy} onClick={() => fileRef.current.click()}>
                {busy ? 'Validating…' : <><Icon.upload width={15} /> Choose file</>}
              </button>
            </div>
          </div>

          {showAdd && (
            <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
              <div className="row-3">
                <Field label="Name *"><input className="input" value={rec.name} onChange={(e) => setF('name', e.target.value)} placeholder="Jane Doe" autoFocus /></Field>
                <Field label="Email address"><input className="input" type="email" value={rec.email} onChange={(e) => setF('email', e.target.value)} placeholder="jane@example.com" /></Field>
                <Field label="Mobile number"><input className="input" value={rec.mobile} onChange={(e) => setF('mobile', e.target.value)} placeholder="9876543210" /></Field>
              </div>
              <div className="flex gap8" style={{ justifyContent: 'flex-end' }}>
                <button className="btn btn-ghost btn-sm" onClick={() => { setShowAdd(false); setRec(BLANK_REC) }}>Cancel</button>
                <button className="btn btn-primary btn-sm" onClick={addOne} disabled={adding || !rec.name || (!rec.email && !rec.mobile)}>
                  {adding ? 'Adding…' : <><Icon.plus width={14} /> Add recipient</>}
                </button>
              </div>
              <p className="hint">Provide at least an email address or a mobile number.</p>
            </div>
          )}
        </div>
      )}

      {!validationSession && (recipients.length === 0 ? (
        <div className="card empty">
          <div className="ico"><Icon.users width={24} /></div>
          <h3 style={{ marginBottom: 6 }}>No recipients yet</h3>
          <p className="muted">Upload a dataset or add a recipient to build your list.</p>
        </div>
      ) : (
        <>
          <div className="flex between" style={{ marginBottom: 10 }}>
            <div className="wrap-gap">
              {columns.map((c) => <span key={c} className="ph-chip" style={{ cursor: 'default' }}>{`{{${c}}}`}</span>)}
            </div>
            <span className="t-sub">{recipientCount} recipient{recipientCount !== 1 ? 's' : ''}</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Name</th><th>Email</th><th>Mobile</th>{extraCols.map((c) => <th key={c}>{c}</th>)}{canEdit && <th>Active</th>}</tr></thead>
              <tbody>
                {recipients.slice(0, 100).map((r) => (
                  <tr key={r.id} style={r.active === false ? { opacity: 0.5 } : undefined}>
                    <td className="t-strong">{r.name || '—'}</td><td>{r.email || '—'}</td><td>{r.mobile || '—'}</td>
                    {extraCols.map((c) => <td key={c} className="muted">{r.data[c] || '—'}</td>)}
                    {canEdit && (
                      <td style={{ textAlign: 'right' }}>
                        <Toggle checked={r.active !== false} title={r.active !== false ? 'Deactivate recipient' : 'Activate recipient'}
                          onChange={(v) => setActive(r.id, v)} />
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {recipientCount > 100 && <p className="t-sub mt8">Showing first 100 of {recipientCount}.</p>}
        </>
      ))}
    </>
  )
}

/* ---------------- Content ---------------- */
function ContentStep({ campaign, campaignId, columns, contents, setContents, recipients, canEdit, toast, onCampaignChange }) {
  const [active, setActive] = useState('email')
  const [preview, setPreview] = useState({ subject: '', body: '', missing: [] })
  const [recipientId, setRecipientId] = useState(recipients[0]?.id || null)
  const [saving, setSaving] = useState(false)
  const [aiMode, setAiMode] = useState(false)
  const [aiPrompt, setAiPrompt] = useState('')
  const [generating, setGenerating] = useState(false)
  const [templates, setTemplates] = useState([])
  const [tplRef, setTplRef] = useState(campaign.sms_template_ref || '')
  const [dlt, setDlt] = useState(null) // {valid, reason}
  const bodyRef = useRef(); const subjRef = useRef(); const focused = useRef('body')

  const ch = CHANNELS.find((c) => c.key === active)
  const val = contents[active] || { subject: '', body: '' }
  const setVal = (patch) => setContents((s) => ({ ...s, [active]: { ...val, ...patch } }))

  useEffect(() => { api.get('/sms/templates').then((r) => setTemplates(r.data)).catch(() => {}) }, [])
  const selectedTpl = templates.find((t) => t.id === Number(tplRef))

  const insert = (token) => {
    const ref = focused.current === 'subject' && ch.hasSubject ? subjRef : bodyRef
    const el = ref.current
    if (!el) { setVal({ body: (val.body || '') + token }); return }
    const start = el.selectionStart ?? el.value.length
    const end = el.selectionEnd ?? el.value.length
    const key = focused.current === 'subject' ? 'subject' : 'body'
    const cur = val[key] || ''
    const next = cur.slice(0, start) + token + cur.slice(end)
    setVal({ [key]: next })
    setTimeout(() => { el.focus(); el.selectionStart = el.selectionEnd = start + token.length }, 0)
  }

  const save = async () => {
    setSaving(true)
    try {
      const payload = { subject: val.subject || '', body: val.body || '' }
      await api.put(`/campaigns/${campaignId}/content/${active}`, payload)
      toast.ok(`${ch.label} content saved`)
    } catch (e) { toast.err(apiError(e)) } finally { setSaving(false) }
  }

  useEffect(() => { setAiMode(false); setAiPrompt('') }, [active])

  const generateContent = async () => {
    if (!aiPrompt.trim()) return
    setGenerating(true)
    try {
      const { data } = await api.post(`/campaigns/${campaignId}/content/${active}/generate`, { prompt: aiPrompt })
      setVal({ subject: ch.hasSubject ? data.subject : val.subject, body: data.body })
      toast.ok('Draft generated — review and edit before saving')
    } catch (e) { toast.err(apiError(e)) } finally { setGenerating(false) }
  }

  const changeTemplate = async (ref) => {
    setTplRef(ref)
    try {
      await api.put(`/campaigns/${campaignId}`, { sms_template_ref: ref ? Number(ref) : null })
      onCampaignChange && onCampaignChange()
    } catch (e) { toast.err(apiError(e)) }
  }

  const runPreview = async () => {
    try {
      const { data } = await api.post(`/campaigns/${campaignId}/preview`, {
        channel: active, subject: val.subject || '', body: val.body || '', recipient_id: recipientId,
      })
      setPreview(data)
    } catch (e) { toast.err(apiError(e)) }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { runPreview() }, [active, recipientId, val.subject, val.body])

  // live DLT validation for SMS
  useEffect(() => {
    if (active !== 'sms' || !tplRef) { setDlt(null); return }
    let cancelled = false
    api.post('/sms/validate', { template_ref: Number(tplRef), message: val.body || '' })
      .then((r) => { if (!cancelled) setDlt(r.data) }).catch(() => {})
    return () => { cancelled = true }
  }, [active, tplRef, val.body])

  return (
    <div className="grid grid-2" style={{ alignItems: 'start' }}>
      <div className="card card-pad">
        <div className="tabs" style={{ marginBottom: 16 }}>
          {CHANNELS.map((c) => {
            const Ico = Icon[c.icon]
            return <div key={c.key} className={`tab ${active === c.key ? 'active' : ''}`} onClick={() => setActive(c.key)}>
              <span className="flex gap8"><Ico width={14} /> {c.label}</span>
            </div>
          })}
        </div>

        {active === 'sms' && (
          <div className="field">
            <label>DLT template <span className="hint" style={{ fontWeight: 400 }}>(India — required for delivery)</span></label>
            <select className="select" value={tplRef} onChange={(e) => changeTemplate(e.target.value)} disabled={!canEdit}>
              <option value="">— No template (won't pass DLT) —</option>
              {templates.map((t) => <option key={t.id} value={t.id}>{t.name} · {t.template_id}</option>)}
            </select>
            {selectedTpl && (
              <div className="preview" style={{ marginTop: 8 }}>
                <div className="ph"><span>Registered template text</span><span>{selectedTpl.sender_id}</span></div>
                <div className="pb" style={{ minHeight: 'auto', fontSize: 12.5 }}>{selectedTpl.body}</div>
              </div>
            )}
          </div>
        )}

        <div className="field">
          <label>Content mode</label>
          <div className="tabs" style={{ marginBottom: 0 }}>
            <div className={`tab ${!aiMode ? 'active' : ''}`} onClick={() => canEdit && setAiMode(false)}>Plain text</div>
            <div className={`tab ${aiMode ? 'active' : ''}`} onClick={() => canEdit && setAiMode(true)}>
              <span className="flex gap8"><Icon.sparkle width={14} /> Generative AI</span>
            </div>
          </div>
        </div>

        {aiMode && (
          <div className="field" style={{ background: 'var(--teal-soft2)', border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
            <label>Describe what you want</label>
            <textarea className="textarea" style={{ minHeight: 70 }} value={aiPrompt} disabled={!canEdit || generating}
              onChange={(e) => setAiPrompt(e.target.value)}
              placeholder='e.g. "Announce our new product launch, friendly and exciting tone, mention a 20% early-bird discount"' />
            <div className="flex" style={{ justifyContent: 'flex-end', marginTop: 8 }}>
              <button className="btn btn-primary btn-sm" disabled={!canEdit || generating || !aiPrompt.trim()} onClick={generateContent}>
                {generating ? 'Generating…' : <><Icon.sparkle width={14} /> Generate</>}
              </button>
            </div>
          </div>
        )}

        {ch.hasSubject && (
          <div className="field">
            <label>Subject</label>
            <input ref={subjRef} className="input" value={val.subject || ''} disabled={!canEdit}
              onFocus={() => (focused.current = 'subject')}
              onChange={(e) => setVal({ subject: e.target.value })} placeholder="Hi {{Name}}, an update from {{Company}}" />
          </div>
        )}

        <div className="field">
          <label>Message body</label>
          <textarea ref={bodyRef} className="textarea" style={{ minHeight: 180 }}
            value={val.body || ''} disabled={!canEdit}
            onFocus={() => (focused.current = 'body')}
            onChange={(e) => setVal({ body: e.target.value })}
            placeholder={`Hello {{Name}},\n\nWrite your ${ch.label} message here…`} />
        </div>

        {active === 'email' && <AttachmentsPanel campaignId={campaignId} canEdit={canEdit} toast={toast} />}

        {active === 'sms' && tplRef && dlt && (
          <div className={`badge ${dlt.valid ? 'green' : 'red'}`} style={{ marginBottom: 10 }}>
            <span className="d" />{dlt.valid ? 'Matches DLT template' : 'Does not match DLT template'}
          </div>
        )}
        {active === 'sms' && tplRef && dlt && !dlt.valid && (
          <p className="hint" style={{ marginTop: -4, marginBottom: 10 }}>{dlt.reason}. Tip: copy the registered wording above and change only the variable.</p>
        )}

        {columns.length > 0 && (
          <div>
            <div className="t-sub">Insert placeholder:</div>
            <div className="ph-chips">
              {columns.map((c) => <span key={c} className="ph-chip" onClick={() => insert(`{{${c}}}`)}>{`{{${c}}}`}</span>)}
            </div>
          </div>
        )}

        {canEdit && (
          <button className="btn btn-primary mt16" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : <><Icon.check width={15} /> Save {ch.label} content</>}
          </button>
        )}
      </div>

      <div className="card" style={{ maxHeight: 620, overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
        <div className="card-pad flex between" style={{ paddingBottom: 12, flexShrink: 0 }}>
          <h3 style={{ fontSize: 15 }}>Live preview</h3>
          {recipients.length > 0 && (
            <select className="select" style={{ width: 200 }} value={recipientId || ''} onChange={(e) => setRecipientId(Number(e.target.value))}>
              {recipients.map((r) => <option key={r.id} value={r.id}>{r.name || r.email}</option>)}
            </select>
          )}
        </div>
        <div style={{ padding: '0 22px 22px', flex: 1, minHeight: 0 }}>
          {preview.missing && preview.missing.length > 0 && (
            <div className="hint" style={{ marginBottom: 10, color: 'var(--warn)' }}>
              ⚠ No value found for: {preview.missing.map((m) => `{{${m}}}`).join(', ')} — sent as blank.
            </div>
          )}
          <div className="preview">
            <div className="ph"><span>{ch.label} preview</span><span>{recipients.length ? '' : 'Upload recipients to personalize'}</span></div>
            <div className="pb">
              {ch.hasSubject && preview.subject && <div className="subj">{preview.subject}</div>}
              {preview.body || <span className="muted">Nothing to preview yet.</span>}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

const fmtSize = (n) => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / (1024 * 1024)).toFixed(1)} MB`)

function AttachmentsPanel({ campaignId, canEdit, toast }) {
  const [attachments, setAttachments] = useState([])
  const [busy, setBusy] = useState(false)
  const fileRef = useRef()

  const load = () => api.get(`/campaigns/${campaignId}/attachments`).then((r) => setAttachments(r.data)).catch(() => {})
  useEffect(() => { load() }, [campaignId])

  const upload = async (files) => {
    if (!files || !files.length) return
    setBusy(true)
    try {
      for (const file of files) {
        const fd = new FormData()
        fd.append('file', file)
        await api.post(`/campaigns/${campaignId}/attachments`, fd, { headers: { 'Content-Type': 'multipart/form-data' } })
      }
      await load()
      toast.ok('Attachment(s) uploaded')
    } catch (e) { toast.err(apiError(e)) } finally { setBusy(false); if (fileRef.current) fileRef.current.value = '' }
  }

  const remove = async (id) => {
    const prev = attachments
    setAttachments((a) => a.filter((x) => x.id !== id))
    try { await api.delete(`/campaigns/${campaignId}/attachments/${id}`) }
    catch (e) { setAttachments(prev); toast.err(apiError(e)) }
  }

  const totalBytes = attachments.reduce((s, a) => s + a.size_bytes, 0)

  return (
    <div className="field">
      <label>Attachments <span className="hint" style={{ fontWeight: 400 }}>(same files sent to every recipient · 10MB total)</span></label>
      {attachments.length > 0 && (
        <div className="wrap-gap" style={{ marginBottom: 10 }}>
          {attachments.map((a) => (
            <span key={a.id} className="ph-chip" style={{ cursor: 'default', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <Icon.paperclip width={12} /> {a.filename} <span className="muted">({fmtSize(a.size_bytes)})</span>
              {canEdit && (
                <span onClick={() => remove(a.id)} title="Remove attachment" style={{ cursor: 'pointer', marginLeft: 2, fontWeight: 700 }}>&times;</span>
              )}
            </span>
          ))}
        </div>
      )}
      {canEdit && (
        <div className="flex gap8" style={{ alignItems: 'center' }}>
          <input ref={fileRef} type="file" multiple style={{ display: 'none' }} onChange={(e) => upload(e.target.files)} />
          <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => fileRef.current.click()}>
            {busy ? 'Uploading…' : <><Icon.paperclip width={14} /> Add attachment</>}
          </button>
          {attachments.length > 0 && <span className="t-sub">{fmtSize(totalBytes)} used</span>}
        </div>
      )}
    </div>
  )
}

/* ---------------- Follow-ups ---------------- */
const FOLLOWUP_CHANNELS = { email: 'Email', whatsapp: 'WhatsApp', sms: 'SMS' }
const TRIGGER_LABELS = { no_reply: 'No reply', not_opened: 'Not opened', not_clicked: 'Not clicked' }
const TRIGGER_BADGE = { no_reply: 'amber', not_opened: 'blue', not_clicked: 'teal' }

function replyPollIntervalLabel(secs) {
  if (!secs) return null
  if (secs < 60) return `${secs}s`
  const mins = Math.round(secs / 60)
  return `${mins} minute${mins !== 1 ? 's' : ''}`
}

function FollowUpsStep({ campaign, project, campaignId, columns, canEdit, toast }) {
  const [settings, setSettings] = useState(null)
  const [steps, setSteps] = useState(null)
  const [editing, setEditing] = useState(null) // step object (existing) or {} (new) or null (closed)
  const [replyCapture, setReplyCapture] = useState(null)

  useEffect(() => {
    // Admin-only endpoint (system.configure) -- a campaign editor without
    // that permission just won't see the hint below, no error surfaced.
    api.get('/admin/reply-capture').then((r) => setReplyCapture(r.data)).catch(() => {})
  }, [])

  const load = async () => {
    const [{ data: s }, { data: st }] = await Promise.all([
      api.get(`/campaigns/${campaignId}/followups/settings`),
      api.get(`/campaigns/${campaignId}/followups/steps`),
    ])
    setSettings(s); setSteps(st)
  }
  useEffect(() => { load() }, [campaignId])

  // Performance is a rollup of the same rows Tracking & Reports polls while a
  // campaign is actively sending -- match that cadence here too, or the two
  // tabs can show conflicting numbers side by side during an active send.
  useEffect(() => {
    if (campaign.status !== 'sending') return
    const interval = setInterval(load, 4000)
    return () => clearInterval(interval)
  }, [campaignId, campaign.status])

  const patchSettings = async (patch) => {
    const next = { ...settings, ...patch }
    setSettings(next)
    try {
      await api.put(`/campaigns/${campaignId}/followups/settings`, {
        max_touches_per_week: next.max_touches_per_week, skip_weekends: next.skip_weekends,
        negative_reply_handling: next.negative_reply_handling, default_send_time: next.default_send_time || null,
        restart_on_resend: next.restart_on_resend,
      })
    } catch (e) { toast.err(apiError(e)) }
  }

  const deleteStep = async (id) => {
    if (!window.confirm('Delete this follow-up step?')) return
    try {
      await api.delete(`/campaigns/${campaignId}/followups/steps/${id}`)
      await load()
      toast.ok('Follow-up step deleted')
    } catch (e) { toast.err(apiError(e)) }
  }

  const moveStep = async (id, direction) => {
    try {
      const { data } = await api.post(`/campaigns/${campaignId}/followups/steps/${id}/move`, { direction })
      setSteps(data)
    } catch (e) { toast.err(apiError(e)) }
  }

  if (!settings || !steps) return <Spinner />

  const channelAvail = { email: true, whatsapp: project.whatsapp_active, sms: project.sms_active }
  const channelUsable = (key) => !!(channelAvail[key] && campaign[`${key}_enabled`])

  return (
    <div className="grid" style={{ gridTemplateColumns: '1.7fr 1fr', alignItems: 'start', gap: 20 }}>
      <div>
        <div className="card card-pad" style={{ marginBottom: 20 }}>
          <h3 style={{ fontSize: 15, marginBottom: 2 }}>Email follow-ups</h3>
          <p className="t-sub" style={{ marginBottom: 16 }}>Follow-ups stop automatically on a classified reply, or advance early based on engagement.</p>
          {replyCapture?.enabled && steps?.some((s) => s.trigger_type === 'no_reply') && (
            <p className="hint" style={{ marginTop: -10, marginBottom: 16 }}>
              Replies are checked roughly every {replyPollIntervalLabel(replyCapture.poll_interval_seconds)} —
              a "No reply" step due sooner than that may fire on top of a reply that hasn't been picked up yet.
            </p>
          )}
          <div className="row-3">
            <Field label="Max touches / week">
              <input className="input" type="number" min={1} max={10} disabled={!canEdit}
                value={settings.max_touches_per_week}
                onChange={(e) => patchSettings({ max_touches_per_week: Number(e.target.value) || 1 })} />
            </Field>
            <Field label="Skip weekends">
              <Toggle checked={settings.skip_weekends} disabled={!canEdit}
                label={settings.skip_weekends ? 'Enabled' : 'Disabled'}
                onChange={(v) => patchSettings({ skip_weekends: v })} />
            </Field>
            <Field label="Negative reply handling">
              <select className="select" disabled={!canEdit} value={settings.negative_reply_handling}
                onChange={(e) => patchSettings({ negative_reply_handling: e.target.value })}>
                <option value="tag_and_stop">Stop &amp; tag contact</option>
                <option value="stop_only">Stop only</option>
              </select>
            </Field>
            <Field label="Restart on resend"
              hint="If a recipient already had a follow-up sequence, sending this campaign again keeps it stopped by default rather than starting a new one from scratch.">
              <Toggle checked={!!settings.restart_on_resend} disabled={!canEdit}
                label={settings.restart_on_resend ? 'Restarts on resend' : "Doesn't restart on resend"}
                onChange={(v) => patchSettings({ restart_on_resend: v })} />
            </Field>
          </div>
        </div>

        {steps.length === 0 ? (
          <div className="card empty">
            <div className="ico"><Icon.repeat width={24} /></div>
            <h3 style={{ marginBottom: 6 }}>No follow-up steps yet</h3>
            <p className="muted">Add a step to automatically nudge recipients who don't open, click, or reply.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 30 }}></th><th>Trigger &amp; timing</th><th>Message</th><th>Channel</th>
                  <th>Performance</th>{canEdit && <th style={{ width: 120 }}>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {steps.map((s, i) => (
                  <tr key={s.id}>
                    <td>
                      <span className="ico" style={{ width: 24, height: 24, borderRadius: '50%', background: 'var(--teal-soft)', color: 'var(--teal)', display: 'grid', placeItems: 'center', fontSize: 11.5, fontWeight: 700 }}>{i + 1}</span>
                    </td>
                    <td>
                      <span className={`badge ${TRIGGER_BADGE[s.trigger_type]}`}><span className="d" />{TRIGGER_LABELS[s.trigger_type]}, {s.delay_value} {s.delay_unit}</span>
                      <div className="t-sub" style={{ marginTop: 4 }}>
                        {s.send_time ? `${s.send_time} local` : settings.default_send_time ? `${settings.default_send_time} local (default)` : 'sends as soon as due'}
                      </div>
                    </td>
                    <td>
                      <div className="t-strong">{s.subject || <span className="muted">No subject</span>}</div>
                      <div className="t-sub">{s.body_template ? `${s.body_template.slice(0, 60)}${s.body_template.length > 60 ? '…' : ''}` : 'No message body'}</div>
                    </td>
                    <td><ChannelCell step={s} channelUsable={channelUsable} /></td>
                    <td><StepStats stats={s.stats} campaignId={campaignId} stepId={s.id} /></td>
                    {canEdit && (
                      <td>
                        <div className="flex gap8">
                          <button className="btn btn-ghost btn-sm" title="Move up" disabled={i === 0} onClick={() => moveStep(s.id, 'up')}>↑</button>
                          <button className="btn btn-ghost btn-sm" title="Move down" disabled={i === steps.length - 1} onClick={() => moveStep(s.id, 'down')}>↓</button>
                          <button className="btn btn-ghost btn-sm" title="Edit" onClick={() => setEditing(s)}><Icon.edit width={13} /></button>
                          <button className="btn btn-ghost btn-sm" title="Delete" onClick={() => deleteStep(s.id)}><Icon.trash width={13} /></button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {canEdit && (
          <button className="btn btn-ghost mt16" style={{ width: '100%', borderStyle: 'dashed' }} onClick={() => setEditing({})}>
            <Icon.plus width={14} /> Add follow-up step
          </button>
        )}
      </div>

      <FollowUpFlowDiagram steps={steps} />

      {editing && (
        <StepEditorModal campaignId={campaignId} step={editing} channelAvail={channelAvail} columns={columns} toast={toast}
          onClose={() => setEditing(null)}
          onSaved={(data, isNew) => {
            setSteps((ss) => (isNew ? [...ss, data] : ss.map((s) => (s.id === data.id ? data : s))))
            setEditing(null)
          }} />
      )}
    </div>
  )
}

function ChannelCell({ step, channelUsable }) {
  const activeChannel = step.fallback_channel && channelUsable(step.fallback_channel) ? step.fallback_channel : step.primary_channel
  return (
    <div className="flex gap8" style={{ alignItems: 'center' }}>
      <span className={`chchip ${activeChannel === step.primary_channel ? 'on' : ''}`}>{FOLLOWUP_CHANNELS[step.primary_channel]}</span>
      {step.fallback_channel && (
        <>
          <span style={{ color: 'var(--faint)', fontSize: 11 }}>→</span>
          <span className={`chchip ${activeChannel === step.fallback_channel ? 'on' : ''}`}
            title={!channelUsable(step.fallback_channel) ? `Enable ${FOLLOWUP_CHANNELS[step.fallback_channel]} for this campaign to use it as a fallback.` : ''}>
            {FOLLOWUP_CHANNELS[step.fallback_channel]}
          </span>
        </>
      )}
    </div>
  )
}

function StepStats({ stats, campaignId, stepId }) {
  const nav = useNavigate()
  if (!stats || !stats.sent) return <span className="muted">—</span>
  // Deep-link into Tracking & Reports pre-filtered to this step -- Performance
  // here is a read-only rollup of the same rows Tracking shows, so "step 2 is
  // underperforming" to "which recipients specifically" stays a one-click hop.
  const go = () => nav('/tracking', { state: { campaignId: String(campaignId), stepId } })
  return (
    <div className="flex gap12" style={{ cursor: 'pointer' }} onClick={go} title="View these recipients in Tracking & Reports">
      <MiniPercent label="Open" value={stats.open_rate} color="var(--info)" />
      <MiniPercent label="Click" value={stats.click_rate} color="var(--teal)" />
      <MiniPercent label="Reply" value={stats.reply_rate} color="#7c3aed" />
    </div>
  )
}
function MiniPercent({ label, value, color }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontWeight: 700, fontSize: 13, color, fontFamily: 'var(--mono)' }}>{value}%</div>
      <div style={{ fontSize: 9.5, color: 'var(--muted)', textTransform: 'uppercase' }}>{label}</div>
    </div>
  )
}

function FollowUpFlowDiagram({ steps }) {
  const box = (label, sub) => (
    <div style={{ border: '1px solid var(--border)', borderRadius: 9, padding: '9px 16px', fontSize: 12.5, fontWeight: 600, background: 'var(--surface)', textAlign: 'center' }}>
      {label}{sub && <div style={{ fontWeight: 400, color: 'var(--muted)', fontSize: 11 }}>{sub}</div>}
    </div>
  )
  const arrow = <div style={{ width: 1, height: 16, background: 'var(--border-strong)' }} />
  const stepSub = (s) => `${TRIGGER_LABELS[s.trigger_type]} · ${s.delay_value}${s.delay_unit[0]}`

  return (
    <div className="card card-pad">
      <h3 style={{ fontSize: 15, marginBottom: 16 }}>Follow-up flow</h3>
      <div className="flex" style={{ flexDirection: 'column', alignItems: 'center', gap: 10 }}>
        {box('✉ Initial email', 'Immediately')}
        {arrow}
        {box('Reply classified?')}
        {arrow}
        <div className="flex" style={{ gap: 20, justifyContent: 'center', flexWrap: 'wrap' }}>
          <div className="flex" style={{ flexDirection: 'column', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--good)' }}>Interested</span>
            <div style={{ background: 'var(--good-soft)', border: '1px solid var(--good)', color: 'var(--good)', borderRadius: 9, padding: '9px 14px', fontSize: 12, fontWeight: 600, textAlign: 'center' }}>
              Stop follow-ups
            </div>
          </div>
          <div className="flex" style={{ flexDirection: 'column', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--danger)' }}>Not interested</span>
            <div style={{ background: 'var(--danger-soft)', border: '1px solid var(--danger)', color: 'var(--danger)', borderRadius: 9, padding: '9px 14px', fontSize: 12, fontWeight: 600, textAlign: 'center' }}>
              Stop &amp; tag contact
            </div>
          </div>
          <div className="flex" style={{ flexDirection: 'column', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--warn)' }}>No signal</span>
            {steps.length > 0 ? box('Follow-up 1', stepSub(steps[0])) : <span className="t-sub">Add a step</span>}
          </div>
        </div>
        {steps.length > 1 && (
          <div className="flex" style={{ justifyContent: 'center', gap: 10, flexWrap: 'wrap', marginTop: 4 }}>
            {steps.slice(1).map((s, i) => (
              <div key={s.id} className="flex gap8" style={{ alignItems: 'center' }}>
                <span style={{ color: 'var(--faint)' }}>→</span>
                {box(`Follow-up ${i + 2}`, stepSub(s))}
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="flex" style={{ gap: 16, marginTop: 20, fontSize: 11.5, color: 'var(--muted)', flexWrap: 'wrap' }}>
        <span className="flex gap8"><span style={{ width: 16, height: 2, background: 'var(--good)', display: 'inline-block' }} /> Stops follow-ups</span>
        <span className="flex gap8"><span style={{ width: 16, height: 2, background: 'var(--warn)', display: 'inline-block' }} /> Continues</span>
        <span className="flex gap8"><span style={{ width: 16, height: 2, background: 'var(--danger)', display: 'inline-block' }} /> Stops + tags</span>
      </div>
    </div>
  )
}

function StepEditorModal({ campaignId, step, channelAvail, columns, toast, onClose, onSaved }) {
  const isNew = !step.id
  const [form, setForm] = useState({
    trigger_type: step.trigger_type || 'no_reply',
    delay_value: step.delay_value || 3,
    delay_unit: step.delay_unit || 'days',
    send_time: step.send_time || '',
    primary_channel: step.primary_channel || 'email',
    fallback_channel: step.fallback_channel || '',
    subject: step.subject || '',
    body_template: step.body_template || '',
  })
  const [busy, setBusy] = useState(false)
  const setF = (k, v) => setForm((s) => ({ ...s, [k]: v }))
  const fallbackOptions = ['email', 'whatsapp', 'sms'].filter((c) => c !== form.primary_channel)

  const subjRef = useRef(); const bodyRef = useRef(); const focused = useRef('body_template')
  const insert = (token) => {
    const key = focused.current === 'subject' ? 'subject' : 'body_template'
    const el = key === 'subject' ? subjRef.current : bodyRef.current
    if (!el) { setF(key, (form[key] || '') + token); return }
    const start = el.selectionStart ?? el.value.length
    const end = el.selectionEnd ?? el.value.length
    const cur = form[key] || ''
    setF(key, cur.slice(0, start) + token + cur.slice(end))
    setTimeout(() => { el.focus(); el.selectionStart = el.selectionEnd = start + token.length }, 0)
  }

  const save = async () => {
    setBusy(true)
    const payload = { ...form, send_time: form.send_time || null, fallback_channel: form.fallback_channel || null }
    try {
      const { data } = isNew
        ? await api.post(`/campaigns/${campaignId}/followups/steps`, payload)
        : await api.put(`/campaigns/${campaignId}/followups/steps/${step.id}`, payload)
      onSaved(data, isNew)
    } catch (e) { toast.err(apiError(e)) } finally { setBusy(false) }
  }

  return (
    <Modal wide title={isNew ? 'Add follow-up step' : 'Edit follow-up step'} onClose={onClose}
      footer={<>
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save step'}</button>
      </>}>
      <div className="row-3">
        <Field label="Trigger condition">
          <select className="select" value={form.trigger_type} onChange={(e) => setF('trigger_type', e.target.value)}>
            <option value="no_reply">No reply</option>
            <option value="not_opened">Not opened</option>
            <option value="not_clicked">Not clicked</option>
          </select>
        </Field>
        <Field label="Delay">
          <div className="flex gap8">
            <input className="input" type="number" min={1} value={form.delay_value}
              onChange={(e) => setF('delay_value', Number(e.target.value) || 1)} />
            <select className="select" value={form.delay_unit} onChange={(e) => setF('delay_unit', e.target.value)}>
              <option value="hours">Hours</option>
              <option value="days">Days</option>
            </select>
          </div>
        </Field>
        <Field label="Send time" hint="Local time — falls back to the campaign default if unset">
          <input className="input" type="time" value={form.send_time} onChange={(e) => setF('send_time', e.target.value)} />
        </Field>
      </div>

      <div className="row-3">
        <Field label="Primary channel">
          <select className="select" value={form.primary_channel} onChange={(e) => setF('primary_channel', e.target.value)}>
            <option value="email">Email</option>
            <option value="whatsapp" disabled={!channelAvail.whatsapp}>WhatsApp{!channelAvail.whatsapp ? ' (not enabled)' : ''}</option>
            <option value="sms" disabled={!channelAvail.sms}>SMS{!channelAvail.sms ? ' (not enabled)' : ''}</option>
          </select>
        </Field>
        <Field label="Fallback channel"
          hint={form.fallback_channel && !channelAvail[form.fallback_channel]
            ? `Enable ${FOLLOWUP_CHANNELS[form.fallback_channel]} for this campaign to use it as a fallback.`
            : 'Used instead of the primary channel when this step actually fires'}>
          <select className="select" value={form.fallback_channel} onChange={(e) => setF('fallback_channel', e.target.value)}>
            <option value="">None</option>
            {fallbackOptions.map((c) => (
              <option key={c} value={c} disabled={!channelAvail[c]}>{FOLLOWUP_CHANNELS[c]}{!channelAvail[c] ? ' (not enabled)' : ''}</option>
            ))}
          </select>
        </Field>
      </div>

      <Field label="Subject">
        <input ref={subjRef} className="input" value={form.subject} onFocus={() => (focused.current = 'subject')}
          onChange={(e) => setF('subject', e.target.value)} placeholder="Reminder: an update from {{Company}}" />
      </Field>
      <Field label="Message body">
        <textarea ref={bodyRef} className="textarea" style={{ minHeight: 140 }} value={form.body_template}
          onFocus={() => (focused.current = 'body_template')}
          onChange={(e) => setF('body_template', e.target.value)} placeholder={'Hi {{Name}},\n\nJust checking if you received our last message…'} />
      </Field>

      {columns.length > 0 && (
        <div>
          <div className="t-sub">Insert placeholder:</div>
          <div className="ph-chips">
            {columns.map((c) => <span key={c} className="ph-chip" onClick={() => insert(`{{${c}}}`)}>{`{{${c}}}`}</span>)}
          </div>
        </div>
      )}
    </Modal>
  )
}

/* ---------------- Send ---------------- */
function SendStep({ campaign, project, contents, canSend, onChange, toast, nav }) {
  const [busy, setBusy] = useState(false)
  const [channelStatus, setChannelStatus] = useState(null)
  const [confirmResend, setConfirmResend] = useState(false)
  const [flags, setFlags] = useState({
    email_enabled: campaign.email_enabled, whatsapp_enabled: campaign.whatsapp_enabled, sms_enabled: campaign.sms_enabled,
  })

  useEffect(() => {
    api.get('/channels/status', { params: { project_id: project.id } }).then((r) => setChannelStatus(r.data)).catch(() => {})
  }, [project.id])

  const avail = { email: true, whatsapp: project.whatsapp_active, sms: project.sms_active }

  const toggle = async (field, ch, v) => {
    setFlags((s) => ({ ...s, [field]: v }))
    try { await api.put(`/campaigns/${campaign.id}`, { [field]: v }) } catch (e) { toast.err(apiError(e)) }
  }

  const send = async () => {
    setConfirmResend(false)
    setBusy(true)
    try {
      await api.post(`/campaigns/${campaign.id}/send`)
      toast.ok('Campaign sent! Processing complete.')
      onChange()
      setTimeout(() => nav('/tracking', { state: { campaignId: campaign.id } }), 600)
    } catch (e) { toast.err(apiError(e)) } finally { setBusy(false) }
  }

  const activeChannels = CHANNELS.filter((c) => flags[c.enField] && avail[c.key])
  const missingContent = activeChannels.filter((c) => !isContentAuthored(contents[c.key]))
  // Only an in-flight send blocks starting another -- a "completed" campaign
  // is deliberately re-sendable (e.g. a follow-up blast to the same dataset).
  // Resend now archives the prior send's tracking history rather than losing
  // it (see app/campaign_resend.py) -- confirmResend below just makes sure
  // that's understood before it happens, it doesn't block anything.
  const sendingInProgress = campaign.status === 'sending'
  const alreadySent = campaign.status === 'completed'
  const ready = !sendingInProgress && campaign.recipient_count > 0 && activeChannels.length > 0 && missingContent.length === 0

  return (
    <div className="grid grid-2" style={{ alignItems: 'start' }}>
      <div className="card card-pad">
        <h3 style={{ fontSize: 16, marginBottom: 4 }}>Communication channels</h3>
        <p className="muted" style={{ fontSize: 13, marginBottom: 16 }}>Only channels enabled on the project can be activated.</p>
        {CHANNELS.map((c) => {
          const Ico = Icon[c.icon]
          const available = avail[c.key]
          const live = channelStatus?.[c.key]?.live
          return (
            <div key={c.key} className="flex between" style={{ padding: '12px 0', borderBottom: '1px solid var(--border)' }}>
              <div className="flex gap12">
                <span className="ico" style={{ width: 38, height: 38, borderRadius: 9, background: available ? 'var(--teal-soft)' : '#5D69751a', color: available ? 'var(--teal)' : 'var(--faint)', display: 'grid', placeItems: 'center' }}><Ico width={18} /></span>
                <div>
                  <div className="flex gap8" style={{ alignItems: 'center' }}>
                    <span style={{ fontWeight: 650 }}>{c.label}</span>
                    {channelStatus && (live
                      ? <span className="badge green" title={channelStatus[c.key].provider}><span className="d" />Live</span>
                      : <span className="badge gray"><span className="d" />Simulated</span>)}
                  </div>
                  <div className="t-sub">{available ? (isContentAuthored(contents[c.key]) ? (live ? `Sends via ${channelStatus[c.key].provider}` : 'Content ready · simulated') : 'No content authored') : 'Not enabled on project'}</div>
                </div>
              </div>
              <Toggle checked={!!flags[c.enField] && available} onChange={(v) => toggle(c.enField, c.key, v)} />
            </div>
          )
        })}
        {channelStatus && (
          <p className="hint mt16"><b>Live</b> channels send to real recipients; <b>Simulated</b> channels record realistic statuses without sending.</p>
        )}
      </div>

      <div className="card card-pad">
        <h3 style={{ fontSize: 16, marginBottom: 16 }}>Ready to send</h3>
        <div className="grid" style={{ gap: 10 }}>
          <SummaryRow label="Recipients" value={campaign.recipient_count} ok={campaign.recipient_count > 0} />
          <SummaryRow label="Active channels" value={activeChannels.map((c) => c.label).join(', ') || '—'} ok={activeChannels.length > 0} />
          <SummaryRow label="Content authored" value={missingContent.length === 0 ? 'All set' : `Missing: ${missingContent.map((c) => c.label).join(', ')}`} ok={missingContent.length === 0} />
        </div>

        <div className="mt24" style={{ padding: 16, borderRadius: 11, background: 'var(--teal-soft2)', border: '1px solid var(--border)' }}>
          <div className="flex between">
            <div>
              <div style={{ fontWeight: 700 }}>{campaign.recipient_count * activeChannels.length} messages</div>
              <div className="t-sub">will be dispatched across {activeChannels.length} channel{activeChannels.length !== 1 ? 's' : ''}</div>
            </div>
            {canSend && !sendingInProgress && (
              <button className="btn btn-primary" disabled={!ready || busy}
                onClick={() => (alreadySent ? setConfirmResend(true) : send())}>
                {busy ? 'Sending…' : <><Icon.send width={16} /> {alreadySent ? 'Send again' : 'Send campaign'}</>}
              </button>
            )}
          </div>
          {sendingInProgress && <p className="hint mt8">This campaign is currently sending — check back shortly.</p>}
          {!sendingInProgress && alreadySent && (
            <p className="hint mt8">Already sent once — sending again will re-dispatch to all current recipients.</p>
          )}
          {!sendingInProgress && !ready && <p className="hint mt8">Complete the checklist above to enable sending.</p>}
          {!sendingInProgress && !canSend && <p className="hint mt8">You don't have permission to send campaigns.</p>}
        </div>
      </div>

      {confirmResend && (
        <Modal title="Send this campaign again?" onClose={() => setConfirmResend(false)}
          footer={<>
            <button className="btn btn-ghost" onClick={() => setConfirmResend(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={send} disabled={busy}>
              {busy ? 'Sending…' : <><Icon.send width={15} /> Send again</>}
            </button>
          </>}>
          <p style={{ marginBottom: 0 }}>
            This campaign was already sent once. Sending again will re-dispatch to all current recipients.
            Previous tracking history (opens/clicks/replies) will be archived and viewable as a separate
            send in Tracking &amp; Reports, not lost.
          </p>
        </Modal>
      )}
    </div>
  )
}

function SummaryRow({ label, value, ok }) {
  return (
    <div className="flex between" style={{ padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 9 }}>
      <span className="flex gap8">
        <span style={{ width: 20, height: 20, borderRadius: '50%', display: 'grid', placeItems: 'center', background: ok ? 'var(--good-soft)' : 'var(--warn-soft)', color: ok ? 'var(--good)' : 'var(--warn)' }}>
          {ok ? <Icon.check width={13} /> : '!'}
        </span>
        {label}
      </span>
      <span className="t-strong" style={{ textAlign: 'right' }}>{value}</span>
    </div>
  )
}
