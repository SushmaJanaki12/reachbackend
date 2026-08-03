import { useEffect, useState } from 'react'
import Layout from '../components/Layout'
import api, { apiError } from '../api'
import { Icon, Modal, Field, Spinner, useToast } from '../components/ui'

export default function Roles() {
  const toast = useToast()
  const [roles, setRoles] = useState(null)
  const [permissions, setPermissions] = useState([])
  const [editing, setEditing] = useState(null)

  const load = () => api.get('/roles').then((r) => setRoles(r.data)).catch(() => setRoles([]))
  useEffect(() => {
    load()
    api.get('/permissions').then((r) => setPermissions(r.data))
  }, [])

  const remove = async (r) => {
    if (!window.confirm(`Delete role "${r.name}"? This cannot be undone.`)) return
    try { await api.delete(`/roles/${r.id}`); load(); toast.ok('Role deleted') }
    catch (e) { toast.err(apiError(e)) }
  }

  const modules = [...new Set(permissions.map((p) => p.module))]

  return (
    <Layout title="Roles & Permissions" crumb="Administration / Roles">
      <div className="page-head">
        <div><div className="pt">Roles &amp; Permissions</div><div className="ps">Define what each role can do. Custom roles are built from the permission catalog.</div></div>
        <button className="btn btn-primary" onClick={() => setEditing({ name: '', description: '', permission_codes: [] })}>
          <Icon.plus width={16} /> New role
        </button>
      </div>

      {roles === null ? <Spinner /> : (
        <div className="grid grid-3">
          {roles.map((r) => (
            <div key={r.id} className="card card-pad" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div className="flex between">
                <span className="ico" style={{ width: 42, height: 42, borderRadius: 11, background: r.name === 'Admin' ? 'var(--amber-soft)' : 'var(--teal-soft)', color: r.name === 'Admin' ? 'var(--amber)' : 'var(--teal)', display: 'grid', placeItems: 'center' }}>
                  <Icon.shield width={20} />
                </span>
                {r.is_system && <span className="badge gray"><span className="d" />system</span>}
              </div>
              <div>
                <div style={{ fontWeight: 700, fontSize: 16 }}>{r.name}</div>
                <div className="t-sub">{r.description}</div>
              </div>
              <div className="flex between mt8" style={{ borderTop: '1px solid var(--border)', paddingTop: 12 }}>
                <span className="t-sub">{r.permissions.length} permission{r.permissions.length !== 1 ? 's' : ''}</span>
                <div className="flex gap8">
                  {r.name !== 'Admin' && (
                    <button className="btn btn-ghost btn-sm" onClick={() => setEditing({ id: r.id, name: r.name, description: r.description, permission_codes: r.permissions.map((p) => p.code) })}>
                      <Icon.edit width={13} /> Edit
                    </button>
                  )}
                  {!r.is_system && (
                    <button className="btn btn-ghost btn-sm" onClick={() => remove(r)}>
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
        <RoleModal initial={editing} modules={modules} permissions={permissions}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); toast.ok('Role saved') }}
          onError={(m) => toast.err(m)} />
      )}
    </Layout>
  )
}

function RoleModal({ initial, modules, permissions, onClose, onSaved, onError }) {
  const isNew = !initial.id
  const [f, setF] = useState(initial)
  const [busy, setBusy] = useState(false)
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }))

  const toggle = (code) => set('permission_codes', f.permission_codes.includes(code)
    ? f.permission_codes.filter((c) => c !== code) : [...f.permission_codes, code])

  const save = async () => {
    setBusy(true)
    try {
      const payload = { name: f.name, description: f.description, permission_codes: f.permission_codes }
      if (isNew) await api.post('/roles', payload)
      else await api.put(`/roles/${initial.id}`, payload)
      onSaved()
    } catch (e) { onError(apiError(e)) } finally { setBusy(false) }
  }

  return (
    <Modal wide title={isNew ? 'New role' : `Edit role — ${initial.name}`} onClose={onClose}
      footer={<>
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={busy || !f.name}>{busy ? 'Saving…' : 'Save role'}</button>
      </>}>
      <div className="row-2">
        <Field label="Role name *"><input className="input" value={f.name} onChange={(e) => set('name', e.target.value)} disabled={!isNew} /></Field>
        <Field label="Description"><input className="input" value={f.description} onChange={(e) => set('description', e.target.value)} /></Field>
      </div>
      <div className="field"><label>Permissions ({f.permission_codes.length} selected)</label></div>
      <div className="perm-grid">
        {modules.map((mod) => (
          <div key={mod} className="perm-mod">
            <div className="mh">{mod}</div>
            <div className="perm-list">
              {permissions.filter((p) => p.module === mod).map((p) => {
                const on = f.permission_codes.includes(p.code)
                return (
                  <div key={p.code} className={`perm-item ${on ? 'checked' : ''}`} onClick={() => toggle(p.code)}>
                    <span style={{ width: 16, height: 16, borderRadius: 5, display: 'grid', placeItems: 'center', border: on ? 'none' : '1.5px solid var(--border-strong)', background: on ? 'var(--teal)' : 'transparent', color: '#fff' }}>
                      {on && <Icon.check width={11} />}
                    </span>
                    {p.label}
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </Modal>
  )
}
