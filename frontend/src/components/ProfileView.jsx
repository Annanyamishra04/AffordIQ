import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

function fmt(n, currency) {
  return `${currency} ${Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
}

export default function ProfileView({ userId }) {
  const [profile, setProfile] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    setError(null)
    api.getProfile(userId).then(setProfile).catch((e) => setError(e.message)).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [userId])

  if (error) {
    return (
      <div className="form-error">
        <span>Couldn't load this profile ({error}).</span>
        <button className="form-error-retry" onClick={load}>Retry</button>
      </div>
    )
  }
  if (loading || !profile) return <div className="loading"><span className="spinner" /> Loading profile…</div>

  const currency = profile.home_currency
  const balancePct = Math.min(100, Math.round((profile.minimum_balance_to_keep / Math.max(profile.current_available_balance, 1)) * 100))

  const byCategory = {}
  for (const c of profile.upcoming_commitments) {
    byCategory[c.category] = (byCategory[c.category] || 0) + c.amount
  }
  const maxCat = Math.max(...Object.values(byCategory), 1)

  return (
    <div className="profile-view">
      <div className="section-caption">FINANCIAL PROFILE — {userId}</div>

      <div className="profile-balance-bar">
        <div className="profile-balance-track">
          <div className="profile-balance-min" style={{ width: `${balancePct}%` }} />
        </div>
        <div className="profile-balance-labels">
          <span>Protected minimum: {fmt(profile.minimum_balance_to_keep, currency)}</span>
          <span>Current balance: {fmt(profile.current_available_balance, currency)}</span>
        </div>
      </div>

      <div className="profile-grid">
        <div className="profile-block">
          <div className="profile-block-title">Priorities</div>
          <ul className="tag-list">
            {profile.financial_priorities.map((p) => <li key={p}>{p.replace(/_/g, ' ')}</li>)}
          </ul>
        </div>
        <div className="profile-block">
          <div className="profile-block-title">Protected categories</div>
          <ul className="tag-list protected">
            {profile.protected_categories.map((p) => <li key={p}>{p.replace(/_/g, ' ')}</li>)}
          </ul>
        </div>
        <div className="profile-block">
          <div className="profile-block-title">Flexible — reducible</div>
          <ul className="tag-list flexible">
            {profile.flexible_reduce_categories.map((p) => <li key={p}>{p.replace(/_/g, ' ')}</li>)}
          </ul>
        </div>
        <div className="profile-block">
          <div className="profile-block-title">Flexible — stoppable</div>
          <ul className="tag-list flexible">
            {profile.flexible_stop_categories.map((p) => <li key={p}>{p.replace(/_/g, ' ')}</li>)}
          </ul>
        </div>
        <div className="profile-block">
          <div className="profile-block-title">Payment methods accepted</div>
          <ul className="tag-list">
            {profile.payment_methods_accepted.map((p) => <li key={p}>{p.replace(/_/g, ' ')}</li>)}
          </ul>
        </div>
        <div className="profile-block">
          <div className="profile-block-title">Max installment months</div>
          <div className="profile-block-value">{profile.max_installment_months || 'not accepted'}</div>
        </div>
      </div>

      <div className="section-caption" style={{ marginTop: '2rem' }}>UPCOMING COMMITMENTS BY CATEGORY (90d)</div>
      <div className="category-bars">
        {Object.entries(byCategory).sort((a, b) => b[1] - a[1]).map(([cat, total]) => (
          <div className="category-bar-row" key={cat}>
            <div className="category-bar-label">{cat.replace(/_/g, ' ')}</div>
            <div className="category-bar-track">
              <div className="category-bar-fill" style={{ width: `${(total / maxCat) * 100}%` }} />
            </div>
            <div className="category-bar-value">{fmt(total, currency)}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
