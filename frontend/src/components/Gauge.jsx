import React from 'react'

const STATUS_META = {
  affordable_now: { label: 'BUY NOW', color: '#3ddc97', angle: 1.0 },
  affordable_with_plan: { label: 'BUY WITH PLAN', color: '#f2c14e', angle: 0.68 },
  affordable_later: { label: 'WAIT', color: '#f2994a', angle: 0.4 },
  not_affordable: { label: "DON'T PROCEED", color: '#e8514c', angle: 0.12 },
}

export default function Gauge({ status, amountSafe, requestedAmount, currency }) {
  const meta = STATUS_META[status] || STATUS_META.not_affordable
  const radius = 92
  const circumference = 2 * Math.PI * radius
  const pct = Math.max(0, Math.min(1, amountSafe / Math.max(requestedAmount, 1)))
  const dash = circumference * pct
  const coveragePct = Math.round(pct * 100)

  return (
    <div className="gauge">
      <svg width="240" height="240" viewBox="0 0 240 240">
        <circle
          cx="120" cy="120" r={radius}
          fill="none" stroke="#20242b" strokeWidth="10"
        />
        <circle
          cx="120" cy="120" r={radius}
          fill="none" stroke={meta.color} strokeWidth="10"
          strokeDasharray={`${dash} ${circumference}`}
          strokeLinecap="round"
          transform="rotate(-90 120 120)"
          style={{ transition: 'stroke-dasharray 0.6s ease, stroke 0.4s ease' }}
        />
        <text x="120" y="112" textAnchor="middle" className="gauge-pct" fill={meta.color}>
          {coveragePct}%
        </text>
        <text x="120" y="136" textAnchor="middle" className="gauge-sub">
          covered today
        </text>
      </svg>
      <div className="gauge-verdict" style={{ color: meta.color, borderColor: meta.color }}>
        {meta.label}
      </div>
    </div>
  )
}
