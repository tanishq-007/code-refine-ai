import { lazy, Suspense, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useRepo } from '../lib/store'
import { ApplyButton, Card, EmptyState, Spinner, StatusBadge, TypeBadge } from '../components/ui'
import {
  FIX_STATUS_META, fixStatus, isRejected,
  type FixResult, type FixStatus, type ScoredFinding,
} from '../lib/types'

// Monaco's core is multiple MB even split from its language workers -- lazy
// loading keeps it out of every other page's initial bundle, so it's only
// fetched once someone actually opens a fix with a diff to render.
const SplitFixEditor = lazy(() =>
  import('../components/SplitFixEditor').then(m => ({ default: m.SplitFixEditor })))

interface Entry {
  id: string
  fix: FixResult
  status: FixStatus
  finding?: ScoredFinding
}

const STATUS_ORDER: FixStatus[] = ['verified', 'tests-failed', 'rejected', 'not-applied', 'error']

export function FixesPage() {
  const { repo, fixes, scored, refresh } = useRepo()
  const [statusFilter, setStatusFilter] = useState<'all' | FixStatus>('all')
  const [selected, setSelected] = useState<string | null>(null)

  const entries = useMemo<Entry[]>(() => {
    const byId = new Map(scored.map(s => [s.id, s]))
    return Object.entries(fixes)
      .map(([id, fix]) => ({ id, fix, status: fixStatus(fix), finding: byId.get(id) }))
      .sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status))
  }, [fixes, scored])

  const counts = useMemo(() => {
    const c = new Map<FixStatus, number>()
    for (const e of entries) c.set(e.status, (c.get(e.status) ?? 0) + 1)
    return c
  }, [entries])

  const visible = statusFilter === 'all' ? entries : entries.filter(e => e.status === statusFilter)
  const current = entries.find(e => e.id === (selected ?? visible[0]?.id)) ?? visible[0]

  if (entries.length === 0) {
    return (
      <EmptyState
        title="No proposed fixes yet"
        hint={<>Run the full pipeline (with fixes enabled) from the <Link className="underline" to="/run">Run pipeline</Link> page. Requires an LLM API key in <span className="font-mono">.env</span>.</>}
      />
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => setStatusFilter('all')}
          className={`rounded-full border border-edge px-3 py-1 text-xs ${statusFilter === 'all' ? 'bg-surface font-medium text-ink' : 'text-ink-3 hover:text-ink-2'}`}
        >
          All ({entries.length})
        </button>
        {STATUS_ORDER.filter(s => counts.get(s)).map(s => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`rounded-full border border-edge px-3 py-1 text-xs ${statusFilter === s ? 'bg-surface font-medium text-ink' : 'text-ink-3 hover:text-ink-2'}`}
          >
            {FIX_STATUS_META[s].label} ({counts.get(s)})
          </button>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <div className="flex max-h-[75vh] flex-col gap-2 overflow-y-auto pr-1">
          {visible.map(e => (
            <button
              key={e.id}
              onClick={() => setSelected(e.id)}
              className={`rounded-xl border p-3 text-left transition-colors ${
                current?.id === e.id
                  ? 'border-baseline bg-surface'
                  : 'border-edge bg-surface/60 hover:bg-surface'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                {e.finding ? <TypeBadge type={e.finding.type} /> : <span className="font-mono text-xs text-ink-3">{e.id}</span>}
                <StatusBadge kind={FIX_STATUS_META[e.status].kind} label={FIX_STATUS_META[e.status].label} />
              </div>
              {e.finding && (
                <>
                  <p className="mt-2 truncate font-mono text-xs text-ink-2">
                    {e.finding.file}:{e.finding.line_start}
                  </p>
                  {e.finding.symbol && <p className="truncate text-sm text-ink">{e.finding.symbol}</p>}
                </>
              )}
            </button>
          ))}
        </div>

        {current ? (
          <Card className="max-h-[75vh] overflow-y-auto">
            <div className="flex flex-col gap-3">
              <header className="flex flex-wrap items-center gap-2">
                {current.finding && <TypeBadge type={current.finding.type} />}
                <StatusBadge kind={FIX_STATUS_META[current.status].kind} label={FIX_STATUS_META[current.status].label} />
                {current.fix.agent && (
                  <span className="rounded-full border border-edge px-2 py-0.5 text-xs text-ink-2">
                    {current.fix.agent}
                  </span>
                )}
                <span className="ml-auto font-mono text-xs text-ink-3">{current.id}</span>
              </header>

              {current.finding && (
                <div>
                  <p className="font-mono text-xs text-ink-2">
                    {current.finding.file}:{current.finding.line_start}-{current.finding.line_end}
                  </p>
                  <p className="mt-1 text-sm text-ink-2">{current.finding.description}</p>
                </div>
              )}

              {current.fix.routing_reason && (
                <p className="text-xs text-ink-3">
                  <span className="font-medium text-ink-2">Routing:</span> {current.fix.routing_reason}
                </p>
              )}

              {current.fix.review && (
                <div className="rounded-lg border border-edge bg-page px-3 py-2.5">
                  <p className="text-xs font-medium text-ink">
                    Reviewer verdict: <span className="capitalize">{current.fix.review.verdict}</span>
                  </p>
                  {current.fix.review.rationale && (
                    <p className="mt-1 text-xs text-ink-2">{current.fix.review.rationale}</p>
                  )}
                </div>
              )}

              {current.fix.retry && (
                <p className="text-xs text-ink-3">
                  <span className="font-medium text-ink-2">Retry:</span> {current.fix.retry}
                </p>
              )}

              {current.fix.error && (
                <div className="rounded-lg border border-edge bg-page px-3 py-2.5">
                  <p className="text-xs text-ink-2">
                    <StatusBadge kind="critical" label="Error" /> <span className="ml-1">{current.fix.error}</span>
                  </p>
                </div>
              )}

              {current.status === 'verified' && (
                <div className="flex items-center justify-between gap-3 rounded-lg border border-edge bg-page px-3 py-2.5">
                  {current.fix.applied_to_repo ? (
                    <>
                      <StatusBadge kind="good" label="Applied to your repo" />
                      <span className="text-xs text-ink-3">re-run a scan to refresh the findings</span>
                    </>
                  ) : (
                    <ApplyButton repo={repo} findingId={current.id} onApplied={refresh} />
                  )}
                </div>
              )}

              {current.fix.diff ? (
                isRejected(current.fix) ? (
                  <div className="rounded-lg border border-dashed border-baseline px-4 py-6 text-center text-xs text-ink-3">
                    Diff withheld: the reviewer rejected this fix (see rationale above).
                  </div>
                ) : (
                  <Suspense fallback={<Spinner label="Loading editor…" />}>
                    <SplitFixEditor repo={repo} findingId={current.id} diff={current.fix.diff} onSaved={refresh} />
                  </Suspense>
                )
              ) : (
                !current.fix.error && (
                  <p className="text-xs text-ink-3">No diff was produced for this finding.</p>
                )
              )}
            </div>
          </Card>
        ) : (
          <EmptyState title="No fixes match this filter" />
        )}
      </div>
    </div>
  )
}
