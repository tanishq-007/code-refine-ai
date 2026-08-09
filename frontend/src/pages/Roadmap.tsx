import { useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Link } from 'react-router-dom'
import { useRepo } from '../lib/store'
import { EmptyState, StatusBadge, TypeBadge } from '../components/ui'
import {
  FIX_STATUS_META, fixStatus, tierOf, TIER_META,
  type ScoredFinding, type Tier,
} from '../lib/types'

const TIER_ACCENT: Record<Tier, string> = {
  'do-now': 'var(--series-1)',
  plan: 'var(--series-2)',
  backlog: 'var(--series-3)',
}

function TierColumn({ tier, items }: { tier: Tier; items: ScoredFinding[] }) {
  const { fixes } = useRepo()
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <header className="flex items-center gap-2 px-1">
        <span aria-hidden className="size-2.5 rounded-full" style={{ background: TIER_ACCENT[tier] }} />
        <h2 className="text-sm font-semibold text-ink">{TIER_META[tier].label}</h2>
        <span className="text-xs text-ink-3">{TIER_META[tier].blurb}</span>
        <span className="ml-auto rounded-full border border-edge bg-surface px-2 py-0.5 text-xs tabular-nums text-ink-2">
          {items.length}
        </span>
      </header>
      {items.length === 0 && (
        <div className="rounded-xl border border-dashed border-baseline px-4 py-8 text-center text-xs text-ink-3">
          Nothing in this tier
        </div>
      )}
      {items.map(s => {
        const fix = fixes[s.id]
        const status = fix ? fixStatus(fix) : null
        return (
          <article key={s.id} className="rounded-xl border border-edge bg-surface p-4">
            <div className="flex items-start justify-between gap-2">
              <TypeBadge type={s.type} />
              <span className="shrink-0 text-xs tabular-nums text-ink-3">
                {s.impact}/{s.effort} · ratio {s.ratio.toFixed(2)}
              </span>
            </div>
            <p className="mt-2 truncate font-mono text-xs text-ink-2" title={`${s.file}:${s.line_start}-${s.line_end}`}>
              {s.file}:{s.line_start}
            </p>
            {s.symbol && <p className="text-sm font-medium text-ink">{s.symbol}</p>}
            <p className="mt-1.5 line-clamp-3 text-xs text-ink-2">{s.description}</p>
            {s.justification && (
              <p className="mt-1.5 line-clamp-2 text-xs text-ink-3">{s.justification}</p>
            )}
            {status && (
              <div className="mt-3 flex items-center justify-between gap-2 border-t border-edge pt-2.5">
                <StatusBadge kind={FIX_STATUS_META[status].kind} label={FIX_STATUS_META[status].label} />
                {fix?.diff && (
                  <Link to="/fixes" className="text-xs text-ink-3 underline hover:text-ink-2">
                    view diff
                  </Link>
                )}
              </div>
            )}
          </article>
        )
      })}
    </div>
  )
}

export function RoadmapPage() {
  const { scored, roadmapMd } = useRepo()
  const [view, setView] = useState<'board' | 'markdown'>('board')

  const tiers = useMemo(() => {
    const t: Record<Tier, ScoredFinding[]> = { 'do-now': [], plan: [], backlog: [] }
    for (const s of scored) t[tierOf(s.impact, s.ratio)].push(s)
    for (const k of Object.keys(t) as Tier[]) t[k].sort((a, b) => b.ratio - a.ratio || b.impact - a.impact)
    return t
  }, [scored])

  if (scored.length === 0 && !roadmapMd) {
    return (
      <EmptyState
        title="No roadmap yet"
        hint={<>Run <span className="font-mono">score</span> or the full pipeline from the <Link className="underline" to="/run">Run pipeline</Link> page.</>}
      />
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <div className="flex rounded-lg border border-edge text-xs">
          {(['board', 'markdown'] as const).map(m => (
            <button
              key={m}
              onClick={() => setView(m)}
              disabled={m === 'board' ? scored.length === 0 : !roadmapMd}
              className={`px-3 py-1.5 capitalize first:rounded-l-lg last:rounded-r-lg disabled:opacity-40 ${
                view === m ? 'bg-surface font-medium text-ink' : 'text-ink-3 hover:text-ink-2'
              }`}
            >
              {m === 'markdown' ? 'roadmap.md' : 'Board'}
            </button>
          ))}
        </div>
        <span className="text-xs text-ink-3">
          {scored.length} scored findings, ranked by impact/effort ratio
        </span>
      </div>

      {view === 'board' && scored.length > 0 ? (
        <div className="grid gap-5 xl:grid-cols-3">
          {(Object.keys(TIER_META) as Tier[]).map(t => (
            <TierColumn key={t} tier={t} items={tiers[t]} />
          ))}
        </div>
      ) : roadmapMd ? (
        <article className="prose-sm max-w-3xl rounded-xl border border-edge bg-surface p-6 text-sm leading-6 text-ink-2 [&_code]:rounded [&_code]:bg-page [&_code]:px-1 [&_code]:font-mono [&_code]:text-xs [&_h1]:text-lg [&_h1]:font-semibold [&_h1]:text-ink [&_h2]:mt-6 [&_h2]:text-base [&_h2]:font-semibold [&_h2]:text-ink [&_h3]:mt-4 [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:text-ink [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-page [&_pre]:p-3 [&_table]:my-3 [&_table]:w-full [&_td]:border-b [&_td]:border-edge [&_td]:py-1 [&_th]:border-b [&_th]:border-edge [&_th]:py-1 [&_th]:text-left [&_ul]:list-disc [&_ul]:pl-5">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{roadmapMd}</ReactMarkdown>
        </article>
      ) : (
        <EmptyState title="roadmap.md not generated yet" hint="Run the full pipeline to produce it." />
      )}
    </div>
  )
}
