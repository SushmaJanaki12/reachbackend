import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../components/Layout'
import { useAuth } from '../auth'
import api from '../api'
import { Icon, Spinner, StatusBadge } from '../components/ui'

/* ── validated data-viz colors ── */
const CH = {
  email: { label: 'Email', color: '#2a78d6', icon: 'mail' },
  whatsapp: { label: 'WhatsApp', color: '#1baf7a', icon: 'chat' },
  sms: { label: 'SMS', color: '#4a3aa7', icon: 'phone' },
}
const DELIV = {
  success: { label: 'Delivered', color: '#0ca30c' },
  failed: { label: 'Failed', color: '#d03b3b' },
  pending: { label: 'Pending', color: '#fab219' },
}
const CAMP = {
  draft: { label: 'Draft', color: '#94a3b8' },
  active: { label: 'Active', color: '#0F766E' },
  sending: { label: 'Sending', color: '#d97706' },
  completed: { label: 'Completed', color: '#2a78d6' },
}

/* ── Donut (SVG stroke segments, 2px gaps, hover) ── */
function Donut({ data, centerBig, centerLab }) {
  const total = data.reduce((a, d) => a + d.value, 0)
  const [hover, setHover] = useState(null)
  const size = 168, sw = 24, r = (size - sw) / 2, C = 2 * Math.PI * r
  const gap = total > 0 ? 2 : 0
  let acc = 0
  const nonzero = data.filter((d) => d.value > 0)

  const shown = hover != null ? nonzero[hover] : null
  const big = shown ? shown.value : centerBig
  const lab = shown ? shown.label : centerLab

  return (
    <div className="donut-wrap" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth={sw} />
        {total > 0 && nonzero.map((d, i) => {
          const frac = d.value / total
          const len = Math.max(frac * C - gap, 0.001)
          const off = acc
          acc += frac * C
          return (
            <circle key={d.label} className="donut-seg" cx={size / 2} cy={size / 2} r={r} fill="none"
              stroke={d.color} strokeWidth={sw} strokeLinecap="round"
              strokeDasharray={`${len} ${C - len}`} strokeDashoffset={-off}
              style={{ opacity: hover == null || hover === i ? 1 : 0.35, cursor: 'pointer' }}
              onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
          )
        })}
      </svg>
      <div className="donut-center">
        <div className="big">{big}{centerLab === 'Success' && !shown ? '%' : ''}</div>
        <div className="lab">{lab}</div>
      </div>
    </div>
  )
}

function Tile({ tone, icon, k, v, sub, subIcon }) {
  const Ico = Icon[icon]
  const SubIco = subIcon ? Icon[subIcon] : null
  return (
    <div className={`tile tile-${tone}`}>
      <span className="glow" />
      <span className="tico"><Ico width={20} /></span>
      <div className="tk">{k}</div>
      <div>
        <div className="tv">{v}</div>
        {sub && <div className="tsub">{SubIco && <SubIco width={12} />}{sub}</div>}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const { user, can } = useAuth()
  const nav = useNavigate()
  const [d, setD] = useState(null)

  useEffect(() => { api.get('/dashboard/overview').then((r) => setD(r.data)).catch(() => setD(false)) }, [])

  if (d === null) return <Layout title="Dashboard"><Spinner /></Layout>
  if (d === false) return <Layout title="Dashboard"><div className="empty">Couldn't load dashboard.</div></Layout>

  const t = d.totals
  const hour = new Date().getHours()
  const greet = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'

  const delivData = Object.entries(d.delivery).map(([k, value]) => ({ ...DELIV[k], value }))
  const chMax = Math.max(1, ...Object.values(d.by_channel))
  const campTotal = Object.values(d.campaign_status).reduce((a, b) => a + b, 0)
  const topMax = Math.max(1, ...d.top_campaigns.map((c) => c.recipients))

  return (
    <Layout title="Dashboard" crumb="Home">
      <div className="page-head">
        <div>
          <div className="pt">{greet}, {user.name.split(' ')[0]} 👋</div>
          <div className="ps">Here's what's happening across your Reach workspace.</div>
        </div>
        {can('project.create') && (
          <button className="btn btn-primary" onClick={() => nav('/projects')}>
            <Icon.plus width={16} /> New project
          </button>
        )}
      </div>

      {/* colorful stat tiles */}
      <div className="grid grid-4" style={{ marginBottom: 20 }}>
        <Tile tone="teal" icon="folder" k="Projects" v={t.projects}
          sub={`${t.projects_active} active`} subIcon="check" />
        <Tile tone="indigo" icon="send" k="Campaigns" v={t.campaigns}
          sub={`${d.campaign_status.completed} completed`} />
        <Tile tone="violet" icon="users" k="Recipients reached" v={t.recipients.toLocaleString()}
          sub="across all campaigns" />
        <Tile tone="green" icon="check" k="Messages sent" v={t.messages_sent.toLocaleString()}
          sub={`${t.success_rate}% success rate`} />
      </div>

      {/* charts row */}
      <div className="grid grid-3" style={{ marginBottom: 20 }}>
        {/* Delivery donut */}
        <div className="chart-card">
          <h3>Delivery outcomes</h3>
          <div className="chart-sub">{t.messages} messages processed</div>
          <div style={{ display: 'flex', justifyContent: 'center', margin: '10px 0 16px' }}>
            <Donut data={delivData} centerBig={t.success_rate} centerLab="Success" />
          </div>
          <div className="grid" style={{ gap: 9 }}>
            {delivData.map((s) => (
              <div key={s.label} className="lg">
                <span className="dot" style={{ background: s.color }} />{s.label}
                <span className="val">{s.value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Channel bars */}
        <div className="chart-card">
          <h3>Messages by channel</h3>
          <div className="chart-sub">Successfully sent per channel</div>
          <div className="grid" style={{ gap: 16, marginTop: 18 }}>
            {Object.entries(d.by_channel).map(([k, v]) => {
              const c = CH[k]; const Ico = Icon[c.icon]
              return (
                <div key={k} className="hrow" title={`${c.label}: ${v}`}>
                  <span className="lg" style={{ gap: 7 }}><Ico width={15} style={{ color: c.color }} /> {c.label}</span>
                  <div className="hbar-track"><div className="hbar-fill" style={{ width: `${(v / chMax) * 100}%`, background: c.color }} /></div>
                  <span className="hval" style={{ color: c.color }}>{v}</span>
                </div>
              )
            })}
          </div>
          <div style={{ marginTop: 22, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
            <div className="chart-sub" style={{ marginBottom: 8, fontWeight: 600 }}>Campaign status</div>
            <div className="seg-bar" title="Campaign status split">
              {Object.entries(d.campaign_status).map(([k, v]) => v > 0 && (
                <div key={k} className="seg" style={{ width: `${(v / campTotal) * 100}%`, background: CAMP[k].color }} title={`${CAMP[k].label}: ${v}`} />
              ))}
            </div>
            <div className="wrap-gap" style={{ marginTop: 10, gap: 14 }}>
              {Object.entries(d.campaign_status).map(([k, v]) => (
                <span key={k} className="lg" style={{ gap: 6 }}>
                  <span className="dot" style={{ background: CAMP[k].color }} />{CAMP[k].label}
                  <b style={{ marginLeft: 2 }}>{v}</b>
                </span>
              ))}
            </div>
          </div>
        </div>

        {/* Top campaigns */}
        <div className="chart-card">
          <h3>Top campaigns</h3>
          <div className="chart-sub">By recipients reached</div>
          {d.top_campaigns.length === 0 ? (
            <div className="empty" style={{ padding: '30px 10px' }}><p className="muted">No campaigns yet.</p></div>
          ) : (
            <div style={{ marginTop: 8 }}>
              {d.top_campaigns.map((c, i) => (
                <div key={c.id} className="rank" style={{ cursor: 'pointer' }} onClick={() => nav('/tracking', { state: { campaignId: c.id } })}>
                  <span className="n">{i + 1}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="flex between">
                      <span className="t-strong" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.name}</span>
                      <span className="hval">{c.recipients}</span>
                    </div>
                    <div className="bar" style={{ width: `${(c.recipients / topMax) * 100}%` }} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* recent projects + quick actions */}
      <div className="grid grid-2">
        <div className="card">
          <div className="card-pad flex between">
            <h3 style={{ fontSize: 16 }}>Recent projects</h3>
            <a onClick={() => nav('/projects')} style={{ cursor: 'pointer', fontSize: 13 }}>View all →</a>
          </div>
          {d.recent_projects.length === 0 ? (
            <div className="empty" style={{ padding: '30px 20px' }}><div className="ico"><Icon.folder width={26} /></div>No projects yet.</div>
          ) : (
            <div className="table-wrap" style={{ border: 'none', borderRadius: 0, boxShadow: 'none' }}>
              <table>
                <thead><tr><th>Project</th><th>Campaigns</th><th>Status</th></tr></thead>
                <tbody>
                  {d.recent_projects.map((p) => (
                    <tr key={p.id} style={{ cursor: 'pointer' }} onClick={() => nav('/campaigns')}>
                      <td className="t-strong">{p.name}<div className="t-sub">{p.email}</div></td>
                      <td>{p.campaign_count}</td>
                      <td><StatusBadge status={p.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card card-pad">
          <h3 style={{ fontSize: 16, marginBottom: 6 }}>Quick actions</h3>
          <p className="muted" style={{ fontSize: 13, marginBottom: 16 }}>Jump straight into your workflow.</p>
          <div className="grid" style={{ gap: 10 }}>
            <QA icon="folder" tone="#0F766E" label="Manage projects" desc="Create & configure client projects" onClick={() => nav('/projects')} show={can('project.view')} />
            <QA icon="send" tone="#2a4fd6" label="Build a campaign" desc="Upload data, write content, send" onClick={() => nav('/campaigns')} show={can('campaign.view')} />
            <QA icon="chart" tone="#0ca30c" label="Tracking & reports" desc="Delivery status and exports" onClick={() => nav('/tracking')} show={can('tracking.view_all', 'tracking.view_own')} />
            <QA icon="users" tone="#8b5cf6" label="Manage users" desc="Invite people and assign roles" onClick={() => nav('/users')} show={can('user.manage')} />
          </div>
        </div>
      </div>
    </Layout>
  )
}

function QA({ icon, tone, label, desc, onClick, show }) {
  if (!show) return null
  const Ico = Icon[icon]
  return (
    <button className="btn btn-ghost" style={{ justifyContent: 'flex-start', padding: 14, textAlign: 'left' }} onClick={onClick}>
      <span style={{ background: `${tone}18`, color: tone, width: 38, height: 38, borderRadius: 10, display: 'grid', placeItems: 'center', flex: 'none' }}>
        <Ico width={18} />
      </span>
      <span>
        <div style={{ fontWeight: 650 }}>{label}</div>
        <div className="t-sub">{desc}</div>
      </span>
    </button>
  )
}