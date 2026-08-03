import { useEffect, useState } from 'react'
import api, { apiError } from '../api'
import { Modal, Icon, Spinner } from './ui'

/** "Use a template" button + picker modal for a campaign's Content step.
 * Lists published templates for one channel and, on pick, calls the
 * from-template endpoint to snapshot that template's content into this
 * campaign -- see routers/campaigns.py::set_content_from_template. */
export default function TemplatePicker({ channel, campaignId, canEdit, onApplied, toast }) {
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState(null)
  const [applyingId, setApplyingId] = useState(null)

  useEffect(() => {
    if (!open) return
    setItems(null)
    api.get('/templates', { params: { channel, status: 'published' } })
      .then((r) => setItems(r.data)).catch(() => setItems([]))
  }, [open, channel])

  if (!canEdit) return null

  const apply = async (templateId) => {
    setApplyingId(templateId)
    try {
      await api.post(`/campaigns/${campaignId}/content/${channel}/from-template/${templateId}`)
      toast.ok('Template applied')
      setOpen(false)
      onApplied && onApplied()
    } catch (e) { toast.err(apiError(e)) } finally { setApplyingId(null) }
  }

  return (
    <>
      <button className="btn btn-ghost btn-sm" onClick={() => setOpen(true)}>
        <Icon.folder width={14} /> Use a template
      </button>
      {open && (
        <Modal title={`Use a ${channel} template`} onClose={() => setOpen(false)}>
          {items === null ? <Spinner /> : items.length === 0 ? (
            <p className="muted">No published {channel} templates yet. Create one under Templates.</p>
          ) : (
            <div className="grid" style={{ gap: 8 }}>
              {items.map((t) => (
                <div key={t.id} className="flex between" style={{ padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 9 }}>
                  <div>
                    <div className="t-strong">{t.name}</div>
                    {t.description && <div className="t-sub">{t.description}</div>}
                  </div>
                  <button className="btn btn-primary btn-sm" disabled={applyingId === t.id} onClick={() => apply(t.id)}>
                    {applyingId === t.id ? 'Applying…' : 'Use'}
                  </button>
                </div>
              ))}
            </div>
          )}
        </Modal>
      )}
    </>
  )
}
