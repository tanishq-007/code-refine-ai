import { useMemo, useState, type ReactNode } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer,
  Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from 'recharts'
import { Link } from 'react-router-dom'
import { useRepo } from '../lib/store'
import { AnimatedNumber, Card, EmptyState, StatTile } from '../components/ui'
import { Donut, type DonutSegment } from '../components/Donut'
import { fixStatus, tierOf, TIER_META, typeLabel, type Tier } from '../lib/types'

/* Categorical slots for the donut, in fixed palette order; the folded
   "Other" tail is always neutral gray, never a hue. */
const DONUT_COLORS = [
  'var(--series-1)', 'var(--series-2)', 'var(--series-3)',
  'var(--series-4)', 'var(--series-5)',
]

const TIER_COLOR: Record<Tier, string> = {
  'do-now': 'var(--series-1)',
  plan: 'var(--series-2)',
  backlog: 'var(--series-3)',
}

function ChartTooltip({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-edge bg-surface px-3 py-2 text-xs shadow-sm">
      {children}
    </div>
  )
}

/* Card with a chart/table twin toggle — the table is the WCAG-clean view. */
function VizCard({ title, subtitle, chart, table }: {
  title: string; subtitle?: string; chart: ReactNode; table: ReactNode
}) {
  const [mode, setMode] = useState<'chart' | 'table'>('chart')
  return (
    <Card title={title} subtitle={subtitle} className="relative">
      <div className="absolute right-4 top-4 flex rounded-lg border border-edge text-xs">
        {(['chart', 'table'] as const).map(m => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-2.5 py-1 capitalize first:rounded-l-lg last:rounded-r-lg ${
              mode === m ? 'bg-page font-medium text-ink' : 'text-ink-3 hover:text-ink-2'
            }`}
          >
            {m}
          </button>
        ))}
      </div>
      {mode === 'chart' ? chart : table}
    </Card>
  )
}

function CountTable({ rows, nameHeader }: { rows: [string, number][]; nameHeader: string }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-edge text-left text-xs text-ink-3">
          <th className="py-1.5 font-medium">{nameHeader}</th>
          <th className="py-1.5 text-right font-medium">Findings</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([name, n]) => (
          <tr key={name} className="border-b border-edge last:border-0">
            <td className="py-1.5 text-ink-2">{name}</td>
            <td className="py-1.5 text-right tabular-nums text-ink">{n}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function OverviewPage() {
  const { findings, scored, fixes, info } = useRepo()

  const byType = useMemo(() => {
    const m = new Map<string, number>()
    for (const f of findings) m.set(f.type, (m.get(f.type) ?? 0) + 1)
    return [...m.entries()].sort((a, b) => b[1] - a[1])
  }, [findings])

  const donutSegments = useMemo<DonutSegment[]>(() => {
    const top = byType.slice(0, DONUT_COLORS.length).map(([type, count], i) => ({
      label: typeLabel(type), value: count, color: DONUT_COLORS[i],
    }))
    const rest = byType.slice(DONUT_COLORS.length).reduce((s, [, n]) => s + n, 0)
    if (rest > 0) top.push({ label: 'other', value: rest, color: 'var(--baseline)' })
    return top
  }, [byType])

  const byFile = useMemo(() => {
    const m = new Map<string, number>()
    for (const f of findings) m.set(f.file, (m.get(f.file) ?? 0) + 1)
    return [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10)
  }, [findings])

  /* Aggregate scored findings onto the integer (effort, impact) grid so the
     scatter doesn't overplot; each cell is a bubble sized by count. */
  const grid = useMemo(() => {
    const m = new Map<string, { impact: number; effort: number; count: number; tier: Tier }>()
    for (const s of scored) {
      const key = `${s.effort}:${s.impact}`
      const cell = m.get(key)
      if (cell) cell.count += 1
      else m.set(key, { impact: s.impact, effort: s.effort, count: 1, tier: tierOf(s.impact, s.ratio) })
    }
    return [...m.values()]
  }, [scored])

  const fixList = Object.values(fixes)
  const verified = fixList.filter(f => fixStatus(f) === 'verified').length

  const typeChartHeight = byType.length * 30 + 40 // rows + x-axis band

  if (findings.length === 0) {
    return (
      <EmptyState
        title="No findings for this repo yet"
        hint={<>Run a scan from the <Link className="underline" to="/run">Run pipeline</Link> page to populate the dashboard.</>}
      />
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile label="Total findings" value={findings.length}
          detail={`across ${new Set(findings.map(f => f.file)).size} files`} />
        <StatTile label="Finding types" value={byType.length}
          detail={byType[0] ? `most common: ${typeLabel(byType[0][0])}` : undefined} />
        <StatTile label="Scored" value={scored.length}
          detail={scored.length ? 'impact / effort via LLM' : 'run score or full pipeline'} />
        <StatTile label="Fixes verified"
          value={fixList.length
            ? <><AnimatedNumber value={verified} />/<AnimatedNumber value={fixList.length} /></>
            : '—'}
          detail={fixList.length ? 'tests pass, not rejected' : 'run the full pipeline'} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <VizCard
          title="Debt share"
          subtitle="how the findings split across categories"
          chart={<Donut segments={donutSegments} caption="total findings" />}
          table={<CountTable nameHeader="Type" rows={donutSegments.map(s => [s.label, s.value])} />}
        />

        <VizCard
          title="Findings by type"
          subtitle="count per debt category"
          chart={
            <ResponsiveContainer width="100%" height={typeChartHeight}>
              <BarChart data={byType.map(([type, count]) => ({ type, count }))}
                layout="vertical" margin={{ left: 8, right: 40, top: 4, bottom: 4 }}>
                <CartesianGrid horizontal={false} stroke="var(--grid)" strokeWidth={1} />
                <XAxis type="number" tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                  axisLine={{ stroke: 'var(--baseline)' }} tickLine={false} allowDecimals={false} />
                <YAxis type="category" dataKey="type" width={128}
                  tickFormatter={typeLabel}
                  tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
                  axisLine={{ stroke: 'var(--baseline)' }} tickLine={false} />
                <Tooltip cursor={{ fill: 'var(--grid)', opacity: 0.4 }}
                  content={({ active, payload }) => active && payload?.length ? (
                    <ChartTooltip>
                      <div className="font-medium text-ink">{typeLabel(String(payload[0].payload.type))}</div>
                      <div className="text-ink-2">{payload[0].value} findings</div>
                    </ChartTooltip>
                  ) : null} />
                <Bar dataKey="count" fill="var(--series-1)" barSize={16} radius={[0, 4, 4, 0]}
                  isAnimationActive={false}>
                  <LabelList dataKey="count" position="right"
                    fill="var(--text-secondary)" fontSize={11} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          }
          table={<CountTable nameHeader="Type" rows={byType.map(([t, n]) => [typeLabel(t), n])} />}
        />

        <VizCard
          title="Hotspot files"
          subtitle="top 10 files by finding count"
          chart={
            <div className="flex flex-col gap-2.5 py-1">
              {byFile.map(([file, n]) => {
                const max = byFile[0][1]
                return (
                  <div key={file} className="group" title={`${file} — ${n} findings`}>
                    <div className="mb-1 flex items-baseline justify-between gap-3">
                      <span className="truncate font-mono text-xs text-ink-2">{file}</span>
                      <span className="text-xs tabular-nums text-ink-2">{n}</span>
                    </div>
                    <div className="h-2 rounded-full bg-page">
                      <div className="h-2 rounded-full transition-[width]"
                        style={{ width: `${(n / max) * 100}%`, background: 'var(--series-1)' }} />
                    </div>
                  </div>
                )
              })}
            </div>
          }
          table={<CountTable nameHeader="File" rows={byFile} />}
        />

      <VizCard
        title="Impact vs effort"
        subtitle="scored findings bucketed on the 1–5 grid; bubble size = count, color = roadmap tier"
        chart={scored.length === 0 ? (
          <EmptyState title="No scored findings yet" hint="Run score or the full pipeline first." />
        ) : (
          <div>
            <ResponsiveContainer width="100%" height={320}>
              <ScatterChart margin={{ top: 12, right: 24, bottom: 28, left: 8 }}>
                <CartesianGrid stroke="var(--grid)" strokeWidth={1} />
                <XAxis type="number" dataKey="effort" name="effort" domain={[0.5, 5.5]}
                  ticks={[1, 2, 3, 4, 5]}
                  label={{ value: 'effort →', position: 'insideBottom', offset: -18, style: { fill: 'var(--text-muted)', fontSize: 11 } }}
                  tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                  axisLine={{ stroke: 'var(--baseline)' }} tickLine={false} />
                <YAxis type="number" dataKey="impact" name="impact" domain={[0.5, 5.5]}
                  ticks={[1, 2, 3, 4, 5]} width={40}
                  label={{ value: 'impact →', angle: -90, position: 'insideLeft', style: { fill: 'var(--text-muted)', fontSize: 11 } }}
                  tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                  axisLine={{ stroke: 'var(--baseline)' }} tickLine={false} />
                <ZAxis type="number" dataKey="count" range={[70, 480]} />
                <Tooltip cursor={false}
                  content={({ active, payload }) => active && payload?.length ? (
                    <ChartTooltip>
                      <div className="font-medium text-ink">
                        impact {payload[0].payload.impact} / effort {payload[0].payload.effort}
                      </div>
                      <div className="text-ink-2">{payload[0].payload.count} finding(s)</div>
                      <div className="text-ink-3">{TIER_META[payload[0].payload.tier as Tier].label}</div>
                    </ChartTooltip>
                  ) : null} />
                <Scatter data={grid} stroke="var(--surface-1)" strokeWidth={2}
                  isAnimationActive={false}>
                  {grid.map((cell, i) => (
                    <Cell key={i} fill={TIER_COLOR[cell.tier]} />
                  ))}
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
            <div className="mt-2 flex flex-wrap gap-4 pl-2">
              {(Object.keys(TIER_META) as Tier[]).map(t => (
                <span key={t} className="inline-flex items-center gap-1.5 text-xs text-ink-2">
                  <span aria-hidden className="size-2.5 rounded-full" style={{ background: TIER_COLOR[t] }} />
                  {TIER_META[t].label} <span className="text-ink-3">({TIER_META[t].blurb})</span>
                </span>
              ))}
            </div>
          </div>
        )}
        table={
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-edge text-left text-xs text-ink-3">
                <th className="py-1.5 font-medium">Impact</th>
                <th className="py-1.5 font-medium">Effort</th>
                <th className="py-1.5 font-medium">Tier</th>
                <th className="py-1.5 text-right font-medium">Findings</th>
              </tr>
            </thead>
            <tbody>
              {[...grid].sort((a, b) => b.count - a.count).map(c => (
                <tr key={`${c.impact}:${c.effort}`} className="border-b border-edge last:border-0">
                  <td className="py-1.5 tabular-nums text-ink-2">{c.impact}</td>
                  <td className="py-1.5 tabular-nums text-ink-2">{c.effort}</td>
                  <td className="py-1.5 text-ink-2">{TIER_META[c.tier].label}</td>
                  <td className="py-1.5 text-right tabular-nums text-ink">{c.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        }
      />
      </div>

      {info && !info.has_scored && (
        <p className="text-xs text-ink-3">
          Tip: this repo has scan results but no LLM scores yet — run <span className="font-mono">score</span> or
          the full pipeline from the <Link className="underline" to="/run">Run pipeline</Link> page to unlock the
          impact/effort scatter and the roadmap board.
        </p>
      )}
    </div>
  )
}
