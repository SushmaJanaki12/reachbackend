import { useEffect, useRef, useState } from 'react'
import Layout from '../components/Layout'
import { useAuth } from '../auth'
import api, { apiError } from '../api'
import { Icon, Modal, Field, StatusBadge, Spinner, Pager, useToast } from '../components/ui'

// /templates now returns one page at a time (see app/pagination.py) --
// this page merges it with the always-fetched-in-full /sms/templates list
// (a separate, DLT-bounded table with no pagination of its own) and
// client-sorts the combination, so true page-through UI isn't a clean fit
// here. Requesting the max page size covers realistic library sizes
// without a regression; TEMPLATES_PAGE_SIZE below only kicks in past that.
const TEMPLATES_PAGE_SIZE = 100
import { BLANK_TPL_FIELDS, TemplateFieldsForm, useTplFieldAccessors } from '../components/TemplateFieldsForm'

const CHANNEL_OPTS = [
  { key: 'email', label: 'Email', icon: 'mail' },
  { key: 'whatsapp', label: 'WhatsApp', icon: 'chat' },
  { key: 'sms', label: 'SMS', icon: 'phone' },
]

const NAME_PLACEHOLDER = { email: 'Welcome email', whatsapp: 'Order confirmation', sms: 'OTP verification' }

const BLANK_WA_CONTENT = {
  meta_template_name: '', meta_template_id: '', language_code: 'en_US',
  header_type: 'none', header_content: '', body_text: '', footer_text: '', buttons: [],
}

const fmtSize = (n) => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / (1024 * 1024)).toFixed(1)} MB`)

// SMS templates live in their own DLT-registered table (no draft/published
// lifecycle) -- normalized into the same row shape as the Email/WhatsApp
// library so they can share one table/filter UI. `_smsRaw` carries the
// original object, since a PUT to /sms/templates/{id} requires every field.
const smsToRow = (t) => ({
  id: t.id, name: t.name, description: '', channel: 'sms', category: null,
  status: t.is_active ? 'published' : 'archived',
  created_at: t.created_at, updated_at: t.created_at,
  _sms: true, _smsRaw: t,
})

export default function Templates() {
  const { can } = useAuth()
  const toast = useToast()
  const canEdit = can('template.edit')
  const canArchive = can('template.archive')
  const canDelete = can('template.delete')
  // SMS DLT templates carry telecom-compliance weight, so they stay gated
  // behind the same permission Settings used to require for them.
  const canManageSms = can('project.configure_channels') || can('system.configure')
  const canCreate = canEdit || canManageSms

  const [items, setItems] = useState(null)
  const [categories, setCategories] = useState([])
  const [channel, setChannel] = useState('all')
  const [status, setStatus] = useState('all')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [templatesTotal, setTemplatesTotal] = useState(0)
  const [creating, setCreating] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [editingSms, setEditingSms] = useState(null)

  const load = () => {
    setItems(null)
    const wantTemplates = channel !== 'sms'
    const wantSms = channel === 'all' || channel === 'sms'

    const templatesReq = wantTemplates
      ? api.get('/templates', {
          params: {
            ...(channel !== 'all' ? { channel } : {}),
            ...(status !== 'all' ? { status } : {}),
            ...(q ? { q } : {}),
            page, page_size: TEMPLATES_PAGE_SIZE,
          },
        }).then((r) => { setTemplatesTotal(Number(r.headers['x-total-count']) || r.data.length); return r.data })
          .catch(() => [])
      : Promise.resolve([])

    const smsReq = wantSms
      ? api.get('/sms/templates').then((r) => r.data.map(smsToRow)).catch(() => [])
      : Promise.resolve([])

    Promise.all([templatesReq, smsReq]).then(([tpl, sms]) => {
      let merged = [...tpl, ...sms]
      if (wantSms) {
        merged = merged.filter((t) => {
          if (!t._sms) return true
          if (status !== 'all' && t.status !== status) return false
          if (q && !t.name.toLowerCase().includes(q.toLowerCase())) return false
          return true
        })
      }
      merged.sort((a, b) => new Date(b.updated_at || 0) - new Date(a.updated_at || 0))
      setItems(merged)
    })
  }
  useEffect(() => { load() }, [channel, status, q, page])
  useEffect(() => { setPage(1) }, [channel, status, q])
  useEffect(() => { api.get('/template-categories').then((r) => setCategories(r.data)).catch(() => {}) }, [])

  const addCategory = (cat) => setCategories((c) => [...c, cat].sort((a, b) => a.name.localeCompare(b.name)))

  const duplicate = async (t) => {
    try { await api.post(`/templates/${t.id}/duplicate`); toast.ok('Template duplicated'); load() }
    catch (e) { toast.err(apiError(e)) }
  }
  const archive = async (t) => {
    try { await api.post(`/templates/${t.id}/archive`); toast.ok('Template archived'); load() }
    catch (e) { toast.err(apiError(e)) }
  }
  const restore = async (t) => {
    try { await api.put(`/templates/${t.id}`, { status: 'draft' }); toast.ok('Moved back to draft'); load() }
    catch (e) { toast.err(apiError(e)) }
  }
  const remove = async (t) => {
    try { await api.delete(`/templates/${t.id}`); toast.ok('Template deleted'); load() }
    catch (e) { toast.err(apiError(e)) }
  }

  const smsToggleActive = async (raw) => {
    try {
      await api.put(`/sms/templates/${raw.id}`, {
        name: raw.name, template_id: raw.template_id, sender_id: raw.sender_id,
        body: raw.body, is_active: !raw.is_active,
      })
      toast.ok(raw.is_active ? 'Template archived' : 'Template restored')
      load()
    } catch (e) { toast.err(apiError(e)) }
  }
  const smsRemove = async (raw) => {
    try { await api.delete(`/sms/templates/${raw.id}`); toast.ok('Template deleted'); load() }
    catch (e) { toast.err(apiError(e)) }
  }

  return (
    <Layout title="Templates" crumb="Workspace / Templates">
      <div className="page-head">
        <div>
          <div className="pt">Message templates</div>
          <div className="ps">Reusable Email, WhatsApp &amp; SMS content, shared across every project.</div>
        </div>
        {canCreate && (
          <button className="btn btn-primary" onClick={() => setCreating(true)}><Icon.plus width={16} /> New template</button>
        )}
      </div>

      <div className="flex gap12 wrap-gap" style={{ marginBottom: 16 }}>
        <select className="select" style={{ width: 160 }} value={channel} onChange={(e) => setChannel(e.target.value)}>
          <option value="all">All channels</option>
          {CHANNEL_OPTS.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
        </select>
        <select className="select" style={{ width: 160 }} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="all">All statuses</option>
          <option value="draft">Draft</option>
          <option value="published">Published</option>
          <option value="archived">Archived</option>
        </select>
        <input className="input" style={{ width: 240 }} placeholder="Search by name…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      {items === null ? <Spinner /> : items.length === 0 ? (
        <div className="card empty">
          <div className="ico"><Icon.mail width={24} /></div>
          <h3 style={{ marginBottom: 6 }}>No templates yet</h3>
          <p className="muted" style={{ marginBottom: 16 }}>Create a reusable Email, WhatsApp or SMS template for your campaigns.</p>
          {canCreate && <button className="btn btn-primary" onClick={() => setCreating(true)}><Icon.plus width={16} /> New template</button>}
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Template</th><th>Channel</th><th>Category</th><th>Status</th><th>Updated</th><th></th></tr></thead>
            <tbody>
              {items.map((t) => {
                const c = CHANNEL_OPTS.find((x) => x.key === t.channel)
                const Ico = c ? Icon[c.icon] : Icon.mail
                const rowCanEdit = t._sms ? canManageSms : canEdit
                const rowCanArchive = t._sms ? canManageSms : canArchive
                const rowCanDelete = t._sms ? canManageSms : canDelete
                const openEditor = () => (t._sms ? setEditingSms(t._smsRaw) : setEditingId(t.id))
                return (
                  <tr key={`${t._sms ? 'sms' : 'tpl'}-${t.id}`}>
                    <td className="t-strong" style={{ cursor: rowCanEdit ? 'pointer' : 'default' }}
                      onClick={() => rowCanEdit && openEditor()}>
                      {t.name}{t.description && <div className="t-sub">{t.description}</div>}
                    </td>
                    <td><span className="chchip on"><Ico width={12} /> {c?.label || t.channel}</span></td>
                    <td className="muted">{t.category?.name || '—'}</td>
                    <td><StatusBadge status={t.status} /></td>
                    <td className="muted">{t.updated_at ? new Date(t.updated_at).toLocaleDateString() : '—'}</td>
                    <td style={{ textAlign: 'right' }}>
                      <div className="flex gap8" style={{ justifyContent: 'flex-end' }}>
                        {rowCanEdit && (
                          <button className="btn btn-ghost btn-sm" onClick={openEditor}><Icon.edit width={13} /></button>
                        )}
                        {!t._sms && rowCanEdit && (
                          <button className="btn btn-ghost btn-sm" onClick={() => duplicate(t)}>Duplicate</button>
                        )}
                        {rowCanArchive && t.status !== 'archived' && (
                          <button className="btn btn-ghost btn-sm" onClick={() => (t._sms ? smsToggleActive(t._smsRaw) : archive(t))}>Archive</button>
                        )}
                        {rowCanArchive && t.status === 'archived' && (
                          <button className="btn btn-ghost btn-sm" onClick={() => (t._sms ? smsToggleActive(t._smsRaw) : restore(t))}>Restore</button>
                        )}
                        {rowCanDelete && (
                          <button className="btn btn-ghost btn-sm" title="Delete" onClick={() => (t._sms ? smsRemove(t._smsRaw) : remove(t))}><Icon.trash width={13} /></button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {templatesTotal > TEMPLATES_PAGE_SIZE && (
        <Pager page={page} pageSize={TEMPLATES_PAGE_SIZE} total={templatesTotal} onPage={setPage} />
      )}

      {creating && (
        <CreateTemplate categories={categories} onCategoryCreated={addCategory} onClose={() => setCreating(false)}
          onCreated={(t) => { setCreating(false); load(); setEditingId(t.id) }}
          onCreatedSms={(t) => { setCreating(false); load(); setEditingSms(t) }}
          onError={(m) => toast.err(m)} />
      )}
      {editingId && (
        <TemplateEditor templateId={editingId} categories={categories} onCategoryCreated={addCategory} canEdit={canEdit}
          onClose={() => { setEditingId(null); load() }} toast={toast} />
      )}
      {editingSms && (
        <SmsTemplateEditor initial={editingSms} canEdit={canManageSms}
          onClose={() => setEditingSms(null)}
          onSaved={() => { setEditingSms(null); load(); toast.ok('Template saved') }}
          onError={(m) => toast.err(m)} />
      )}
    </Layout>
  )
}

/** Category <select> with an inline "add new category" affordance -- the
 * backend has always had POST /template-categories, but nothing in the UI
 * ever called it, so the dropdown was permanently stuck at "No category"
 * for anyone who couldn't hit the API directly. */
function CategoryField({ categories, value, onChange, onCategoryCreated }) {
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const toast = useToast()

  const submit = async () => {
    if (!name.trim()) return
    setBusy(true)
    try {
      const { data } = await api.post('/template-categories', { name: name.trim() })
      onCategoryCreated(data)
      onChange(String(data.id))
      setAdding(false); setName('')
    } catch (e) { toast.err(apiError(e)) } finally { setBusy(false) }
  }

  if (adding) {
    return (
      <Field label="Category">
        <div className="flex gap8">
          <input className="input" autoFocus placeholder="New category name" value={name}
            onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && submit()} />
          <button type="button" className="btn btn-ghost btn-sm" onClick={submit} disabled={busy || !name.trim()}>Add</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setAdding(false); setName('') }}>Cancel</button>
        </div>
      </Field>
    )
  }

  return (
    <Field label="Category">
      <select className="select" value={value}
        onChange={(e) => (e.target.value === '__new__' ? setAdding(true) : onChange(e.target.value))}>
        <option value="">No category</option>
        {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        <option value="__new__">+ Add new category…</option>
      </select>
    </Field>
  )
}

function CreateTemplate({ categories, onCategoryCreated, onClose, onCreated, onCreatedSms, onError }) {
  const [channel, setChannel] = useState('email')
  const [name, setName] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [templateId, setTemplateId] = useState('')
  const [senderId, setSenderId] = useState('')
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)

  const canSave = channel === 'sms'
    ? name.trim() && templateId.trim() && body.trim()
    : !!name.trim()

  const save = async () => {
    setBusy(true)
    try {
      if (channel === 'sms') {
        const { data } = await api.post('/sms/templates', {
          name, template_id: templateId, sender_id: senderId, body, is_active: true,
        })
        onCreatedSms(data)
      } else {
        const payload = { name, channel, category_id: categoryId ? Number(categoryId) : null }
        if (channel === 'email') payload.email_content = { subject: '', fields: BLANK_TPL_FIELDS }
        if (channel === 'whatsapp') payload.whatsapp_content = BLANK_WA_CONTENT
        const { data } = await api.post('/templates', payload)
        onCreated(data)
      }
    } catch (e) { onError(apiError(e)) } finally { setBusy(false) }
  }

  return (
    <Modal title="New template" onClose={onClose}
      footer={<>
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={busy || !canSave}>{busy ? 'Creating…' : 'Create'}</button>
      </>}>
      <Field label="Channel *">
        <div className="tabs" style={{ marginBottom: 0 }}>
          {CHANNEL_OPTS.map((c) => {
            const Ico = Icon[c.icon]
            return <div key={c.key} className={`tab ${channel === c.key ? 'active' : ''}`} onClick={() => setChannel(c.key)}>
              <span className="flex gap8"><Ico width={14} /> {c.label}</span>
            </div>
          })}
        </div>
      </Field>
      <Field label="Template name *">
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder={NAME_PLACEHOLDER[channel]} autoFocus />
      </Field>
      {channel === 'sms' ? (
        <>
          <div className="row-2">
            <Field label="DLT template ID *"><input className="input" value={templateId} onChange={(e) => setTemplateId(e.target.value)} placeholder="1707168726031344535" /></Field>
            <Field label="Sender ID"><input className="input" value={senderId} onChange={(e) => setSenderId(e.target.value)} placeholder="MISTAE" /></Field>
          </div>
          <Field label="Registered template text *" hint="Use {#var#} or {{var}} for variable parts — exactly as approved by the operator.">
            <textarea className="textarea" value={body} onChange={(e) => setBody(e.target.value)} placeholder="Dear customer, ... {#var#} ..." />
          </Field>
        </>
      ) : (
        <CategoryField categories={categories} value={categoryId} onChange={setCategoryId} onCategoryCreated={onCategoryCreated} />
      )}
    </Modal>
  )
}

function SmsTemplateEditor({ initial, canEdit, onClose, onSaved, onError }) {
  const [f, setF] = useState({
    name: initial.name, template_id: initial.template_id, sender_id: initial.sender_id,
    body: initial.body, is_active: initial.is_active,
  })
  const [busy, setBusy] = useState(false)
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }))

  const save = async () => {
    setBusy(true)
    try { await api.put(`/sms/templates/${initial.id}`, f); onSaved() }
    catch (e) { onError(apiError(e)) } finally { setBusy(false) }
  }

  return (
    <Modal title="Edit template · SMS" onClose={onClose}
      footer={<>
        <button className="btn btn-ghost" onClick={onClose}>Close</button>
        {canEdit && <button className="btn btn-primary" onClick={save} disabled={busy || !f.name || !f.template_id || !f.body}>{busy ? 'Saving…' : 'Save'}</button>}
      </>}>
      <p className="hint">DLT-registered templates must exactly match what's approved by the telecom operator (India DLT) — editing the text here does not re-register it.</p>
      <div className="row-2">
        <Field label="Template name *"><input className="input" value={f.name} disabled={!canEdit} onChange={(e) => set('name', e.target.value)} /></Field>
        <Field label="Sender ID"><input className="input" value={f.sender_id} disabled={!canEdit} onChange={(e) => set('sender_id', e.target.value)} placeholder="MISTAE" /></Field>
      </div>
      <Field label="DLT template ID *"><input className="input" value={f.template_id} disabled={!canEdit} onChange={(e) => set('template_id', e.target.value)} /></Field>
      <Field label="Registered template text *" hint="Use {#var#} or {{var}} for variable parts — exactly as approved by the operator.">
        <textarea className="textarea" style={{ minHeight: 100 }} value={f.body} disabled={!canEdit} onChange={(e) => set('body', e.target.value)} />
      </Field>
    </Modal>
  )
}

function TemplateAttachments({ templateId, canEdit, toast }) {
  const [attachments, setAttachments] = useState([])
  const [busy, setBusy] = useState(false)
  const fileRef = useRef()

  const load = () => api.get(`/templates/${templateId}/attachments`).then((r) => setAttachments(r.data)).catch(() => {})
  useEffect(() => { load() }, [templateId])

  const upload = async (files) => {
    if (!files || !files.length) return
    setBusy(true)
    try {
      for (const file of files) {
        const fd = new FormData()
        fd.append('file', file)
        await api.post(`/templates/${templateId}/attachments`, fd, { headers: { 'Content-Type': 'multipart/form-data' } })
      }
      await load()
      toast.ok('Attachment(s) uploaded')
    } catch (e) { toast.err(apiError(e)) } finally { setBusy(false); if (fileRef.current) fileRef.current.value = '' }
  }

  const remove = async (id) => {
    const prev = attachments
    setAttachments((a) => a.filter((x) => x.id !== id))
    try { await api.delete(`/templates/${templateId}/attachments/${id}`) }
    catch (e) { setAttachments(prev); toast.err(apiError(e)) }
  }

  const totalBytes = attachments.reduce((s, a) => s + a.size_bytes, 0)

  return (
    <Field label="Attachments" hint="Shared by anyone who uses this template · 10MB total">
      {attachments.length > 0 && (
        <div className="wrap-gap" style={{ marginBottom: 10 }}>
          {attachments.map((a) => (
            <span key={a.id} className="ph-chip" style={{ cursor: 'default', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <Icon.paperclip width={12} /> {a.filename} <span className="muted">({fmtSize(a.size_bytes)})</span>
              {canEdit && <span onClick={() => remove(a.id)} title="Remove attachment" style={{ cursor: 'pointer', marginLeft: 2, fontWeight: 700 }}>&times;</span>}
            </span>
          ))}
        </div>
      )}
      {canEdit && (
        <div className="flex gap8" style={{ alignItems: 'center' }}>
          <input ref={fileRef} type="file" multiple style={{ display: 'none' }} onChange={(e) => upload(e.target.files)} />
          <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => fileRef.current.click()}>
            {busy ? 'Uploading…' : <><Icon.paperclip width={14} /> Add attachment</>}
          </button>
          {attachments.length > 0 && <span className="t-sub">{fmtSize(totalBytes)} used</span>}
        </div>
      )}
    </Field>
  )
}

function TemplateEditor({ templateId, categories, onCategoryCreated, canEdit, onClose, toast }) {
  const [tpl, setTpl] = useState(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [subject, setSubject] = useState('')
  const [tf, setTf] = useState(BLANK_TPL_FIELDS)
  const [wa, setWa] = useState(BLANK_WA_CONTENT)
  const [projects, setProjects] = useState([])
  const [previewProjectId, setPreviewProjectId] = useState('')
  const [preview, setPreview] = useState({ html: '', missing: [] })
  const [saving, setSaving] = useState(false)
  const tplRefs = { current: {} }
  const tplFocused = { current: 'headline' }

  useEffect(() => {
    api.get(`/templates/${templateId}`).then((r) => {
      const t = r.data
      setTpl(t)
      setName(t.name); setDescription(t.description); setCategoryId(t.category?.id || '')
      if (t.channel === 'email' && t.email_content) {
        setSubject(t.email_content.subject || '')
        setTf({ ...BLANK_TPL_FIELDS, ...(t.email_content.fields || {}) })
      }
      if (t.channel === 'whatsapp' && t.whatsapp_content) setWa(t.whatsapp_content)
    })
    api.get('/projects').then((r) => setProjects(r.data)).catch(() => {})
  }, [templateId])

  const { getTplValue, setTplField } = useTplFieldAccessors(tf, setTf)

  const runPreview = () => {
    api.post(`/templates/${templateId}/preview`, {}).then((r) => setPreview(r.data)).catch(() => {})
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (tpl) runPreview() }, [tpl, subject, JSON.stringify(tf), JSON.stringify(wa)])

  const previewProject = projects.find((p) => String(p.id) === String(previewProjectId))

  const save = async () => {
    setSaving(true)
    try {
      const payload = { name, description, category_id: categoryId ? Number(categoryId) : null }
      if (tpl.channel === 'email') payload.email_content = { subject, fields: tf }
      if (tpl.channel === 'whatsapp') payload.whatsapp_content = wa
      await api.put(`/templates/${templateId}`, payload)
      toast.ok('Template saved')
      onClose()
    } catch (e) { toast.err(apiError(e)) } finally { setSaving(false) }
  }

  const publish = async () => {
    try { await api.put(`/templates/${templateId}`, { status: 'published' }); toast.ok('Template published'); onClose() }
    catch (e) { toast.err(apiError(e)) }
  }

  if (!tpl) return <Modal title="Loading…" onClose={onClose}><Spinner /></Modal>

  return (
    <Modal title={`Edit template · ${tpl.channel === 'email' ? 'Email' : 'WhatsApp'}`} onClose={onClose} wide
      footer={<>
        <button className="btn btn-ghost" onClick={onClose}>Close</button>
        {canEdit && tpl.status !== 'published' && (
          <button className="btn btn-ghost" onClick={publish}>Save &amp; publish</button>
        )}
        {canEdit && <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>}
      </>}>
      <div className="grid grid-2" style={{ alignItems: 'start' }}>
        <div>
          <div className="row-2">
            <Field label="Name *"><input className="input" value={name} disabled={!canEdit} onChange={(e) => setName(e.target.value)} /></Field>
            <CategoryField categories={categories} value={categoryId} onChange={setCategoryId} onCategoryCreated={onCategoryCreated} />
          </div>
          <Field label="Description"><textarea className="textarea" value={description} disabled={!canEdit} onChange={(e) => setDescription(e.target.value)} /></Field>

          {tpl.channel === 'email' && (
            <>
              <Field label="Subject">
                <input className="input" value={subject} disabled={!canEdit} onChange={(e) => setSubject(e.target.value)}
                  placeholder="Hi {{Name}}, an update from {{Company}}" />
              </Field>
              <TemplateAttachments templateId={templateId} canEdit={canEdit} toast={toast} />
              <TemplateFieldsForm project={previewProject} tf={tf} getTplValue={getTplValue} setTplField={setTplField}
                tplRefs={tplRefs} tplFocused={tplFocused} canEdit={canEdit} />
            </>
          )}

          {tpl.channel === 'whatsapp' && (
            <>
              <p className="hint">Fields must match a template already approved in WhatsApp Business Manager — this is a catalog, not a free-form editor.</p>
              <div className="row-2">
                <Field label="Meta template name *"><input className="input" value={wa.meta_template_name} disabled={!canEdit}
                  onChange={(e) => setWa({ ...wa, meta_template_name: e.target.value })} /></Field>
                <Field label="Meta template ID *"><input className="input" value={wa.meta_template_id} disabled={!canEdit}
                  onChange={(e) => setWa({ ...wa, meta_template_id: e.target.value })} /></Field>
              </div>
              <div className="row-2">
                <Field label="Language code *"><input className="input" value={wa.language_code} disabled={!canEdit}
                  onChange={(e) => setWa({ ...wa, language_code: e.target.value })} placeholder="en_US" /></Field>
                <Field label="Header type">
                  <select className="select" value={wa.header_type} disabled={!canEdit} onChange={(e) => setWa({ ...wa, header_type: e.target.value })}>
                    <option value="none">None</option><option value="text">Text</option>
                    <option value="image">Image</option><option value="document">Document</option>
                  </select>
                </Field>
              </div>
              {wa.header_type !== 'none' && (
                <Field label="Header content"><input className="input" value={wa.header_content} disabled={!canEdit}
                  onChange={(e) => setWa({ ...wa, header_content: e.target.value })} /></Field>
              )}
              <Field label="Body text *" hint="Numbered placeholders ({{1}}, {{2}}…) per the approved Meta template, not {{Name}}-style tokens.">
                <textarea className="textarea" style={{ minHeight: 100 }} value={wa.body_text} disabled={!canEdit}
                  onChange={(e) => setWa({ ...wa, body_text: e.target.value })} />
              </Field>
              <Field label="Footer text"><input className="input" value={wa.footer_text} disabled={!canEdit}
                onChange={(e) => setWa({ ...wa, footer_text: e.target.value })} /></Field>
            </>
          )}
        </div>

        <div className="card" style={{ maxHeight: 620, overflowY: 'auto' }}>
          <div className="card-pad flex between" style={{ paddingBottom: 12 }}>
            <h3 style={{ fontSize: 15 }}>Live preview</h3>
            {tpl.channel === 'email' && (
              <select className="select" style={{ width: 200 }} value={previewProjectId} onChange={(e) => setPreviewProjectId(e.target.value)}>
                <option value="">No branding (blank)</option>
                {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            )}
          </div>
          <div style={{ padding: '0 22px 22px' }}>
            {preview.missing && preview.missing.length > 0 && (
              <div className="hint" style={{ marginBottom: 10, color: 'var(--warn)' }}>
                ⚠ No value found for: {preview.missing.map((m) => `{{${m}}}`).join(', ')} — sent as blank.
              </div>
            )}
            {tpl.channel === 'email' ? (
              <iframe title="Template preview" srcDoc={preview.html || '<body></body>'} sandbox=""
                style={{ width: '100%', height: 520, border: '1px solid var(--border)', borderRadius: 10, background: '#fff' }} />
            ) : (
              <div className="preview">
                <div className="ph"><span>WhatsApp preview</span></div>
                <div className="pb" dangerouslySetInnerHTML={{ __html: preview.html || '<span class="muted">Nothing to preview yet.</span>' }} />
              </div>
            )}
          </div>
        </div>
      </div>
    </Modal>
  )
}
