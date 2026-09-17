import React from 'react'

function fmt(amount, currency) {
  if (amount === null || amount === undefined || amount === '') return '—'
  return `${currency} ${Number(amount).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
}

export default function DecisionTrail({ decision, profile, currency }) {
  if (!decision) return null

  const steps = [
    {
      title: 'Current financial position',
      body: `Balance of ${fmt(profile?.current_available_balance, currency)} as of ${profile?.as_of_date}.`,
    },
    {
      title: 'Essential commitments protected',
      body: `Rent, groceries and other protected categories (${(profile?.protected_categories || []).join(', ') || 'none set'}) are never touched by this decision.`,
    },
    {
      title: 'Upcoming income',
      body: profile?.next_income
        ? `Next confirmed income of ${fmt(profile.next_income.amount, currency)} on ${profile.next_income.date}.`
        : 'No further confirmed income detected in the forecast window.',
    },
    {
      title: 'Upcoming expenses',
      body: `${profile?.upcoming_commitments?.length || 0} recurring/scheduled commitments projected over the next 90 days.`,
    },
    {
      title: 'Minimum balance protection',
      body: `The plan is only recommended if the balance never drops below the protected minimum of ${fmt(profile?.minimum_balance_to_keep, currency)}.`,
    },
    {
      title: 'Payment-plan safety',
      body: decision.payment_plan && decision.payment_plan !== 'none'
        ? `Plan: ${decision.payment_plan.split('|').length} payment(s), independently validated across the full 90-day forecast.`
        : 'No payment plan is safe within the forecast window.',
    },
    {
      title: 'Final recommendation',
      body: decision.decision_explanation,
    },
  ]

  return (
    <div className="decision-trail">
      <div className="section-caption">WHY THIS DECISION?</div>
      <ol className="decision-trail-list">
        {steps.map((s, i) => (
          <li key={i}>
            <span className="decision-trail-num">{i + 1}</span>
            <div>
              <div className="decision-trail-title">{s.title}</div>
              <div className="decision-trail-body">{s.body}</div>
            </div>
          </li>
        ))}
      </ol>
      {decision.spending_changes_needed && decision.spending_changes_needed !== 'none' && (
        <div className="decision-trail-changes">
          Spending changes used in this plan: <code>{decision.spending_changes_needed}</code>
        </div>
      )}
    </div>
  )
}
