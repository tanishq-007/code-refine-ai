import { lazy, Suspense, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useRepo } from '../lib/store'
import { ChevronDownIcon, PanelLeftIcon } from '../components/icons'
import { EmptyState, Spinner, StatusBadge, TypeBadge } from '../components/ui'
import {
  FIX_STATUS_META, fixStatus, tierOf, TIER_META,
  type ScoredFinding, type Tier,
} from '../lib/types'

const ManualFixEditor = lazy(() =>
  import('../components/ManualFixEditor').then(m => ({ default: m.ManualFixEditor })))

const TIER_ACCENT: Record<Tier, string> = {
  'do-now': 'var(--series-1)',
  plan: 'var(--series-2)',
  backlog: 'var(--series-3)',
}

/** The editor tab: the ranked roadmap on the left, a hands-on editor on the
 *  right. The pipeline only generates LLM fixes for the top-N findings; this
 *  page is for everything else -- pick any finding, edit its file directly,
 *  and save to get the same sandboxed verification an LLM fix gets. */
export function EditorPage() {
  const { repo, scored, fixes, refresh } = useRepo()
  const [selected, setSelected] = useState<string | null>(null)
  const [filter, setFilter] = useState<'remaining' | 'all'>('remaining')
  const [listOpen, setListOpen] = useState(true)
  const [detailsOpen, setDetailsOpen] = useState(true)

  const ranked = useMemo(() =>
    [...scored].sort((a, b) => b.ratio - a.ratio || b.impact - a.impact), [scored])

  const remaining = useMemo(() =>
    ranked.filter(s => !fixes[s.id]?.diff), [ranked, fixes])

  const visible = filter === 'all' ? ranked : remaining

  const tiers = useMemo(() => {
    const t: Record<Tier, ScoredFinding[]> = { 'do-now': [], plan: [], backlog: [] }
    for (const s of visible) t[tierOf(s.impact, s.ratio)].push(s)
    return t
  }, [visible])

  const current =
    ranked.find(s => s.id === selected) ?? visible[0] ?? null

  if (scored.length === 0) {
    return (
      <EmptyState
        title="Nothing to edit yet"
        hint={<>The editor works from the scored roadmap — run <span className="font-mono">score</span> or the full pipeline from the <Link className="underline" to="/run">Run pipeline</Link> page first.</>}
      />
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg border border-edge text-xs">
          {(['remaining', 'all'] as const).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 first:rounded-l-lg last:rounded-r-lg ${
                filter === f ? 'bg-surface font-medium text-ink' : 'text-ink-3 hover:text-ink-2'
              }`}
            >
              {f === 'remaining' ? `No fix yet (${remaining.length})` : `All (${ranked.length})`}
            </button>
          ))}
        </div>
        <span className="text-xs text-ink-3">
          Pick a finding, fix it by hand — saving verifies your edit in a sandbox like any other fix
        </span>
        <button
          onClick={() => setListOpen(o => !o)}
          className="ml-auto flex items-center gap-1.5 rounded-lg border border-edge px-2.5 py-1.5 text-xs text-ink-2 transition-colors hover:bg-surface hover:text-ink"
        >
          <PanelLeftIcon className={listOpen ? '' : 'opacity-50'} />
          {listOpen ? 'Hide list' : 'Show list'}
        </button>
      </div>

      <div className={`grid gap-4 ${listOpen ? 'lg:grid-cols-[340px_minmax(0,1fr)]' : ''}`}>
        {listOpen && (
        <div className="flex max-h-[78vh] flex-col gap-3 overflow-y-auto pr-1">
          {visible.length === 0 && (
            <div className="rounded-xl border border-dashed border-baseline px-4 py-8 text-center text-xs text-ink-3">
              Every scored finding already has a proposed fix — review them on the{' '}
              <Link to="/fixes" className="underline">Fix review</Link> page.
            </div>
          )}
          {(Object.keys(TIER_META) as Tier[]).map(tier => tiers[tier].length > 0 && (
            <section key={tier} className="flex flex-col gap-2">
              <header className="flex items-center gap-2 px-1">
                <span aria-hidden className="size-2.5 rounded-full" style={{ background: TIER_ACCENT[tier] }} />
                <h2 className="text-sm font-semibold text-ink">{TIER_META[tier].label}</h2>
                <span className="ml-auto rounded-full border border-edge bg-surface px-2 py-0.5 text-xs tabular-nums text-ink-2">
                  {tiers[tier].length}
                </span>
              </header>
              {tiers[tier].map(s => {
                const fix = fixes[s.id]
                const status = fix ? fixStatus(fix) : null
                return (
                  <button
                    key={s.id}
                    onClick={() => setSelected(s.id)}
                    className={`rounded-xl border p-3 text-left transition-colors ${
                      current?.id === s.id
                        ? 'border-baseline bg-surface'
                        : 'border-edge bg-surface/60 hover:bg-surface'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <TypeBadge type={s.type} />
                      <span className="shrink-0 text-xs tabular-nums text-ink-3">
                        ratio {s.ratio.toFixed(2)}
                      </span>
                    </div>
                    <p className="mt-2 truncate font-mono text-xs text-ink-2" title={`${s.file}:${s.line_start}-${s.line_end}`}>
                      {s.file}:{s.line_start}
                    </p>
                    {s.symbol && <p className="truncate text-sm text-ink">{s.symbol}</p>}
                    {status && (
                      <div className="mt-2">
                        <StatusBadge kind={FIX_STATUS_META[status].kind} label={FIX_STATUS_META[status].label} />
                      </div>
                    )}
                  </button>
                )
              })}
            </section>
          ))}
        </div>
        )}

        {current ? (
          <div className="flex h-[78vh] min-w-0 flex-col gap-3">
            <div className="rounded-xl border border-edge bg-surface px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <TypeBadge type={current.type} />
                {current.symbol && <span className="text-sm font-medium text-ink">{current.symbol}</span>}
                <span className="ml-auto text-xs tabular-nums text-ink-3">
                  impact {current.impact} / effort {current.effort}
                </span>
                <button
                  onClick={() => setDetailsOpen(o => !o)}
                  aria-label={detailsOpen ? 'Collapse finding details' : 'Expand finding details'}
                  className="rounded p-0.5 text-ink-3 transition-colors hover:text-ink"
                >
                  <ChevronDownIcon className={`transition-transform duration-200 ${detailsOpen ? '' : '-rotate-90'}`} />
                </button>
              </div>
              {detailsOpen && (
                <>
                  <p className="mt-1.5 text-xs text-ink-2">{current.description}</p>
                  {current.justification && (
                    <p className="mt-1 text-xs text-ink-3">{current.justification}</p>
                  )}
                </>
              )}
            </div>
            <Suspense fallback={
              <div className="flex flex-1 items-center justify-center rounded-xl border border-edge bg-page">
                <Spinner label="Loading editor…" />
              </div>
            }>
              <ManualFixEditor
                key={`${repo}:${current.id}`}
                repo={repo}
                finding={current}
                onSaved={refresh}
              />
            </Suspense>
          </div>
        ) : (
          <EmptyState title="Select a finding to start editing" />
        )}
      </div>
    </div>
  )
}
