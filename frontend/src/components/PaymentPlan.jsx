import React from 'react'

export default function PaymentPlan({ plan, currency, requestedAmount }) {
  if (!plan || plan === 'none') return null
  const legs = plan.split('|').map((leg) => {
    const [date, amount] = leg.split(':')
    return { date, amount: Number(amount) }
  })
  if (legs.length <= 1) return null // single full payment already shown by the gauge/signals

  const total = legs.reduce((s, l) => s + l.amount, 0)
  let running = 0

  return (
    <div className="payment-plan">
      <div className="section-caption">PAYMENT PLAN</div>
      <div className="payment-plan-total">
        Total {currency} {total.toLocaleString(undefined, { maximumFractionDigits: 2 })}
        {requestedAmount ? ` · requested ${currency} ${Number(requestedAmount).toLocaleString(undefined, { maximumFractionDigits: 2 })}` : ''}
      </div>
      <div className="payment-plan-row">
        {legs.map((leg, i) => {
          running += leg.amount
          const remaining = Math.max(0, total - running)
          return (
            <div className="payment-step" key={i}>
              <div className="payment-step-index">PAYMENT {i + 1}</div>
              <div className="payment-step-amount">
                {currency} {leg.amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </div>
              <div className="payment-step-date">{leg.date}</div>
              <div className="payment-step-remaining">
                remaining after: {currency} {remaining.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </div>
              {i < legs.length - 1 && <div className="payment-step-arrow">→</div>}
            </div>
          )
        })}
      </div>
    </div>
  )
}
