import { useEffect, useState } from 'react'
import Layout from '../components/Layout'
import api, { apiError } from '../api'
import { Icon, Modal, Field, StatusBadge, Toggle, Spinner, Pager, useToast } from '../components/ui'

const SEED_EMAILS = new Set(['admin@reach.io', 'user@reach.io'])
const PAGE_SIZE = 25

export default function Users() {
  const toast = useToast()
  const [users, setUsers] = useState(null)
  const [roles, setRoles] = useState([])
  const [projects, setProjects] = useState([])
  const [editing, setEditing] = useState(null)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)

  const load = () => api.get('/users', { params: { page, page_size: PAGE_SIZE } })
    .then((r) => { setUsers(r.data); setTotal(Number(r.headers['x-total-count']) || r.data.length) })
    .catch(() => { setUsers([]); setTotal(0) })
  useEffect(() => { load() }, [page])
  useEffect(() => {
    api.get('/roles').then((r) => setRoles(r.data))
    api.get('/projects').then((r) => setProjects(r.data)).catch(() => {})
  }, [])

  const toggleActive = async (u) => {
    try { await api.put(`/users/${u.id}`, { is_active: !u.is_active }); load() }
    catch (e) { toast.err(apiError(e)) }
  }

  const remove = async (u) => {
    if (!window.confirm(`Delete user "${u.name}"? This cannot be undone.`)) return
    try { await api.delete(`/users/${u.id}`); load(); toast.ok('User deleted') }
    catch (e) { toast.err(apiError(e)) }
  }

  return (
    <Layout title="Users" crumb="Administration / Users">
      <div className="page-head">
        <div><div className="pt">Users</div><div className="ps">Invite people, assign roles and scope them to projects.</div></div>
        <button className="btn btn-primary" onClick={() => setEditing({ name: '', email: '', password: '', role_id: roles[1]?.id || roles[0]?.id, project_ids: [] })}>
          <Icon.plus width={16} /> Add user
        </button>
      </div>

      {users === null ? <Spinner /> : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Projects</th><th></th></tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td className="t-strong">{u.name}</td>
                  <td>{u.email}</td>
                  <td><span className="badge teal"><span className="d" />{u.role.name}</span></td>
                  <td><StatusBadge status={u.is_active ? 'active' : 'inactive'} /></td>
                  <td className="muted">{u.role.name === 'Admin' ? 'All' : '—'}</td>
                  <td style={{ textAlign: 'right' }}>
                    <div className="flex gap8" style={{ justifyContent: 'flex-end' }}>
                      {!SEED_EMAILS.has(u.email) && (
                        <button className="btn btn-ghost btn-sm" onClick={() => toggleActive(u)}>{u.is_active ? 'Deactivate' : 'Activate'}</button>
                      )}
                      <button className="btn btn-ghost btn-sm" onClick={() => setEditing({ id: u.id, name: u.name, email: u.email, role_id: u.role.id, is_active: u.is_active, password: '', project_ids: [] })}>
                        <Icon.edit width={13} /> Edit
                      </button>
                      {!SEED_EMAILS.has(u.email) && (
                        <button className="btn btn-ghost btn-sm" onClick={() => remove(u)}>
                          <Icon.trash width={13} /> Delete
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {users && users.length > 0 && <Pager page={page} pageSize={PAGE_SIZE} total={total} onPage={setPage} />}

      {editing && (
        <UserModal initial={editing} roles={roles} projects={projects}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); toast.ok('User saved') }}
          onError={(m) => toast.err(m)} />
      )}
    </Layout>
  )
}

function UserModal({ initial, roles, projects, onClose, onSaved, onError }) {
  const isNew = !initial.id
  const [f, setF] = useState(initial)
  const [busy, setBusy] = useState(false)
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }))
  const role = roles.find((r) => r.id === Number(f.role_id))
  const scoped = role && role.name !== 'Admin'
  const isSeed = SEED_EMAILS.has(f.email)

  const save = async () => {
    setBusy(true)
    try {
      if (isNew) await api.post('/users', { name: f.name, email: f.email, password: f.password, role_id: Number(f.role_id), project_ids: f.project_ids })
      else await api.put(`/users/${initial.id}`, { name: f.name, role_id: Number(f.role_id), is_active: f.is_active, ...(f.password ? { password: f.password } : {}), project_ids: f.project_ids })
      onSaved()
    } catch (e) { onError(apiError(e)) } finally { setBusy(false) }
  }

  return (
    <Modal title={isNew ? 'Add user' : `Edit — ${initial.name}`} onClose={onClose}
      footer={<>
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={busy || !f.name || (isNew && (!f.email || !f.password))}>{busy ? 'Saving…' : 'Save'}</button>
      </>}>
      <div className="row-2">
        <Field label="Full name *"><input className="input" value={f.name} onChange={(e) => set('name', e.target.value)} /></Field>
        <Field label="Role *">
          <select className="select" value={f.role_id} onChange={(e) => set('role_id', e.target.value)}>
            {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </Field>
      </div>
      {isNew && (
        <div className="row-2">
          <Field label="Email *"><input className="input" type="email" value={f.email} onChange={(e) => set('email', e.target.value)} /></Field>
          <Field label="Password *"><input className="input" type="password" value={f.password} onChange={(e) => set('password', e.target.value)} /></Field>
        </div>
      )}
      {!isNew && (
        <div className="row-2">
          <Field label="Reset password" hint="Leave blank to keep current"><input className="input" type="password" value={f.password} onChange={(e) => set('password', e.target.value)} placeholder="••••••••" /></Field>
          <Field label="Account" hint={isSeed ? 'Seeded default account — cannot be deactivated' : undefined}>
            <div style={{ paddingTop: 6 }}><Toggle checked={f.is_active} disabled={isSeed} onChange={(v) => set('is_active', v)} label={f.is_active ? 'Active' : 'Deactivated'} /></div>
          </Field>
        </div>
      )}
      {scoped && projects.length > 0 && (
        <Field label="Assigned projects" hint="Users only see and act within assigned projects">
          <div className="grid" style={{ gap: 6, marginTop: 4 }}>
            {projects.map((p) => {
              const on = f.project_ids.includes(p.id)
              return (
                <label key={p.id} className={`perm-item ${on ? 'checked' : ''}`} style={{ justifyContent: 'space-between' }}>
                  <span>{p.name}</span>
                  <input type="checkbox" checked={on} onChange={(e) => set('project_ids', e.target.checked ? [...f.project_ids, p.id] : f.project_ids.filter((x) => x !== p.id))} />
                </label>
              )
            })}
          </div>
        </Field>
      )}
    </Modal>
  )
}
