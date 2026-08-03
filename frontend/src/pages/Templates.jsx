import { useEffect, useState } from 'react'
import Layout from '../components/Layout'
import { useAuth } from '../auth'
import api, { apiError } from '../api'
import { Icon, Modal, Field, StatusBadge, Spinner, useToast } from '../components/ui'
import { BLANK_TPL_FIELDS, TemplateFieldsForm, useTplFieldAccessors } from '../components/TemplateFieldsForm'

const CHANNEL_OPTS = [
  { key: 'email', label: 'Email', icon: 'mail' },
  { key: 'whatsapp', label: 'WhatsApp', icon: 'chat' },
  { key: 'sms', label: 'SMS', icon: 'phone' },
]

const BLANK_WA_CONTENT = {
  meta_template_name: '', meta_template_id: '', language_code: 'en_US',
  header_type: 'none', header_content: '', body_text: '', footer_text: '', buttons: [],
}

export default function Templates() {
  const { can } = useAuth()
  const toast = useToast()
  const canEdit = can('template.edit')
  const canArchive = can('template.archive')
  const canDelete = can('template.delete')

  const [items, setItems] = useState(null)
  const [categories, setCategories] = useState([])
  const [channel, setChannel] = useState('all')
  const [status, setStatus] = useState('all')
  const [q, setQ] = useState('')
  const [creating, setCreating] = useState(false)
  const [editingId, setEditingId] = useState(null)

  const load = () => {
    setItems(null)
    const params = {}
    if (channel !== 'all') params.channel = channel
    if (status !== 'all') params.status = status
    if (q) params.q = q
    api.get('/templates', { params }).then((r) => setItems(r.data)).catch(() => setItems([]))
  }
  useEffect(() => { load() }, [channel, status, q])
  useEffect(() => { api.get('/template-categories').then((r) => setCategories(r.data)).catch(() => {}) }, [])

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

  return (
    <Layout title="Templates" crumb="Workspace / Templates">
      <div className="page-head">
        <div>
          <div className="pt">Message templates</div>
          <div className="ps">Reusable Email &amp; WhatsApp content, shared across every project.</div>
        </div>
        {canEdit && (
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
          <p className="muted" style={{ marginBottom: 16 }}>Create a reusable Email or WhatsApp template for your campaigns.</p>
          {canEdit && <button className="btn btn-primary" onClick={() => setCreating(true)}><Icon.plus width={16} /> New template</button>}
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Template</th><th>Channel</th><th>Category</th><th>Status</th><th>Updated</th><th></th></tr></thead>
            <tbody>
              {items.map((t) => {
                const c = CHANNEL_OPTS.find((x) => x.key === t.channel)
                const Ico = c ? Icon[c.icon] : Icon.mail
                const editable = t.channel !== 'sms'
                return (
                  <tr key={t.id}>
                    <td className="t-strong" style={{ cursor: editable ? 'pointer' : 'default' }}
                      onClick={() => editable && setEditingId(t.id)}>
                      {t.name}{t.description && <div className="t-sub">{t.description}</div>}
                    </td>
                    <td><span className="chchip on"><Ico width={12} /> {c?.label || t.channel}</span></td>
                    <td className="muted">{t.category?.name || '—'}</td>
                    <td><StatusBadge status={t.status} /></td>
                    <td className="muted">{t.updated_at ? new Date(t.updated_at).toLocaleDateString() : '—'}</td>
                    <td style={{ textAlign: 'right' }}>
                      <div className="flex gap8" style={{ justifyContent: 'flex-end' }}>
                        {editable && canEdit && (
                          <button className="btn btn-ghost btn-sm" onClick={() => setEditingId(t.id)}><Icon.edit width={13} /></button>
                        )}
                        {editable && canEdit && (
                          <button className="btn btn-ghost btn-sm" onClick={() => duplicate(t)}>Duplicate</button>
                        )}
                        {editable && canArchive && t.status !== 'archived' && (
                          <button className="btn btn-ghost btn-sm" onClick={() => archive(t)}>Archive</button>
                        )}
                        {editable && canArchive && t.status === 'archived' && (
                          <button className="btn btn-ghost btn-sm" onClick={() => restore(t)}>Restore</button>
                        )}
                        {editable && canDelete && (
                          <button className="btn btn-ghost btn-sm" title="Delete" onClick={() => remove(t)}><Icon.trash width={13} /></button>
                        )}
                        {!editable && <span className="t-sub">Manage under Settings → SMS Templates</span>}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {creating && (
        <CreateTemplate categories={categories} onClose={() => setCreating(false)}
          onCreated={(t) => { setCreating(false); load(); setEditingId(t.id) }}
          onError={(m) => toast.err(m)} />
      )}
      {editingId && (
        <TemplateEditor templateId={editingId} categories={categories} canEdit={canEdit}
          onClose={() => { setEditingId(null); load() }} toast={toast} />
      )}
    </Layout>
  )
}

function CreateTemplate({ categories, onClose, onCreated, onError }) {
  const [name, setName] = useState('')
  const [channel, setChannel] = useState('email')
  const [categoryId, setCategoryId] = useState('')
  const [busy, setBusy] = useState(false)

  const save = async () => {
    setBusy(true)
    try {
      const payload = { name, channel, category_id: categoryId ? Number(categoryId) : null }
      if (channel === 'email') payload.email_content = { subject: '', fields: BLANK_TPL_FIELDS }
      if (channel === 'whatsapp') payload.whatsapp_content = BLANK_WA_CONTENT
      const { data } = await api.post('/templates', payload)
      onCreated(data)
    } catch (e) { onError(apiError(e)) } finally { setBusy(false) }
  }

  return (
    <Modal title="New template" onClose={onClose}
      footer={<>
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={busy || !name}>{busy ? 'Creating…' : 'Create'}</button>
      </>}>
      <Field label="Channel *">
        <div className="tabs" style={{ marginBottom: 0 }}>
          {CHANNEL_OPTS.filter((c) => c.key !== 'sms').map((c) => {
            const Ico = Icon[c.icon]
            return <div key={c.key} className={`tab ${channel === c.key ? 'active' : ''}`} onClick={() => setChannel(c.key)}>
              <span className="flex gap8"><Ico width={14} /> {c.label}</span>
            </div>
          })}
        </div>
      </Field>
      <Field label="Template name *"><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Welcome email" autoFocus /></Field>
      <Field label="Category">
        <select className="select" value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
          <option value="">No category</option>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </Field>
    </Modal>
  )
}

function TemplateEditor({ templateId, categories, canEdit, onClose, toast }) {
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
            <Field label="Category">
              <select className="select" value={categoryId} disabled={!canEdit} onChange={(e) => setCategoryId(e.target.value)}>
                <option value="">No category</option>
                {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Field>
          </div>
          <Field label="Description"><textarea className="textarea" value={description} disabled={!canEdit} onChange={(e) => setDescription(e.target.value)} /></Field>

          {tpl.channel === 'email' && (
            <>
              <Field label="Subject">
                <input className="input" value={subject} disabled={!canEdit} onChange={(e) => setSubject(e.target.value)}
                  placeholder="Hi {{Name}}, an update from {{Company}}" />
              </Field>
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
