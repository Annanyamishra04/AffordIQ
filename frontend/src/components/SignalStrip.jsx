import React from 'react'

function fmt(amount, currency) {
  if (amount === null || amount === undefined || amount === '') return '—'
  const n = Number(amount)
  return `${currency} ${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
}

export default function SignalStrip({ decision, profile, currency }) {
  const items = [
    { label: 'SAFE TO SPEND', value: fmt(decision?.amount_safe_to_pay, currency) },
    { label: 'CURRENT BALANCE', value: fmt(profile?.current_available_balance, currency) },
    { label: 'PROTECTED MINIMUM', value: fmt(profile?.minimum_balance_to_keep, currency) },
    {
      label: 'NEXT INCOME',
      value: profile?.next_income
        ? `${fmt(profile.next_income.amount, currency)} · ${profile.next_income.date}`
        : '—',
    },
    {
      label: 'UPCOMING COMMITMENTS',
      value: profile?.upcoming_commitments?.length
        ? `${profile.upcoming_commitments.length} in next 90d`
        : '0',
    },
  ]

  return (
    <div className="signal-strip">
      {items.map((it, i) => (
        <React.Fragment key={it.label}>
          <div className="signal">
            <div className="signal-label">{it.label}</div>
            <div className="signal-value">{it.value}</div>
          </div>
          {i < items.length - 1 && <div className="signal-divider" />}
        </React.Fragment>
      ))}
    </div>
  )
}
