import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import Layout from '../components/Layout'
import { useAuth } from '../auth'
import api, { apiError } from '../api'
import { Icon, StatusBadge, Spinner, useToast } from '../components/ui'

const TABS = [
  { key: 'email', label: 'Email', icon: 'mail' },
  { key: 'whatsapp', label: 'WhatsApp', icon: 'chat' },
  { key: 'sms', label: 'SMS', icon: 'phone' },
]

function fmt(dt) {
  if (!dt) return '—'
  // Backend sends naive UTC timestamps (no trailing Z/offset). Without one,
  // `new Date()` parses ISO date-times as local time instead of UTC, so tag
  // them explicitly as UTC here; toLocaleString then converts to whatever
  // timezone the browser is actually in.
  const iso = /Z$|[+-]\d\d:?\d\d$/.test(dt) ? dt : `${dt}Z`
  const d = new Date(iso)
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export default function Tracking() {
  const { can } = useAuth()
  const toast = useToast()
  const loc = useLocation()
  const [projects, setProjects] = useState([])
  const [projectId, setProjectId] = useState('')
  const [campaigns, setCampaigns] = useState([])
  const [campaignId, setCampaignId] = useState(loc.state?.campaignId || '')
  const [tab, setTab] = useState('email')
  const [stepFilter, setStepFilter] = useState(loc.state?.stepId ?? null)
  const [summary, setSummary] = useState(null)
  const [rows, setRows] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [sendRuns, setSendRuns] = useState([])
  // 'current' (default -- the most recent send), 'all' (every send blended
  // together), or a specific past run_number -- a resend archives rather
  // than overwrites a campaign's prior Message rows (see
  // app/campaign_resend.py), so older sends stay independently viewable
  // here instead of being silently replaced.
  const [run, setRun] = useState('current')
  const summaryRef = useRef(null)

  useEffect(() => { api.get('/projects').then((r) => { setProjects(r.data); if (r.data.length && !projectId) setProjectId(String(r.data[0].id)) }) }, [])
  useEffect(() => {
    if (!projectId) return
    api.get(`/projects/${projectId}/campaigns`).then((r) => {
      setCampaigns(r.data)
      if (r.data.length && !r.data.find((c) => String(c.id) === String(campaignId))) setCampaignId(String(r.data[0].id))
    })
  }, [projectId])

  useEffect(() => {
    if (!campaignId) { setSendRuns([]); return }
    api.get(`/campaigns/${campaignId}/send-runs`).then((r) => setSendRuns(r.data)).catch(() => setSendRuns([]))
  }, [campaignId])
  // A campaign switch (or a resend landing a new run) should default back to
  // "current" rather than staying pinned to whatever run was picked before.
  useEffect(() => { setRun('current') }, [campaignId])

  const loadCampaign = () => {
    if (!campaignId) { setSummary(null); setRows([]); return }
    return api.get(`/campaigns/${campaignId}/summary`, { params: { run } }).then((r) => {
      summaryRef.current = r.data
      setSummary(r.data)
      setLastUpdated(new Date())
    }).catch(() => setSummary(null))
  }
  useEffect(() => { loadCampaign() }, [campaignId, run])

  useEffect(() => {
    if (!campaignId) return
    setRows(null)

    const loadTracking = () => {
      api.get(`/campaigns/${campaignId}/tracking/${tab}`, { params: { run } })
        .then((r) => { setRows(r.data); setLastUpdated(new Date()) })
        .catch(() => setRows([]))
    }
    loadTracking()

    // Poll while the campaign is actively sending so status updates show up
    // without a manual page refresh; stop once the backend marks it complete.
    // Only the current run can still be "sending" -- a past/blended view
    // never needs to poll.
    const interval = setInterval(() => {
      if (run !== 'current' || summaryRef.current?.status !== 'sending') { clearInterval(interval); return }
      loadCampaign()
      loadTracking()
    }, 4000)

    return () => clearInterval(interval)
  }, [campaignId, tab, run])

  const activeCampaign = campaigns.find((c) => String(c.id) === String(campaignId))
  // Simulate writes directly to real engagement fields (opened_at/clicked_at/
  // reply_sentiment) that also drive live follow-up trigger logic -- gated
  // server-side (routers/followups.py::simulate_event) to test campaigns
  // only; hidden here too so it's not offered somewhere it'll just 403.
  // Simulate writes onto live Message rows, so it only makes sense while
  // looking at the current run -- a past/blended view is read-only history.
  const canSimulate = can('content.edit') && !!activeCampaign?.is_test_campaign && run === 'current'

  // Stands in for real engagement capture -- there's no tracking pixel,
  // click redirect, or inbound reply webhook yet, so this is how the
  // follow-up engine (Campaigns -> Follow-ups tab) gets tested/demoed today.
  const simulateEvent = async (messageId, event) => {
    let reply_text
    if (event === 'replied') {
      reply_text = window.prompt('Simulate a reply — enter the reply text (used for sentiment classification):', 'Yes, interested!')
      if (reply_text === null) return
    }
    try {
      await api.post(`/campaigns/${campaignId}/followups/messages/${messageId}/simulate`, { event, reply_text })
      const { data } = await api.get(`/campaigns/${campaignId}/tracking/${tab}`, { params: { run } })
      setRows(data)
      toast.ok(`Simulated: ${event}`)
    } catch (e) { toast.err(apiError(e)) }
  }

  const exportCsv = async () => {
    try {
      const res = await api.get(`/campaigns/${campaignId}/report.csv`, { params: { run }, responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url; a.download = `campaign_${campaignId}_report.csv`; a.click()
      URL.revokeObjectURL(url)
    } catch (e) { toast.err(apiError(e)) }
  }

  const visibleRows = rows && stepFilter != null ? rows.filter((m) => m.step_id === stepFilter) : (rows || [])

  const stats = summary ? [
    { k: 'Recipients', v: summary.total_recipients, tone: '', icon: 'users' },
    { k: 'Messages', v: summary.total_messages, tone: 'info', icon: 'send' },
    { k: 'Delivered', v: summary.delivered + summary.email_sent, tone: 'good', icon: 'check' },
    { k: 'Failed', v: summary.failed, tone: 'amber', icon: 'shield' },
  ] : []

  return (
    <Layout title="Tracking & Reports" crumb="Workspace / Tracking">
      <div className="page-head">
        <div>
          <div className="pt flex gap8" style={{ alignItems: 'center' }}>
            Tracking &amp; Reports
            {activeCampaign?.is_test_campaign && (
              <span className="badge amber" title="Synthetic recipients — excluded from dashboard analytics">
                <span className="d" />TEST CAMPAIGN
              </span>
            )}
          </div>
          <div className="ps">Real-time delivery status across every channel.</div>
        </div>
        <div className="flex gap12 wrap-gap">
          <select className="select" style={{ width: 200 }} value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <select className="select" style={{ width: 220 }} value={campaignId}
            onChange={(e) => { setCampaignId(e.target.value); setStepFilter(null) }}>
            {campaigns.length === 0 && <option value="">No campaigns</option>}
            {campaigns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          {campaignId && sendRuns.length > 1 && (
            <select className="select" style={{ width: 180 }} value={run} title="This campaign has been resent -- pick which send to view"
              onChange={(e) => setRun(e.target.value)}>
              <option value="current">Latest send (#{sendRuns[sendRuns.length - 1].run_number})</option>
              {sendRuns.slice(0, -1).reverse().map((r) => (
                <option key={r.run_number} value={r.run_number}>Send #{r.run_number}</option>
              ))}
              <option value="all">All sends</option>
            </select>
          )}
          {can('report.export') && campaignId && summary?.total_messages > 0 && (
            <button className="btn btn-ghost" onClick={exportCsv}><Icon.download width={15} /> Export CSV</button>
          )}
        </div>
      </div>

      {!campaignId ? (
        <div className="card empty"><div className="ico"><Icon.chart width={24} /></div><h3>Select a campaign</h3><p className="muted">Choose a project and campaign to view tracking.</p></div>
      ) : !summary ? <Spinner /> : summary.total_messages === 0 ? (
        <div className="card empty"><div className="ico"><Icon.send width={24} /></div><h3>Not sent yet</h3><p className="muted">This campaign hasn't been dispatched. Send it to see delivery tracking.</p></div>
      ) : (
        <>
          <div className="grid grid-4" style={{ marginBottom: 20 }}>
            {stats.map((s) => {
              const Ico = Icon[s.icon]
              return <div key={s.k} className={`stat ${s.tone}`}>
                <div className="flex between"><div className="k">{s.k}</div><span className="ico"><Ico width={18} /></span></div>
                <div className="v">{s.v}</div>
              </div>
            })}
          </div>

          <div className="card card-pad" style={{ marginBottom: 20 }}>
            <div className="flex between wrap-gap">
              <div className="flex gap12 wrap-gap">
                <MiniStat label="Email sent" value={summary.email_sent} icon="mail" />
                <MiniStat label="WhatsApp sent" value={summary.whatsapp_sent} icon="chat" />
                <MiniStat label="SMS sent" value={summary.sms_sent} icon="phone" />
                <MiniStat label="Pending" value={summary.pending} icon="settings" />
                <MiniStat label="Suppressed" value={summary.suppressed} icon="shield" />
              </div>
              <div className="flex gap12" style={{ alignItems: 'center' }}>
                {summary.status === 'sending' && (
                  <span className="flex gap8" style={{ alignItems: 'center', fontSize: 12, color: 'var(--teal)' }}>
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--teal)', display: 'inline-block' }} />
                    Live — updating every few seconds
                  </span>
                )}
                {lastUpdated && <span className="t-sub" style={{ fontSize: 12 }}>Updated {lastUpdated.toLocaleTimeString()}</span>}
                <StatusBadge status={summary.status} />
              </div>
            </div>
          </div>

          <div className="tabs">
            {TABS.map((t) => {
              const Ico = Icon[t.icon]
              return <div key={t.key} className={`tab ${tab === t.key ? 'active' : ''}`} onClick={() => setTab(t.key)}>
                <span className="flex gap8"><Ico width={14} /> {t.label}</span>
              </div>
            })}
          </div>

          {stepFilter != null && (
            <div className="flex gap8" style={{ alignItems: 'center', margin: '12px 0' }}>
              <span className="badge blue"><span className="d" />Filtered to follow-up step</span>
              <button className="btn btn-ghost btn-sm" onClick={() => setStepFilter(null)}>Clear filter</button>
            </div>
          )}

          {tab === 'email' && (
            <p className="t-sub" style={{ margin: '10px 0' }} title="Open tracking uses a 1x1 pixel image, so it can only ever undercount, never overcount actual reads.">
              "Opened" is a lower bound, not an exact count — Gmail caches the tracking image server-side (a
              second real open by the same recipient may not register), Apple Mail Privacy Protection
              pre-fetches it for every message automatically regardless of whether it's actually read, and
              plain-text clients or images-blocked-by-default recipients never trigger it at all.
            </p>
          )}

          {rows === null ? <Spinner /> : visibleRows.length === 0 ? (
            <div className="card empty" style={{ padding: '40px 20px' }}>
              <p className="muted">{stepFilter != null ? 'No messages for this follow-up step.' : `No ${tab} messages for this campaign.`}</p>
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Recipient</th><th>{tab === 'email' ? 'Email' : 'Mobile'}</th><th>Status</th>
                    {tab === 'whatsapp' && <th>Read</th>}
                    {tab === 'email' && <th>Engagement</th>}
                    <th>Sent</th><th>Failure reason</th>
                    {tab === 'email' && canSimulate && <th style={{ width: 150 }}>Simulate</th>}
                  </tr>
                </thead>
                <tbody>
                  {visibleRows.map((m) => (
                    <tr key={m.id}>
                      <td className="t-strong">{m.recipient_name || '—'}</td>
                      <td>{m.to_address || '—'}</td>
                      <td><StatusBadge status={m.status} /></td>
                      {tab === 'whatsapp' && <td>{m.read_at ? <span className="badge green"><span className="d" />read</span> : <span className="muted">—</span>}</td>}
                      {tab === 'email' && (
                        <td>
                          <div className="flex gap8" style={{ flexWrap: 'wrap' }}>
                            {m.opened_at && <span className="badge blue"><span className="d" />opened</span>}
                            {m.clicked_at && <span className="badge teal"><span className="d" />clicked</span>}
                            {m.reply_sentiment && (
                              <span className={`badge ${m.reply_sentiment === 'interested' ? 'green' : m.reply_sentiment === 'not_interested' ? 'red' : 'gray'}`}>
                                <span className="d" />{m.reply_sentiment.replace('_', ' ')}
                              </span>
                            )}
                            {m.engagement_source === 'simulated' && (
                              <span className="badge gray" title="Written via Simulate, not real recipient activity — excluded from reporting rollups">
                                <span className="d" />simulated
                              </span>
                            )}
                            {!m.opened_at && !m.clicked_at && !m.reply_sentiment && <span className="muted">—</span>}
                          </div>
                        </td>
                      )}
                      <td className="muted">{fmt(m.sent_at)}</td>
                      <td className="muted">
                        {m.error || (m.warnings ? <span style={{ color: 'var(--warn)' }}>⚠ missing: {m.warnings}</span> : '—')}
                      </td>
                      {tab === 'email' && canSimulate && (
                        <td>
                          {m.sent_at ? (
                            <div className="flex gap8">
                              <button className="btn btn-ghost btn-sm" title="Simulate an open (testing aid — no live tracking pixel yet)"
                                onClick={() => simulateEvent(m.id, 'opened')}>Open</button>
                              <button className="btn btn-ghost btn-sm" title="Simulate a click" onClick={() => simulateEvent(m.id, 'clicked')}>Click</button>
                              <button className="btn btn-ghost btn-sm" title="Simulate a reply" onClick={() => simulateEvent(m.id, 'replied')}>Reply</button>
                            </div>
                          ) : <span className="muted">—</span>}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Layout>
  )
}

function MiniStat({ label, value, icon }) {
  const Ico = Icon[icon]
  return (
    <div className="flex gap8" style={{ padding: '4px 12px 4px 4px' }}>
      <span className="ico" style={{ width: 34, height: 34, borderRadius: 9, background: 'var(--teal-soft)', color: 'var(--teal)', display: 'grid', placeItems: 'center' }}><Ico width={16} /></span>
      <div><div style={{ fontWeight: 750, fontSize: 18, lineHeight: 1 }}>{value}</div><div className="t-sub">{label}</div></div>
    </div>
  )
}
