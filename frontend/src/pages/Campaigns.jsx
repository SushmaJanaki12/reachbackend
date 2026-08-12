import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../components/Layout'
import { useAuth } from '../auth'
import api, { apiError } from '../api'
import { Icon, Modal, Field, StatusBadge, Toggle, Spinner, Pager, useToast } from '../components/ui'

const PAGE_SIZE = 25

export default function Campaigns() {
  const { can } = useAuth()
  const toast = useToast()
  const nav = useNavigate()
  const [projects, setProjects] = useState([])
  const [projectId, setProjectId] = useState('all')   // "all" by default
  const [campaigns, setCampaigns] = useState(null)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [creating, setCreating] = useState(false)

  useEffect(() => { api.get('/projects').then((r) => setProjects(r.data)) }, [])

  const load = () => {
    setCampaigns(null)
    const url = projectId === 'all' ? '/campaigns' : `/projects/${projectId}/campaigns`
    api.get(url, { params: { page, page_size: PAGE_SIZE } })
      .then((r) => { setCampaigns(r.data); setTotal(Number(r.headers['x-total-count']) || r.data.length) })
      .catch(() => { setCampaigns([]); setTotal(0) })
  }
  useEffect(() => { load() }, [projectId, page])

  const remove = async (e, c) => {
    e.stopPropagation()
    if (!window.confirm(`Delete campaign "${c.name}"? This permanently deletes its recipients and content. This cannot be undone.`)) return
    try { await api.delete(`/campaigns/${c.id}`); load(); toast.ok('Campaign deleted') }
    catch (err) { toast.err(apiError(err)) }
  }

  const isAll = projectId === 'all'
  const project = projects.find((p) => String(p.id) === String(projectId))
  const scopeName = isAll ? 'all projects' : project?.name

  return (
    <Layout title="Campaigns" crumb="Workspace / Campaigns">
      <div className="page-head">
        <div>
          <div className="pt">Campaigns</div>
          <div className="ps">Build, personalize and send campaigns under a project.</div>
        </div>
        <div className="flex gap12">
          <select className="select" style={{ width: 240 }} value={projectId}
            onChange={(e) => { setProjectId(e.target.value); setPage(1) }}>
            <option value="all">All projects</option>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          {can('campaign.create') && projects.length > 0 && (
            <button className="btn btn-primary" onClick={() => setCreating(true)}><Icon.plus width={16} /> New campaign</button>
          )}
        </div>
      </div>

      {projects.length === 0 ? (
        <div className="card empty">
          <div className="ico"><Icon.folder width={26} /></div>
          <h3>No projects available</h3>
          <p className="muted">Campaigns live under a project — create one first.</p>
        </div>
      ) : campaigns === null ? <Spinner /> : campaigns.length === 0 ? (
        <div className="card empty">
          <div className="ico"><Icon.send width={24} /></div>
          <h3 style={{ marginBottom: 6 }}>No campaigns in {scopeName}</h3>
          <p className="muted" style={{ marginBottom: 16 }}>Create a campaign to upload recipients and author content.</p>
          {can('campaign.create') && <button className="btn btn-primary" onClick={() => setCreating(true)}><Icon.plus width={16} /> New campaign</button>}
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Campaign</th>{isAll && <th>Project</th>}<th>Recipients</th><th>Channels</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {campaigns.map((c) => (
                <tr key={c.id} style={{ cursor: 'pointer' }} onClick={() => nav(`/campaigns/${c.id}`)}>
                  <td className="t-strong">
                    {c.name}{c.is_test_campaign && <span className="badge amber" style={{ marginLeft: 8 }}><span className="d" />TEST</span>}
                    {c.description && <div className="t-sub">{c.description}</div>}
                  </td>
                  {isAll && <td><span className="badge teal"><span className="d" />{c.project_name}</span></td>}
                  <td>{c.recipient_count}</td>
                  <td>
                    <div className="wrap-gap">
                      {c.email_enabled && <span className="chchip on"><Icon.mail width={12} /> Email</span>}
                      {c.whatsapp_enabled && <span className="chchip on"><Icon.chat width={12} /> WA</span>}
                      {c.sms_enabled && <span className="chchip on"><Icon.phone width={12} /> SMS</span>}
                    </div>
                  </td>
                  <td><StatusBadge status={c.status} /></td>
                  <td style={{ textAlign: 'right' }}>
                    <div className="flex gap8" style={{ justifyContent: 'flex-end', alignItems: 'center' }}>
                      {can('campaign.delete') && (
                        <button className="btn btn-ghost btn-sm" onClick={(e) => remove(e, c)}>
                          <Icon.trash width={13} /> Delete
                        </button>
                      )}
                      <span className="muted">Open →</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {campaigns && campaigns.length > 0 && <Pager page={page} pageSize={PAGE_SIZE} total={total} onPage={setPage} />}

      {creating && (
        <CreateCampaign projects={projects} initialProjectId={isAll ? '' : projectId}
          onClose={() => setCreating(false)}
          onCreated={(c) => { setCreating(false); toast.ok('Campaign created'); nav(`/campaigns/${c.id}`) }}
          onError={(m) => toast.err(m)} />
      )}
    </Layout>
  )
}

function CreateCampaign({ projects, initialProjectId, onClose, onCreated, onError }) {
  const [projectId, setProjectId] = useState(initialProjectId || (projects[0] ? String(projects[0].id) : ''))
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [isTest, setIsTest] = useState(false)
  const [busy, setBusy] = useState(false)
  const save = async () => {
    setBusy(true)
    try {
      const { data } = await api.post('/campaigns', {
        project_id: Number(projectId), name, description, is_test_campaign: isTest,
      })
      onCreated(data)
    } catch (e) { onError(apiError(e)) } finally { setBusy(false) }
  }
  return (
    <Modal title="New campaign" onClose={onClose}
      footer={<>
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={busy || !name || !projectId}>{busy ? 'Creating…' : 'Create'}</button>
      </>}>
      <Field label="Project *">
        <select className="select" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
          <option value="">Select a project</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </Field>
      <Field label="Campaign name *"><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Autumn newsletter" autoFocus /></Field>
      <Field label="Description"><textarea className="textarea" value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
      <Field label="Test campaign"
        hint="Uses synthetic recipients for QA/demo. Unlocks the Simulate tools in Tracking & Reports; cannot be changed after creation.">
        <Toggle checked={isTest} label={isTest ? 'Yes — sandbox campaign' : 'No — real campaign'} onChange={setIsTest} />
      </Field>
    </Modal>
  )
}