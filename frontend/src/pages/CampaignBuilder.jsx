import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import Layout from '../components/Layout'
import { useAuth } from '../auth'
import api, { apiError } from '../api'
import { Icon, Field, StatusBadge, Toggle, Spinner, useToast } from '../components/ui'
import { BLANK_TPL_FIELDS, TemplateFieldsForm } from '../components/TemplateFieldsForm'
import TemplatePicker from '../components/TemplatePicker'

const CHANNELS = [
  { key: 'email', label: 'Email', icon: 'mail', enField: 'email_enabled', hasSubject: true },
  { key: 'whatsapp', label: 'WhatsApp', icon: 'chat', enField: 'whatsapp_enabled', hasSubject: false },
  { key: 'sms', label: 'SMS', icon: 'phone', enField: 'sms_enabled', hasSubject: false },
]

function isContentAuthored(channelKey, val) {
  if (!val) return false
  if (channelKey === 'email' && val.content_mode === 'template') {
    const f = val.template_fields || {}
    return !!(f.headline || f.opening_line)
  }
  return !!val.body
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
      api.get(`/campaigns/${id}/recipients`),
      api.get(`/campaigns/${id}/content`),
      api.get(`/projects/${c.project_id}`),
    ])
    setRecipients(recs)
    setProject(proj)
    const map = {}
    cont.forEach((x) => {
      map[x.channel] = { subject: x.subject, body: x.body, content_mode: x.content_mode, template_fields: x.template_fields }
    })
    setContents(map)
  }
  useEffect(() => { load() }, [id])

  if (!campaign || !project) return <Layout title="Campaign"><Spinner /></Layout>

  const steps = [['recipients', 'Recipients', 'upload'], ['content', 'Content', 'edit'], ['send', 'Review & Send', 'send']]

  return (
    <Layout title={campaign.name} crumb={<span style={{ cursor: 'pointer' }} onClick={() => nav('/campaigns')}>← Campaigns</span>}>
      <div className="page-head">
        <div>
          <div className="flex gap12">
            <div className="pt">{campaign.name}</div>
            <StatusBadge status={campaign.status} />
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
          canEdit={can('dataset.upload')} onUploaded={(c) => { load(); toast.ok(`${c.recipient_count} recipients imported`) }}
          onChange={load} toast={toast} onError={(m) => toast.err(m)} />
      )}
      {step === 'content' && (
        <ContentStep campaign={campaign} campaignId={id} columns={campaign.columns} contents={contents} setContents={setContents}
          recipients={recipients} project={project} canEdit={can('content.edit')} toast={toast} onCampaignChange={load} />
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
function RecipientsStep({ campaignId, recipients, setRecipients, columns, canEdit, onUploaded, onChange, toast, onError }) {
  const fileRef = useRef()
  const [busy, setBusy] = useState(false)
  const [showAdd, setShowAdd] = useState(false)
  const [rec, setRec] = useState(BLANK_REC)
  const [adding, setAdding] = useState(false)
  const setF = (k, v) => setRec((s) => ({ ...s, [k]: v }))
  const extraCols = columns.filter((c) => !['name', 'email address', 'mobile number', 'email', 'mobile', 'phone'].includes(c.toLowerCase())).slice(0, 3)

  const upload = async (file) => {
    if (!file) return
    setBusy(true)
    const fd = new FormData()
    fd.append('file', file)
    try {
      const { data } = await api.post(`/campaigns/${campaignId}/dataset`, fd, { headers: { 'Content-Type': 'multipart/form-data' } })
      onUploaded(data)
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
      {canEdit && (
        <div className="card card-pad" style={{ marginBottom: 20 }}>
          <div className="flex between wrap-gap">
            <div className="flex gap12">
              <span className="ico" style={{ width: 44, height: 44, borderRadius: 11, background: 'var(--teal-soft)', color: 'var(--teal)', display: 'grid', placeItems: 'center' }}><Icon.upload width={20} /></span>
              <div>
                <div style={{ fontWeight: 700 }}>Upload recipient dataset</div>
                <div className="t-sub">Excel (.xlsx) or CSV — must include <b>Name</b>, <b>Email Address</b> &amp; <b>Mobile Number</b>. Or add recipients one at a time. Choosing a new file replaces the existing recipients.</div>
              </div>
            </div>
            <div className="flex gap8">
              <button className="btn btn-ghost" onClick={() => setShowAdd((s) => !s)}><Icon.userplus width={15} /> Add recipient</button>
              {recipients.length > 0 && (
                <button className="btn btn-ghost" disabled={busy} onClick={removeDataset}><Icon.trash width={15} /> Remove dataset</button>
              )}
              <input ref={fileRef} type="file" accept=".csv,.xlsx" style={{ display: 'none' }} onChange={(e) => upload(e.target.files[0])} />
              <button className="btn btn-primary" disabled={busy} onClick={() => fileRef.current.click()}>
                {busy ? 'Importing…' : <><Icon.upload width={15} /> Choose file</>}
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

      {recipients.length === 0 ? (
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
            <span className="t-sub">{recipients.length} recipient{recipients.length !== 1 ? 's' : ''}</span>
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
          {recipients.length > 100 && <p className="t-sub mt8">Showing first 100 of {recipients.length}.</p>}
        </>
      )}
    </>
  )
}

/* ---------------- Content ---------------- */
function ContentStep({ campaign, campaignId, columns, contents, setContents, recipients, project, canEdit, toast, onCampaignChange }) {
  const [active, setActive] = useState('email')
  const [preview, setPreview] = useState({ subject: '', body: '', missing: [] })
  const [tplPreview, setTplPreview] = useState({ html: '', missing: [] })
  const [recipientId, setRecipientId] = useState(recipients[0]?.id || null)
  const [saving, setSaving] = useState(false)
  const [templates, setTemplates] = useState([])
  const [tplRef, setTplRef] = useState(campaign.sms_template_ref || '')
  const [dlt, setDlt] = useState(null) // {valid, reason}
  const bodyRef = useRef(); const subjRef = useRef(); const focused = useRef('body')
  const tplRefs = useRef({}); const tplFocused = useRef('opening_line')

  const ch = CHANNELS.find((c) => c.key === active)
  const val = contents[active] || { subject: '', body: '', content_mode: 'plain', template_fields: BLANK_TPL_FIELDS }
  const setVal = (patch) => setContents((s) => ({ ...s, [active]: { ...val, ...patch } }))
  const isTemplateMode = active === 'email' && val.content_mode === 'template'
  const tf = val.template_fields || BLANK_TPL_FIELDS

  useEffect(() => { api.get('/sms/templates').then((r) => setTemplates(r.data)).catch(() => {}) }, [])
  const selectedTpl = templates.find((t) => t.id === Number(tplRef))

  const getTplValue = (path) => {
    if (path.startsWith('bullets.')) {
      const [, idx, key] = path.split('.')
      return (tf.bullets && tf.bullets[Number(idx)] && tf.bullets[Number(idx)][key]) || ''
    }
    return tf[path] || ''
  }
  const setTplField = (path, v) => {
    if (path.startsWith('bullets.')) {
      const [, idx, key] = path.split('.')
      const bullets = [...(tf.bullets && tf.bullets.length ? tf.bullets : BLANK_TPL_FIELDS.bullets)]
      bullets[Number(idx)] = { ...bullets[Number(idx)], [key]: v }
      setVal({ template_fields: { ...tf, bullets } })
    } else {
      setVal({ template_fields: { ...tf, [path]: v } })
    }
  }

  const insert = (token) => {
    if (isTemplateMode) {
      const path = tplFocused.current
      const el = tplRefs.current[path]
      const cur = getTplValue(path)
      if (!el) { setTplField(path, cur + token); return }
      const start = el.selectionStart ?? cur.length
      const end = el.selectionEnd ?? cur.length
      const next = cur.slice(0, start) + token + cur.slice(end)
      setTplField(path, next)
      setTimeout(() => { el.focus(); el.selectionStart = el.selectionEnd = start + token.length }, 0)
      return
    }
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
      if (active === 'email') {
        payload.content_mode = val.content_mode || 'plain'
        payload.template_fields = tf
      }
      await api.put(`/campaigns/${campaignId}/content/${active}`, payload)
      toast.ok(`${ch.label} content saved`)
    } catch (e) { toast.err(apiError(e)) } finally { setSaving(false) }
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
      if (isTemplateMode) {
        const { data } = await api.post(`/campaigns/${campaignId}/preview-template`, {
          fields: tf, recipient_id: recipientId,
        })
        setTplPreview(data)
      } else {
        const { data } = await api.post(`/campaigns/${campaignId}/preview`, {
          channel: active, subject: val.subject || '', body: val.body || '', recipient_id: recipientId,
        })
        setPreview(data)
      }
    } catch (e) { toast.err(apiError(e)) }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { runPreview() }, [active, recipientId, val.subject, val.body, val.content_mode, JSON.stringify(tf)])

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

        {(active === 'email' || active === 'whatsapp') && (
          <div className="flex" style={{ justifyContent: 'flex-end', marginBottom: 12 }}>
            <TemplatePicker channel={active} campaignId={campaignId} canEdit={canEdit} toast={toast}
              onApplied={() => api.get(`/campaigns/${campaignId}/content`).then((r) => {
                const map = {}
                r.data.forEach((x) => { map[x.channel] = { subject: x.subject, body: x.body, content_mode: x.content_mode, template_fields: x.template_fields } })
                setContents(map)
              })} />
          </div>
        )}

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

        {active === 'email' && (
          <div className="field">
            <label>Content mode</label>
            <div className="tabs" style={{ marginBottom: 0 }}>
              <div className={`tab ${(val.content_mode || 'plain') === 'plain' ? 'active' : ''}`}
                onClick={() => canEdit && setVal({ content_mode: 'plain' })}>Plain text</div>
              <div className={`tab ${val.content_mode === 'template' ? 'active' : ''}`}
                onClick={() => canEdit && setVal({ content_mode: 'template', template_fields: tf })}>Use branded template</div>
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

        {isTemplateMode ? (
          <TemplateFieldsForm project={project} tf={tf} getTplValue={getTplValue} setTplField={setTplField}
            tplRefs={tplRefs} tplFocused={tplFocused} canEdit={canEdit} />
        ) : (
          <div className="field">
            <label>Message body</label>
            <textarea ref={bodyRef} className="textarea" style={{ minHeight: 180 }}
              value={val.body || ''} disabled={!canEdit}
              onFocus={() => (focused.current = 'body')}
              onChange={(e) => setVal({ body: e.target.value })}
              placeholder={`Hello {{Name}},\n\nWrite your ${ch.label} message here…`} />
          </div>
        )}

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
          {isTemplateMode ? (
            <>
              {tplPreview.missing && tplPreview.missing.length > 0 && (
                <div className="hint" style={{ marginBottom: 10, color: 'var(--warn)' }}>
                  ⚠ No value found for: {tplPreview.missing.map((m) => `{{${m}}}`).join(', ')} — sent as blank.
                </div>
              )}
              <iframe title="Email preview" srcDoc={tplPreview.html || '<body></body>'} sandbox=""
                style={{ width: '100%', height: 520, border: '1px solid var(--border)', borderRadius: 10, background: '#fff' }} />
            </>
          ) : (
            <>
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
            </>
          )}
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

/* ---------------- Send ---------------- */
function SendStep({ campaign, project, contents, canSend, onChange, toast, nav }) {
  const [busy, setBusy] = useState(false)
  const [channelStatus, setChannelStatus] = useState(null)
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
    setBusy(true)
    try {
      await api.post(`/campaigns/${campaign.id}/send`)
      toast.ok('Campaign sent! Processing complete.')
      onChange()
      setTimeout(() => nav('/tracking', { state: { campaignId: campaign.id } }), 600)
    } catch (e) { toast.err(apiError(e)) } finally { setBusy(false) }
  }

  const activeChannels = CHANNELS.filter((c) => flags[c.enField] && avail[c.key])
  const missingContent = activeChannels.filter((c) => !isContentAuthored(c.key, contents[c.key]))
  const ready = campaign.recipient_count > 0 && activeChannels.length > 0 && missingContent.length === 0

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
                  <div className="t-sub">{available ? (isContentAuthored(c.key, contents[c.key]) ? (live ? `Sends via ${channelStatus[c.key].provider}` : 'Content ready · simulated') : 'No content authored') : 'Not enabled on project'}</div>
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
            {canSend && (
              <button className="btn btn-primary" disabled={!ready || busy} onClick={send}>
                {busy ? 'Sending…' : <><Icon.send width={16} /> Send campaign</>}
              </button>
            )}
          </div>
          {!ready && <p className="hint mt8">Complete the checklist above to enable sending.</p>}
          {!canSend && <p className="hint mt8">You don't have permission to send campaigns.</p>}
        </div>
      </div>
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
