import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import Gauge from './Gauge.jsx'
import SignalStrip from './SignalStrip.jsx'
import Timeline from './Timeline.jsx'
import PaymentPlan from './PaymentPlan.jsx'
import WhatIf from './WhatIf.jsx'
import DecisionTrail from './DecisionTrail.jsx'

export default function DecideView({ userId }) {
  const [profile, setProfile] = useState(null)
  const [forecast, setForecast] = useState(null)
  const [decision, setDecision] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [initialLoading, setInitialLoading] = useState(true)

  const [form, setForm] = useState({
    item: 'Laptop',
    amount: 900,
    currency: 'USD',
    description: '',
    daysUntilNeeded: 30,
    allowsPartial: true,
  })

  const loadUserData = () => {
    setInitialLoading(true)
    setLoadError(null)
    Promise.all([api.getProfile(userId), api.getForecast(userId)])
      .then(([p, f]) => { setProfile(p); setForecast(f) })
      .catch((e) => setLoadError(e.message))
      .finally(() => setInitialLoading(false))
  }

  useEffect(() => {
    setDecision(null)
    loadUserData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId])

  useEffect(() => {
    if (profile) setForm((f) => ({ ...f, currency: profile.home_currency }))
  }, [profile?.home_currency])

  const submit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const result = await api.postDecision({
        user_id: userId,
        item: form.item,
        amount: Number(form.amount),
        currency: form.currency,
        description: form.description,
        days_until_needed: Number(form.daysUntilNeeded),
        allows_partial_payment: form.allowsPartial,
      })
      setDecision(result)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const currency = decision?.home_currency || profile?.home_currency || form.currency

  if (initialLoading) {
    return <div className="loading"><span className="spinner" /> Loading your financial position…</div>
  }

  if (loadError) {
    return (
      <div className="form-error">
        <span>Couldn't load your financial position ({loadError}).</span>
        <button className="form-error-retry" onClick={loadUserData}>Retry</button>
      </div>
    )
  }

  return (
    <div className="decide-view">
      <form className="expense-form" onSubmit={submit}>
        <div className="expense-form-title">Can I safely buy this?</div>
        <div className="expense-form-grid">
          <label>
            Item
            <input value={form.item} onChange={(e) => setForm({ ...form, item: e.target.value })} required />
          </label>
          <label>
            Amount
            <input
              type="number" min="0.01" step="0.01" value={form.amount}
              onChange={(e) => setForm({ ...form, amount: e.target.value })} required
            />
          </label>
          <label>
            Currency
            <select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>
              {['USD', 'EUR', 'INR', 'ZAR', 'IDR'].map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label>
            Needed within (days)
            <input
              type="number" min="1" max="90" value={form.daysUntilNeeded}
              onChange={(e) => setForm({ ...form, daysUntilNeeded: e.target.value })}
            />
          </label>
          <label className="expense-form-wide">
            Description (optional)
            <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </label>
          <label className="expense-form-checkbox">
            <input
              type="checkbox" checked={form.allowsPartial}
              onChange={(e) => setForm({ ...form, allowsPartial: e.target.checked })}
            />
            Allow partial payment
          </label>
        </div>
        <button type="submit" disabled={loading}>
          {loading ? <><span className="spinner" /> Checking your financial position…</> : 'Evaluate'}
        </button>
        {error && (
          <div className="form-error">
            <span>We couldn't complete the affordability check ({error}).</span>
            <button type="button" className="form-error-retry" onClick={(e) => submit(e)}>Retry</button>
          </div>
        )}
      </form>

      {decision && (
        <div className="result-composed">
          <div className="result-top">
            <Gauge
              status={decision.affordability_status}
              amountSafe={Number(decision.amount_safe_to_pay)}
              requestedAmount={decision.amount_in_home_currency}
              currency={currency}
            />
            <SignalStrip decision={decision} profile={profile} currency={currency} />
          </div>

          {forecast && (
            <Timeline
              forecast={forecast}
              currency={currency}
              paymentDates={(decision.payment_plan !== 'none' ? decision.payment_plan.split('|') : []).map((l) => l.split(':')[0])}
            />
          )}

          <PaymentPlan plan={decision.payment_plan} currency={currency} requestedAmount={decision.amount_in_home_currency} />

          <WhatIf decision={decision} profile={profile} currency={currency} />

          <DecisionTrail decision={decision} profile={profile} currency={currency} />
        </div>
      )}
    </div>
  )
}
