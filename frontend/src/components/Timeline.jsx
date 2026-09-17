import React, { useMemo } from 'react'

export default function Timeline({ forecast, currency, paymentDates = [] }) {
  const { pathD, points, minKeepY, width, height, lowest, top, bottom } = useMemo(() => {
    if (!forecast?.points?.length) return {}
    const width = 900
    const height = 220
    const padL = 50
    const padR = 20
    const padT = 20
    const padB = 30

    const pts = forecast.points
    const balances = pts.map((p) => p.balance)
    const minKeep = forecast.minimum_balance_to_keep
    const top = Math.max(...balances, minKeep) * 1.08
    const bottom = Math.min(...balances, minKeep) * (Math.min(...balances, minKeep) < 0 ? 1.15 : 0.85)

    const x = (i) => padL + (i / (pts.length - 1)) * (width - padL - padR)
    const y = (v) => padT + (1 - (v - bottom) / (top - bottom || 1)) * (height - padT - padB)

    const pathD = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${x(i).toFixed(1)} ${y(p.balance).toFixed(1)}`).join(' ')
    const lowestIdx = balances.indexOf(Math.min(...balances))
    const lowest = { ...pts[lowestIdx], x: x(lowestIdx), y: y(pts[lowestIdx].balance) }
    const points = pts.map((p, i) => ({ ...p, x: x(i), y: y(p.balance) }))
    const minKeepY = y(minKeep)

    return { pathD, points, minKeepY, width, height, lowest, top, bottom }
  }, [forecast])

  if (!pathD) return <div className="timeline-empty">No forecast data.</div>

  const paymentXs = paymentDates
    .map((d) => points.find((p) => p.date === d))
    .filter(Boolean)

  return (
    <div className="timeline">
      <div className="timeline-caption">90-DAY PROJECTED BALANCE</div>
      <svg viewBox={`0 0 ${width} ${height}`} className="timeline-svg" preserveAspectRatio="none">
        <line x1="50" y1={minKeepY} x2={width - 20} y2={minKeepY} stroke="#e8514c" strokeDasharray="4 4" strokeWidth="1" />
        <text x={width - 22} y={minKeepY - 6} textAnchor="end" className="timeline-minline-label">
          protected minimum
        </text>
        <path d={pathD} fill="none" stroke="#3ddc97" strokeWidth="2" />
        {paymentXs.map((p, i) => (
          <g key={i}>
            <line x1={p.x} y1="20" x2={p.x} y2={height - 30} stroke="#f2c14e" strokeDasharray="3 3" strokeWidth="1" />
            <circle cx={p.x} cy={p.y} r="4" fill="#f2c14e" />
          </g>
        ))}
        <circle cx={lowest.x} cy={lowest.y} r="5" fill="#e8514c" />
        <text x={lowest.x} y={lowest.y - 12} textAnchor="middle" className="timeline-lowest-label">
          lowest: {currency} {Number(lowest.balance).toLocaleString(undefined, { maximumFractionDigits: 0 })}
        </text>
      </svg>
      <div className="timeline-footer">
        <span>{forecast.as_of_date} · today</span>
        <span>+90 days</span>
      </div>
    </div>
  )
}
