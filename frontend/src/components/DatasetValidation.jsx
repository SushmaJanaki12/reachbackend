import { useEffect, useState } from 'react'
import api, { apiError } from '../api'
import { Icon } from './ui'

const FIELD_LABELS = {
  name: 'Name', first_name: 'First Name', last_name: 'Last Name', email: 'Email',
  mobile: 'Mobile', company: 'Company', job_title: 'Job Title', city: 'City',
  state: 'State', country: 'Country',
}

const BREAKDOWN_LABELS = {
  valid_email: 'Valid emails', duplicate_rate: 'No duplicates', missing_mandatory: 'Mandatory fields present',
  invalid_phone: 'Valid phone numbers', personalization_readiness: 'Personalization ready',
}

const sevClass = (sev) => ({ error: 'red', warning: 'amber', duplicate: 'gray' }[sev] || 'gray')
const scoreColor = (label) => ({
  Excellent: 'var(--good)', Good: 'var(--good)', 'Needs Attention': 'var(--warn)', Poor: 'var(--danger)',
}[label] || 'var(--muted)')
const barColor = (v) => (v >= 80 ? 'var(--good)' : v >= 50 ? 'var(--warn)' : 'var(--danger)')

export function ValidationPanel({ campaignId, session, setSession, canEdit, canOverrideWarnings, toast, onImported, onCancel }) {
  const [pendingMapping, setPendingMapping] = useState(session.column_mapping)
  const [selectedFixIds, setSelectedFixIds] = useState(new Set())
  const [confirming, setConfirming] = useState(false)
  const [applyingFixes, setApplyingFixes] = useState(false)
  const [importing, setImporting] = useState(false)

  useEffect(() => { setPendingMapping(session.column_mapping); setSelectedFixIds(new Set()) }, [session.id])

  const { summary, quality_score: score, issues, mapping_suggestions: suggestions, target_fields: targetFields } = session

  const confirmMapping = async () => {
    setConfirming(true)
    try {
      const { data } = await api.post(`/campaigns/${campaignId}/dataset/validate/${session.id}/mapping`,
        { column_mapping: pendingMapping })
      setSession(data)
      toast.ok('Column mapping confirmed')
    } catch (e) { toast.err(apiError(e)) } finally { setConfirming(false) }
  }

  const applyFixes = async (all) => {
    setApplyingFixes(true)
    try {
      const { data } = await api.post(`/campaigns/${campaignId}/dataset/validate/${session.id}/fixes`,
        all ? { accept_all: true } : { fix_ids: [...selectedFixIds] })
      setSession(data)
      setSelectedFixIds(new Set())
      toast.ok('Fixes applied — score updated')
    } catch (e) { toast.err(apiError(e)) } finally { setApplyingFixes(false) }
  }

  const toggleFix = (fixId) => setSelectedFixIds((s) => {
    const next = new Set(s)
    if (next.has(fixId)) next.delete(fixId); else next.add(fixId)
    return next
  })

  const doImport = async (mode) => {
    setImporting(true)
    try {
      const { data } = await api.post(`/campaigns/${campaignId}/dataset/validate/${session.id}/import`, { mode })
      onImported(data)
    } catch (e) { toast.err(apiError(e)) } finally { setImporting(false) }
  }

  const cancel = async () => {
    try { await api.delete(`/campaigns/${campaignId}/dataset/validate/${session.id}`) } catch { /* best-effort */ }
    onCancel()
  }

  const downloadReport = async () => {
    try {
      const res = await api.get(`/campaigns/${campaignId}/dataset/validate/${session.id}/report`, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url; a.download = 'validation-report.csv'
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
    } catch { toast.err('Failed to download report') }
  }

  const fixableCount = issues.filter((i) => i.suggested_fix).length

  return (
    <div className="card card-pad" style={{ marginBottom: 20 }}>
      <div className="flex between">
        <div>
          <div style={{ fontWeight: 700 }}>Validation report — {session.original_filename}</div>
          <div className="t-sub">
            {summary.total_rows} row{summary.total_rows !== 1 ? 's' : ''} parsed
            {summary.empty_rows_skipped > 0 ? ` · ${summary.empty_rows_skipped} empty row(s) skipped` : ''}
          </div>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={cancel}>Cancel</button>
      </div>

      {session.encoding_warning && (
        <p className="hint" style={{ color: 'var(--warn)', marginTop: 10 }}>
          ⚠ This file wasn't UTF-8 — it was read using a fallback encoding. Double-check special characters, or re-export as UTF-8.
        </p>
      )}

      <div style={{ marginTop: 18 }}>
        <div className="flex between" style={{ marginBottom: 8 }}>
          <span className="t-sub">Column mapping</span>
          <span className={`badge ${session.mapping_confirmed ? 'green' : 'amber'}`}>
            <span className="d" />{session.mapping_confirmed ? 'Confirmed' : 'Needs confirmation'}
          </span>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Source column</th><th>Maps to</th><th>Sample values</th></tr></thead>
            <tbody>
              {suggestions.map((s) => (
                <tr key={s.header}>
                  <td className="t-strong">{s.header}</td>
                  <td>
                    <select className="select" disabled={!canEdit} value={pendingMapping[s.header] || ''}
                      onChange={(e) => setPendingMapping((m) => ({ ...m, [s.header]: e.target.value || null }))}>
                      <option value="">— Keep as custom field —</option>
                      {targetFields.map((f) => <option key={f} value={f}>{FIELD_LABELS[f] || f}</option>)}
                    </select>
                  </td>
                  <td className="muted">{s.sample_values.join(', ') || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex" style={{ justifyContent: 'flex-end', marginTop: 8 }}>
          <button className="btn btn-primary btn-sm" disabled={!canEdit || confirming} onClick={confirmMapping}>
            {confirming ? 'Confirming…' : session.mapping_confirmed ? 'Re-confirm mapping' : 'Confirm mapping'}
          </button>
        </div>
      </div>

      <div className="flex gap12" style={{ marginTop: 22, alignItems: 'center' }}>
        <div style={{ textAlign: 'center', minWidth: 70 }}>
          <div style={{ fontSize: 32, fontWeight: 800, color: scoreColor(score.label), lineHeight: 1 }}>{score.overall}</div>
          <div className="t-sub" style={{ marginTop: 4 }}>{score.label}</div>
        </div>
        <div style={{ flex: 1 }}>
          {Object.entries(score.breakdown).map(([k, v]) => (
            <div key={k} style={{ marginBottom: 7 }}>
              <div className="flex between" style={{ fontSize: 12 }}>
                <span className="muted">{BREAKDOWN_LABELS[k] || k}</span><span>{v}%</span>
              </div>
              <div style={{ height: 6, borderRadius: 4, background: 'var(--border)', overflow: 'hidden' }}>
                <div style={{ height: 6, borderRadius: 4, width: `${v}%`, background: barColor(v) }} />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="wrap-gap" style={{ marginTop: 18 }}>
        <span className="badge teal"><span className="d" />{summary.total_rows} total</span>
        <span className="badge green"><span className="d" />{summary.valid_rows} valid</span>
        <span className="badge red"><span className="d" />{summary.invalid_rows} error{summary.invalid_rows !== 1 ? 's' : ''}</span>
        <span className="badge amber"><span className="d" />{summary.warning_rows} warning{summary.warning_rows !== 1 ? 's' : ''}</span>
        <span className="badge gray"><span className="d" />{summary.duplicate_rows} duplicate{summary.duplicate_rows !== 1 ? 's' : ''}</span>
      </div>

      {issues.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <div className="flex between wrap-gap">
            <span className="t-sub">Issues ({issues.length})</span>
            <div className="flex gap8">
              <button className="btn btn-ghost btn-sm" disabled={!canEdit || applyingFixes || fixableCount === 0}
                onClick={() => applyFixes(true)}>Accept all fixes ({fixableCount})</button>
              <button className="btn btn-ghost btn-sm" disabled={!canEdit || applyingFixes || selectedFixIds.size === 0}
                onClick={() => applyFixes(false)}>Apply selected ({selectedFixIds.size})</button>
            </div>
          </div>
          <div className="table-wrap" style={{ maxHeight: 340, overflowY: 'auto', marginTop: 8 }}>
            <table>
              <thead><tr><th></th><th>Row</th><th>Severity</th><th>Issue</th><th>Description</th><th>Suggested fix</th></tr></thead>
              <tbody>
                {issues.slice(0, 200).map((i) => (
                  <tr key={i.fix_id}>
                    <td>
                      {i.suggested_fix && (
                        <input type="checkbox" checked={selectedFixIds.has(i.fix_id)}
                          onChange={() => toggleFix(i.fix_id)} disabled={!canEdit} />
                      )}
                    </td>
                    <td>{i.row_number}</td>
                    <td><span className={`badge ${sevClass(i.severity)}`}><span className="d" />{i.severity}</span></td>
                    <td className="muted">{i.issue_type}</td>
                    <td>{i.description}</td>
                    <td className="t-strong">{i.suggested_fix || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {issues.length > 200 && <p className="t-sub mt8">Showing first 200 of {issues.length} — download the full report below.</p>}
        </div>
      )}

      <div className="flex gap8 wrap-gap" style={{ marginTop: 22, justifyContent: 'flex-end' }}>
        <button className="btn btn-ghost" onClick={downloadReport}><Icon.download width={15} /> Download error report</button>
        {canOverrideWarnings && summary.warning_rows > 0 && (
          <button className="btn btn-amber" disabled={!canEdit || importing || !session.mapping_confirmed}
            onClick={() => doImport('ignore_warnings')} title="Force-import rows with warnings too (logged for audit)">
            Ignore warnings & import ({summary.ready_for_import_with_overrides})
          </button>
        )}
        <button className="btn btn-primary" disabled={!canEdit || importing || !session.mapping_confirmed || summary.ready_for_import === 0}
          onClick={() => doImport('valid_only')}>
          {importing ? 'Importing…' : `Import valid records (${summary.ready_for_import})`}
        </button>
      </div>
      {!session.mapping_confirmed && <p className="hint" style={{ marginTop: 8, textAlign: 'right' }}>Confirm the column mapping above before importing.</p>}
    </div>
  )
}
