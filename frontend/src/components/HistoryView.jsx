import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'

const STATUS_LABEL = {
  affordable_now: 'BUY NOW',
  affordable_with_plan: 'BUY WITH PLAN',
  affordable_later: 'WAIT',
  not_affordable: "DON'T PROCEED",
}

export default function HistoryView() {
  const [history, setHistory] = useState([])
  const [statusFilter, setStatusFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(null)

  const refresh = () => {
    setLoading(true)
    setError(null)
    api.getHistory().then(setHistory).catch((e) => setError(e.message)).finally(() => setLoading(false))
  }

  useEffect(() => { refresh() }, [])

  const filtered = useMemo(() => {
    return history.filter((h) => {
      if (statusFilter !== 'all' && h.affordability_status !== statusFilter) return false
      if (query && !`${h.item} ${h.user_id}`.toLowerCase().includes(query.toLowerCase())) return false
      return true
    })
  }, [history, statusFilter, query])

  if (error) {
    return (
      <div className="form-error">
        <span>Couldn't load history ({error}).</span>
        <button className="form-error-retry" onClick={refresh}>Retry</button>
      </div>
    )
  }

  return (
    <div className="history-view">
      <div className="section-caption">DECISION HISTORY</div>
      <div className="history-controls">
        <input placeholder="Search item or user…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="all">All statuses</option>
          {Object.keys(STATUS_LABEL).map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
        </select>
        <button type="button" onClick={refresh}>{loading ? 'Refreshing…' : 'Refresh'}</button>
      </div>
      {loading && history.length === 0 ? (
        <div className="loading"><span className="spinner" /> Loading history…</div>
      ) : (
        <>
          <table className="history-table">
            <thead>
              <tr>
                <th>Item</th><th>User</th><th>Amount</th><th>Decision</th><th>Method</th><th>Safe amount</th><th>Date</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((h) => (
                <tr key={h.id} onClick={() => setSelected(h)} className="history-row">
                  <td>{h.item}</td>
                  <td>{h.user_id}</td>
                  <td>{h.currency || h.home_currency} {Number(h.amount).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                  <td><span className={`status-pill status-${h.affordability_status}`}>{STATUS_LABEL[h.affordability_status] || h.affordability_status}</span></td>
                  <td>{h.recommended_payment_method}</td>
                  <td>{h.home_currency || h.currency} {Number(h.amount_safe_to_pay).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                  <td>{h.date}</td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr><td colSpan={7} className="history-empty">No decisions match.</td></tr>
              )}
            </tbody>
          </table>
          {selected && (
            <div className="history-detail">
              <div className="history-detail-header">
                <div className="section-caption" style={{ margin: 0, border: 'none', padding: 0 }}>
                  {selected.item} — {selected.user_id}
                </div>
                <button className="history-detail-close" onClick={() => setSelected(null)}>Close ✕</button>
              </div>
              <p className="history-detail-explanation">{selected.decision_explanation}</p>
              <div className="history-detail-grid">
                <div><span>Requested</span>{selected.currency || selected.home_currency} {Number(selected.amount).toLocaleString(undefined, { maximumFractionDigits: 2 })}</div>
                <div><span>Safe to pay</span>{selected.home_currency || selected.currency} {Number(selected.amount_safe_to_pay).toLocaleString(undefined, { maximumFractionDigits: 2 })}</div>
                <div><span>Payment plan</span>{selected.payment_plan && selected.payment_plan !== 'none' ? selected.payment_plan.replace(/\|/g, ' → ') : 'None'}</div>
                <div><span>Earliest full payment</span>{selected.earliest_date_for_full_payment || '—'}</div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
