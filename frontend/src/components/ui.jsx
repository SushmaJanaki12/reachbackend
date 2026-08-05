import { createContext, useContext, useState, useCallback } from 'react'

/* ---------------- Icons (inline SVG, 1.8 stroke) ---------------- */
const I = (p) => ({ width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
  strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', ...p })
export const Icon = {
  dashboard: (p) => <svg {...I(p)}><rect x="3" y="3" width="7" height="9"/><rect x="14" y="3" width="7" height="5"/><rect x="14" y="12" width="7" height="9"/><rect x="3" y="16" width="7" height="5"/></svg>,
  folder: (p) => <svg {...I(p)}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>,
  send: (p) => <svg {...I(p)}><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg>,
  chart: (p) => <svg {...I(p)}><path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/></svg>,
  users: (p) => <svg {...I(p)}><circle cx="9" cy="8" r="3.2"/><path d="M3 20a6 6 0 0 1 12 0"/><path d="M16 5.5a3 3 0 0 1 0 5.5"/><path d="M18 20a6 6 0 0 0-2-4.5"/></svg>,
  shield: (p) => <svg {...I(p)}><path d="M12 3l7 3v5c0 5-3.5 8-7 10-3.5-2-7-5-7-10V6z"/><path d="m9 12 2 2 4-4"/></svg>,
  mail: (p) => <svg {...I(p)}><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>,
  chat: (p) => <svg {...I(p)}><path d="M21 15a2 2 0 0 1-2 2H8l-4 4V5a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2z"/></svg>,
  phone: (p) => <svg {...I(p)}><rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/></svg>,
  plus: (p) => <svg {...I(p)}><path d="M12 5v14M5 12h14"/></svg>,
  upload: (p) => <svg {...I(p)}><path d="M12 15V3"/><path d="m7 8 5-5 5 5"/><path d="M5 15v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"/></svg>,
  download: (p) => <svg {...I(p)}><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>,
  eye: (p) => <svg {...I(p)}><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>,
  check: (p) => <svg {...I(p)}><path d="m20 6-11 11-5-5"/></svg>,
  edit: (p) => <svg {...I(p)}><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>,
  settings: (p) => <svg {...I(p)}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 6.8 19l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 4 13.6H4a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 5.6 6.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.6 1.6 0 0 0 11 4.6V4a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8Z"/></svg>,
  users3: (p) => <svg {...I(p)}><circle cx="12" cy="8" r="3.2"/><path d="M6 21a6 6 0 0 1 12 0"/></svg>,
  trash: (p) => <svg {...I(p)}><path d="M3 6h18"/><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/><path d="M6 6l1 14a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-14"/></svg>,
  userplus: (p) => <svg {...I(p)}><circle cx="9" cy="8" r="3.2"/><path d="M3 20a6 6 0 0 1 12 0"/><path d="M18 8v6M21 11h-6"/></svg>,
  paperclip: (p) => <svg {...I(p)}><path d="M21.44 11.05l-9.19 9.19a5 5 0 0 1-7.07-7.07l9.19-9.19a3.5 3.5 0 0 1 4.95 4.95l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>,
  sparkle: (p) => <svg {...I(p)}><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18"/><circle cx="12" cy="12" r="2.2"/></svg>,
}

/* ---------------- Toast ---------------- */
const ToastCtx = createContext(null)
export function ToastProvider({ children }) {
  const [items, setItems] = useState([])
  const push = useCallback((message, type = 'ok') => {
    const id = Math.random().toString(36).slice(2)
    setItems((s) => [...s, { id, message, type }])
    setTimeout(() => setItems((s) => s.filter((t) => t.id !== id)), 3200)
  }, [])
  return (
    <ToastCtx.Provider value={{ ok: (m) => push(m, 'ok'), err: (m) => push(m, 'err') }}>
      {children}
      <div className="toast-host">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.type}`}>
            {t.type === 'ok' ? <Icon.check width={16} /> : <span>⚠</span>}
            <span>{t.message}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}
export const useToast = () => useContext(ToastCtx)

/* ---------------- Modal ---------------- */
export function Modal({ title, onClose, children, footer, wide }) {
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? 'wide' : ''}`}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="x-btn" onClick={onClose}>&times;</button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  )
}

/* ---------------- Form bits ---------------- */
export function Field({ label, hint, children }) {
  return (
    <div className="field">
      {label && <label>{label}</label>}
      {children}
      {hint && <span className="hint">{hint}</span>}
    </div>
  )
}
export function Toggle({ checked, onChange, label, title, disabled }) {
  return (
    <label className={`toggle${disabled ? ' disabled' : ''}`} title={title}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="track" />
      {label && <span>{label}</span>}
    </label>
  )
}

/* ---------------- Status badge ---------------- */
const STATUS = {
  active: 'green', completed: 'blue', draft: 'gray', inactive: 'amber', archived: 'gray', published: 'green',
  sent: 'teal', delivered: 'green', read: 'green', failed: 'red', pending: 'amber', suppressed: 'gray',
  queued: 'amber', processing: 'teal', sending: 'amber',
}
export function StatusBadge({ status }) {
  const cls = STATUS[status] || 'gray'
  return <span className={`badge ${cls}`}><span className="d" />{status}</span>
}

export function Spinner() { return <div className="center"><div className="spinner" /></div> }
