import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { Icon } from './ui'
import reachLogo from '../assets/reach-logo-wordmark.png'

const NAV = [
  { to: '/', label: 'Dashboard', icon: 'dashboard', end: true },
  { to: '/projects', label: 'Projects', icon: 'folder', perms: ['project.view'] },
  { to: '/campaigns', label: 'Campaigns', icon: 'send', perms: ['campaign.view'] },
  { to: '/templates', label: 'Templates', icon: 'mail', perms: ['template.view'] },
  { to: '/tracking', label: 'Tracking & Reports', icon: 'chart', perms: ['tracking.view_all', 'tracking.view_own'] },
]
const ADMIN_NAV = [
  { to: '/users', label: 'Users', icon: 'users', perms: ['user.manage'] },
  { to: '/roles', label: 'Roles & Permissions', icon: 'shield', perms: ['role.manage'] },
  { to: '/settings', label: 'Settings', icon: 'settings', perms: ['system.configure', 'project.configure_channels'] },
]

export default function Layout({ children, title, crumb }) {
  const { user, logout, can } = useAuth()
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const initials = (user?.name || '?').split(' ').map((s) => s[0]).slice(0, 2).join('').toUpperCase()

  
  const item = (n) => {
    if (n.perms && !can(...n.perms)) return null
    const Ico = Icon[n.icon]
    return (
      <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
        onClick={() => setOpen(false)}>
        <Ico className="ico" /> {n.label}
      </NavLink>
    )
  }
  const showAdmin = can('user.manage', 'role.manage', 'system.configure', 'project.configure_channels')

  return (
    <div className="app">
      <aside className={`sidebar ${open ? 'open' : ''}`}>
        <div className="sb-logo"><img src={reachLogo} alt="Reach" className="sb-logo-img" /></div>
        <div className="sb-section">Workspace</div>
        {NAV.map(item)}
        {showAdmin && <>
          <div className="sb-section">Administration</div>
          {ADMIN_NAV.map(item)}
        </>}
        <div className="sb-spacer" />
        <div className="sb-user">
          <div className="row">
            <span className="avatar">{initials}</span>
            <div>
              <div className="nm">{user?.name}</div>
              <div className="rl">{user?.role?.name}</div>
            </div>
          </div>
          <button className="logout-btn" onClick={() => { logout(); nav('/login') }}>Sign out</button>
        </div>
      </aside>

      <div className="main">
        <div className="topbar">
          <div>
            {crumb && <div className="crumb">{crumb}</div>}
            <h1>{title}</h1>
          </div>
        </div>
        <div className="content">{children}</div>
      </div>
    </div>
  )
}
