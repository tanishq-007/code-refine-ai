import { Fragment, useMemo, useState } from 'react'
import { useRepo } from '../lib/store'
import { EmptyState, TypeBadge } from '../components/ui'
import { SnippetView } from '../components/SnippetView'
import { typeLabel } from '../lib/types'

type SortKey = 'ratio' | 'impact' | 'file' | 'type'

export function FindingsPage() {
  const { repo, findings, scored } = useRepo()
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<SortKey>('ratio')
  const [open, setOpen] = useState<string | null>(null)

  const scoreById = useMemo(
    () => new Map(scored.map(s => [s.id, s])),
    [scored],
  )

  const types = useMemo(
    () => [...new Set(findings.map(f => f.type))].sort(),
    [findings],
  )

  const rows = useMemo(() => {
    const ql = query.toLowerCase()
    const filtered = findings.filter(f =>
      (typeFilter === 'all' || f.type === typeFilter) &&
      (!ql ||
        f.file.toLowerCase().includes(ql) ||
        (f.symbol ?? '').toLowerCase().includes(ql) ||
        f.description.toLowerCase().includes(ql)))
    return filtered.sort((a, b) => {
      const sa = scoreById.get(a.id)
      const sb = scoreById.get(b.id)
      switch (sort) {
        case 'ratio': return (sb?.ratio ?? -1) - (sa?.ratio ?? -1)
        case 'impact': return (sb?.impact ?? -1) - (sa?.impact ?? -1)
        case 'file': return a.file.localeCompare(b.file) || a.line_start - b.line_start
        case 'type': return a.type.localeCompare(b.type) || a.file.localeCompare(b.file)
      }
    })
  }, [findings, typeFilter, query, sort, scoreById])

  if (findings.length === 0) {
    return <EmptyState title="No findings for this repo yet" hint="Run a scan from the Run pipeline page." />
  }

  return (
    <div className="flex flex-col gap-4">
      {/* one filter row above everything it scopes */}
      <div className="flex flex-wrap items-center gap-3">
        <input
          className="w-72 rounded-lg border border-edge bg-surface px-3 py-1.5 text-sm text-ink outline-none placeholder:text-ink-3 focus:border-baseline"
          placeholder="Filter by file, symbol, or description…"
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
        <select
          className="rounded-lg border border-edge bg-surface px-3 py-1.5 text-sm text-ink outline-none"
          value={typeFilter}
          onChange={e => setTypeFilter(e.target.value)}
        >
          <option value="all">All types ({findings.length})</option>
          {types.map(t => (
            <option key={t} value={t}>
              {typeLabel(t)} ({findings.filter(f => f.type === t).length})
            </option>
          ))}
        </select>
        <select
          className="rounded-lg border border-edge bg-surface px-3 py-1.5 text-sm text-ink outline-none"
          value={sort}
          onChange={e => setSort(e.target.value as SortKey)}
        >
          <option value="ratio">Sort: impact/effort ratio</option>
          <option value="impact">Sort: impact</option>
          <option value="file">Sort: file</option>
          <option value="type">Sort: type</option>
        </select>
        <span className="ml-auto text-xs text-ink-3">{rows.length} of {findings.length} findings</span>
      </div>

      <div className="overflow-hidden rounded-xl border border-edge bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-edge text-left text-xs text-ink-3">
              <th className="px-4 py-2.5 font-medium">Type</th>
              <th className="px-4 py-2.5 font-medium">Location</th>
              <th className="px-4 py-2.5 font-medium">Description</th>
              <th className="px-3 py-2.5 text-right font-medium">Impact</th>
              <th className="px-3 py-2.5 text-right font-medium">Effort</th>
              <th className="px-4 py-2.5 text-right font-medium">Ratio</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((f, i) => {
              const s = scoreById.get(f.id)
              const expanded = open === f.id
              return (
                // the scanner occasionally emits duplicate finding ids, so
                // the row key needs the index to stay unique
                <Fragment key={`${f.id}:${i}`}>
                  <tr
                    className="cursor-pointer border-b border-edge transition-colors last:border-0 hover:bg-page"
                    onClick={() => setOpen(expanded ? null : f.id)}
                  >
                    <td className="px-4 py-2.5"><TypeBadge type={f.type} /></td>
                    <td className="px-4 py-2.5 font-mono text-xs text-ink-2">
                      {f.file}:{f.line_start}
                      {f.symbol && <span className="block text-ink-3">{f.symbol}</span>}
                    </td>
                    <td className="max-w-md px-4 py-2.5 text-ink-2">
                      <span className="line-clamp-2">{f.description}</span>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-ink">{s?.impact ?? '—'}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-ink">{s?.effort ?? '—'}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums font-medium text-ink">
                      {s ? s.ratio.toFixed(2) : '—'}
                    </td>
                  </tr>
                  {expanded && (
                    <tr className="border-b border-edge last:border-0">
                      <td colSpan={6} className="bg-page/60 px-4 py-3">
                        <div className="flex flex-col gap-3">
                          {s?.justification && (
                            <p className="text-xs text-ink-2">
                              <span className="font-medium text-ink">Scorer notes:</span> {s.justification}
                            </p>
                          )}
                          <SnippetView repo={repo} path={f.file} start={f.line_start} end={f.line_end} />
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
