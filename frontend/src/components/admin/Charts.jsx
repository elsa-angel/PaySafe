import { CHART_COLORS } from '../../utils/chartColors'
import { formatCompact } from '../../utils/format'

/* Small dependency-free SVG charts drawn with the PaySafe palette. */

const W = 640
const H = 240
const PAD = { top: 14, right: 14, bottom: 30, left: 46 }
const PLOT_W = W - PAD.left - PAD.right
const PLOT_H = H - PAD.top - PAD.bottom

/** Axis maximum. Count charts use whole-number ticks (a multiple of 4, so 5 ticks are evenly spaced integers). */
function axisMax(value, integer) {
  if (integer) return Math.max(4, Math.ceil(value / 4) * 4)
  return niceMax(value)
}

function niceMax(value) {
  if (value <= 0) return 1
  const magnitude = 10 ** Math.floor(Math.log10(value))
  const step = [1, 2, 5, 10].find((candidate) => candidate * magnitude >= value)
  return step * magnitude
}

function Axes({ points, max, formatTick }) {
  const ticks = [0, 0.25, 0.5, 0.75, 1]
  const labelEvery = Math.max(1, Math.ceil(points.length / 6))
  const slot = PLOT_W / points.length
  return (
    <g className="chart__axes">
      {ticks.map((fraction) => {
        const y = PAD.top + PLOT_H * (1 - fraction)
        return (
          <g key={fraction}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y} y2={y} className="chart__grid" />
            <text x={PAD.left - 8} y={y + 4} textAnchor="end" className="chart__tick">
              {formatTick(max * fraction)}
            </text>
          </g>
        )
      })}
      {points.map((point, index) =>
        index % labelEvery === 0 ? (
          <text key={point.label + index} x={PAD.left + slot * (index + 0.5)} y={H - 8} textAnchor="middle" className="chart__tick">
            {point.label}
          </text>
        ) : null,
      )}
    </g>
  )
}

/** points: [{ label, value, tooltip }] */
export function BarChart({ points, color = CHART_COLORS.blue, formatValue = formatCompact, integer = false, ariaLabel }) {
  const max = axisMax(Math.max(...points.map((p) => p.value), 0), integer)
  const slot = PLOT_W / points.length
  const barWidth = Math.max(Math.min(slot * 0.62, 36), 1.5)
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ariaLabel}>
      <Axes points={points} max={max} formatTick={formatValue} />
      {points.map((point, index) => {
        const height = (point.value / max) * PLOT_H
        const x = PAD.left + slot * index + (slot - barWidth) / 2
        return (
          <rect key={point.label + index} x={x} y={PAD.top + PLOT_H - height} width={barWidth} height={Math.max(height, point.value > 0 ? 1.5 : 0)} rx={Math.min(4, barWidth / 2)} fill={color}>
            <title>{point.tooltip}</title>
          </rect>
        )
      })}
    </svg>
  )
}

export function LineChart({ points, color = CHART_COLORS.blue, formatValue = formatCompact, integer = false, ariaLabel }) {
  const max = axisMax(Math.max(...points.map((p) => p.value), 0), integer)
  const slot = PLOT_W / points.length
  const coords = points.map((point, index) => [
    PAD.left + slot * (index + 0.5),
    PAD.top + PLOT_H - (point.value / max) * PLOT_H,
  ])
  const line = coords.map(([x, y]) => `${x},${y}`).join(' ')
  const baseline = PAD.top + PLOT_H
  const area = `${coords[0][0]},${baseline} ${line} ${coords[coords.length - 1][0]},${baseline}`
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ariaLabel}>
      <Axes points={points} max={max} formatTick={formatValue} />
      <polygon points={area} fill={color} opacity="0.12" />
      <polyline points={line} fill="none" stroke={color} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
      {coords.map(([x, y], index) => (
        <circle key={points[index].label + index} cx={x} cy={y} r={points.length > 60 ? 2 : 4} fill="#fff" stroke={color} strokeWidth="2">
          <title>{points[index].tooltip}</title>
        </circle>
      ))}
    </svg>
  )
}

/** segments: [{ label, value, color }] */
export function DonutChart({ segments, centerLabel = 'Total' }) {
  const total = segments.reduce((sum, segment) => sum + segment.value, 0)
  const radius = 15.9155 // circumference 100
  const arcs = segments.map((segment, index) => {
    const share = (segment.value / total) * 100
    const before = segments.slice(0, index).reduce((sum, other) => sum + (other.value / total) * 100, 0)
    return { ...segment, share, offset: 25 - before }
  })
  return (
    <div className="donut">
      <svg viewBox="0 0 42 42" className="donut__svg" role="img" aria-label={`${centerLabel}: ${total}`}>
        <circle cx="21" cy="21" r={radius} fill="none" stroke="var(--field-bg)" strokeWidth="5" />
        {arcs.filter((arc) => arc.value > 0).map((arc) => (
          <circle key={arc.label} cx="21" cy="21" r={radius} fill="none" stroke={arc.color} strokeWidth="5"
            strokeDasharray={`${arc.share} ${100 - arc.share}`} strokeDashoffset={arc.offset}>
            <title>{`${arc.label}: ${arc.value}`}</title>
          </circle>
        ))}
        <text x="21" y="21.5" textAnchor="middle" className="donut__total">{total}</text>
        <text x="21" y="26.5" textAnchor="middle" className="donut__caption">{centerLabel}</text>
      </svg>
      <ul className="legend">
        {segments.map((segment) => (
          <li key={segment.label}>
            <span className="legend__dot" style={{ background: segment.color }} />
            <span className="legend__label">{segment.label}</span>
            <strong>{segment.value}</strong>
            <span className="legend__pct">{total ? `${Math.round((segment.value / total) * 100)}%` : '0%'}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** rows: [{ label, value, display }] */
export function HBars({ rows, color = CHART_COLORS.blue }) {
  const max = Math.max(...rows.map((row) => row.value), 0)
  return (
    <ul className="hbars">
      {rows.map((row) => (
        <li key={row.label}>
          <span className="hbars__label">{row.label}</span>
          <span className="hbars__track">
            <span className="hbars__fill" style={{ width: `${max ? (row.value / max) * 100 : 0}%`, background: color }} />
          </span>
          <strong className="hbars__value">{row.display ?? row.value}</strong>
        </li>
      ))}
    </ul>
  )
}
