import React, { useMemo, useRef, useState } from 'react'
import { api } from '../api.js'

const STATUS_LABEL = {
  affordable_now: 'BUY NOW',
  affordable_with_plan: 'BUY WITH PLAN',
  affordable_later: 'WAIT',
  not_affordable: "DON'T PROCEED",
}

const STATUS_COLOR = {
  affordable_now: 'var(--accent)',
  affordable_with_plan: 'var(--amber)',
  affordable_later: 'var(--orange)',
  not_affordable: 'var(--red)',
}

function daysBetween(fromIso, toIso) {
  const ms = new Date(toIso) - new Date(fromIso)
  return Math.max(1, Math.round(ms / 86400000))
}

/**
 * A real scenario tool: the person picks flexible spending changes to try,
 * and every number shown -- the safe-to-pay amount, the affordability
 * status, the recommended plan -- comes back from POST /api/what-if, which
 * runs the same financial engine as the main decision. Nothing here
 * recomputes affordability in JavaScript.
 */
export default function WhatIf({ decision, profile, currency }) {
  const [toggled, setToggled] = useState(() => new Set())
  const [status, setStatus] = useState('idle') // idle | loading | success | error
  const [result, setResult] = useState(null)
  const [errorMessage, setErrorMessage] = useState(null)
  const requestInFlight = useRef(false)

  const flexible = useMemo(() => {
    const stop = new Set(profile?.flexible_stop_categories || [])
    const reduce = new Set(profile?.flexible_reduce_categories || [])
    const byCategory = {}
    for (const item of profile?.upcoming_commitments || []) {
      if (!stop.has(item.category) && !reduce.has(item.category)) continue
      byCategory[item.category] = (byCategory[item.category] || 0) + item.amount
    }
    return Object.entries(byCategory).map(([category, total]) => ({
      category,
      total,
      action: stop.has(category) ? 'stop' : 'reduce',
    }))
  }, [profile])

  if (!flexible.length || !decision) return null

  const toggle = (category) => {
    if (status === 'loading') return
    setToggled((prev) => {
      const next = new Set(prev)
      next.has(category) ? next.delete(category) : next.add(category)
      return next
    })
  }

  const runScenario = async () => {
    if (requestInFlight.current) return // prevent duplicate requests
    requestInFlight.current = true
    setStatus('loading')
    setErrorMessage(null)
    try {
      const changes = flexible
        .filter((f) => toggled.has(f.category))
        .map((f) => ({ category: f.category, action: f.action }))

      const payload = {
        user_id: decision.user_id,
        item: decision.item,
        amount: decision.amount,
        currency: decision.currency,
        days_until_needed: daysBetween(decision.date, decision.desired_completion_date),
        allows_partial_payment: decision.allows_partial_payment,
        changes,
      }
      const body = await api.postWhatIf(payload)
      setResult(body)
      setStatus('success')
    } catch (err) {
      setErrorMessage(err.message)
      setStatus('error')
    } finally {
      requestInFlight.current = false
    }
  }

  const reset = () => {
    setToggled(new Set())
    setResult(null)
    setStatus('idle')
    setErrorMessage(null)
  }

  const fmt = (n) => `${currency} ${Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 })}`

  return (
    <div className="whatif">
      <div className="section-caption">WHAT IF I ADJUSTED MY SPENDING?</div>
      <div className="whatif-note">
        Select flexible expenses to cut, then recalculate — the result comes straight
        from the same engine that produced the recommendation above.
      </div>

      <div className="whatif-chips">
        {flexible.map((f) => (
          <button
            key={f.category}
            type="button"
            className={`whatif-chip ${toggled.has(f.category) ? 'active' : ''}`}
            onClick={() => toggle(f.category)}
            disabled={status === 'loading'}
          >
            <span className="whatif-chip-label">{f.category.replace(/_/g, ' ')}</span>
            <span className="whatif-chip-amount">
              {f.action} · {fmt(f.total)}
            </span>
          </button>
        ))}
      </div>

      <div className="whatif-actions">
        <button
          type="button"
          className="whatif-run"
          onClick={runScenario}
          disabled={toggled.size === 0 || status === 'loading'}
        >
          {status === 'loading'
            ? <><span className="spinner" /> Recalculating…</>
            : 'Recalculate with these changes'}
        </button>
        {(status === 'success' || status === 'error') && (
          <button type="button" className="whatif-reset" onClick={reset}>Reset</button>
        )}
      </div>

      {status === 'error' && (
        <div className="form-error">
          <span>Couldn't recalculate the scenario ({errorMessage}).</span>
          <button type="button" className="form-error-retry" onClick={runScenario}>Retry</button>
        </div>
      )}

      {status === 'success' && result && (
        <WhatIfResult result={result} currency={currency} />
      )}
    </div>
  )
}

function WhatIfResult({ result, currency }) {
  const { scenario, comparison, applied_changes: appliedChanges } = result
  const fmt = (n) => `${currency} ${Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
  const diff = comparison.difference
  const diffSign = diff > 0 ? '+' : diff < 0 ? '−' : ''
  const diffAbs = Math.abs(diff)

  if (!appliedChanges.length) {
    return (
      <div className="whatif-result whatif-result-empty" key="empty">
        None of the selected changes applied to a real upcoming expense in your timeline,
        so the scenario is identical to your current decision.
      </div>
    )
  }

  return (
    <div className="whatif-result" key={JSON.stringify(comparison)}>
      <div className="whatif-compare">
        <div className="whatif-compare-card">
          <div className="whatif-compare-label">CURRENT</div>
          <div className="whatif-compare-amount" style={{ color: STATUS_COLOR[comparison.affordability_status_before] }}>
            {fmt(comparison.amount_safe_to_pay_before)}
          </div>
          <div className="whatif-compare-sub">SAFE TO PAY</div>
          <div
            className="whatif-compare-status"
            style={{ color: STATUS_COLOR[comparison.affordability_status_before], borderColor: STATUS_COLOR[comparison.affordability_status_before] }}
          >
            {STATUS_LABEL[comparison.affordability_status_before] || comparison.affordability_status_before}
          </div>
        </div>

        <div className="whatif-compare-arrow">→</div>

        <div className="whatif-compare-card whatif-compare-card-after">
          <div className="whatif-compare-label">SCENARIO</div>
          <div className="whatif-compare-amount" style={{ color: STATUS_COLOR[comparison.affordability_status_after] }}>
            {fmt(comparison.amount_safe_to_pay_after)}
          </div>
          <div className="whatif-compare-sub">SAFE TO PAY</div>
          <div
            className="whatif-compare-status"
            style={{ color: STATUS_COLOR[comparison.affordability_status_after], borderColor: STATUS_COLOR[comparison.affordability_status_after] }}
          >
            {STATUS_LABEL[comparison.affordability_status_after] || comparison.affordability_status_after}
          </div>
        </div>
      </div>

      <div className={`whatif-diff ${diff > 0 ? 'whatif-diff-up' : diff < 0 ? 'whatif-diff-down' : ''}`}>
        {diff === 0
          ? "No change in headroom — these expenses don't fall before your tightest point in the next 90 days."
          : `${diffSign}${fmt(diffAbs)} headroom`}
      </div>

      {comparison.changed && (
        <div className="whatif-method-change">
          {comparison.recommended_payment_method_before} → {comparison.recommended_payment_method_after}
        </div>
      )}

      <div className="whatif-applied">
        <div className="whatif-applied-label">Applied changes</div>
        <ul>
          {appliedChanges.map((c) => (
            <li key={c.event_id}>
              {c.kind === 'stop' ? 'Stop' : 'Reduce'} {c.category.replace(/_/g, ' ')} — frees {fmt(c.freed_amount)}
            </li>
          ))}
        </ul>
      </div>

      {scenario.payment_plan && scenario.payment_plan !== 'none' && (
        <div className="whatif-plan">
          <span className="whatif-plan-label">Updated payment plan:</span>{' '}
          <span className="whatif-plan-value">
            {scenario.payment_plan.split('|').map((leg) => {
              const [d, amt] = leg.split(':')
              return `${d} · ${fmt(amt)}`
            }).join('  ·  ')}
          </span>
        </div>
      )}
    </div>
  )
}
