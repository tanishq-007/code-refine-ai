import { useMemo, useState } from 'react'
import { AnimatedNumber } from './ui'

export interface DonutSegment {
  label: string
  value: number
  color: string
}

const TAU = Math.PI * 2

function arcPath(cx: number, cy: number, r: number, a0: number, a1: number): string {
  const x0 = cx + r * Math.cos(a0)
  const y0 = cy + r * Math.sin(a0)
  const x1 = cx + r * Math.cos(a1)
  const y1 = cy + r * Math.sin(a1)
  const large = a1 - a0 > Math.PI ? 1 : 0
  return `M ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1}`
}

/** Ring chart with a hero total in the center and 2px surface gaps between
 *  segments. Hovering a segment (or its legend row) highlights it and swaps
 *  the center readout. */
export function Donut({ segments, caption }: { segments: DonutSegment[]; caption: string }) {
  const [hover, setHover] = useState<number | null>(null)
  const total = segments.reduce((s, seg) => s + seg.value, 0)

  const size = 180
  const r = 72
  const stroke = 22
  const cx = size / 2
  const cy = size / 2

  const arcs = useMemo(() => {
    // a 2px gap at radius r, expressed as an angle
    const gap = total > 0 ? 2 / r : 0
    let angle = -Math.PI / 2
    return segments.map(seg => {
      const sweep = total > 0 ? (seg.value / total) * TAU : 0
      const a0 = angle + gap / 2
      const a1 = Math.max(a0, angle + sweep - gap / 2)
      angle += sweep
      return { a0, a1 }
    })
  }, [segments, total, r])

  const active = hover !== null ? segments[hover] : null

  return (
    <div className="flex flex-wrap items-center gap-6">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
        aria-label={`${caption}: ${segments.map(s => `${s.label} ${s.value}`).join(', ')}`}>
        {arcs.map((a, i) => (
          <path
            key={segments[i].label}
            d={arcPath(cx, cy, r, a.a0, a.a1)}
            fill="none"
            stroke={segments[i].color}
            strokeWidth={hover === i ? stroke + 4 : stroke}
            opacity={hover === null || hover === i ? 1 : 0.35}
            style={{ transition: 'stroke-width 150ms ease, opacity 150ms ease' }}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
          >
            <title>{`${segments[i].label}: ${segments[i].value}`}</title>
          </path>
        ))}
        <text x={cx} y={cy - 4} textAnchor="middle"
          style={{ fill: 'var(--text-primary)', fontSize: 28, fontWeight: 600 }}>
          {active ? active.value : <AnimatedNumber value={total} />}
        </text>
        <text x={cx} y={cy + 16} textAnchor="middle"
          style={{ fill: 'var(--text-muted)', fontSize: 11 }}>
          {active ? active.label : caption}
        </text>
      </svg>

      <div className="flex min-w-40 flex-1 flex-col gap-1.5">
        {segments.map((seg, i) => (
          <button
            key={seg.label}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
            className={`flex items-center gap-2 rounded-md px-1.5 py-1 text-left transition-colors duration-150 ${
              hover === i ? 'bg-page' : ''
            }`}
          >
            <span aria-hidden className="size-2.5 shrink-0 rounded-full" style={{ background: seg.color }} />
            <span className="min-w-0 flex-1 truncate text-xs text-ink-2">{seg.label}</span>
            <span className="text-xs tabular-nums text-ink">{seg.value}</span>
            <span className="w-10 text-right text-xs tabular-nums text-ink-3">
              {total > 0 ? `${Math.round((seg.value / total) * 100)}%` : '—'}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
