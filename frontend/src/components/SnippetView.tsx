import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { Snippet } from '../lib/types'
import { Spinner } from './ui'

export function SnippetView({ repo, path, start, end }: {
  repo: string; path: string; start: number; end: number
}) {
  const [snippet, setSnippet] = useState<Snippet | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setSnippet(null)
    setError(null)
    api.snippet(repo, path, start, end)
      .then(s => { if (!cancelled) setSnippet(s) })
      .catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)) })
    return () => { cancelled = true }
  }, [repo, path, start, end])

  if (error) return <p className="text-xs text-ink-3">Could not load snippet: {error}</p>
  if (!snippet) return <Spinner label="Loading snippet…" />

  return (
    <pre className="log-pane overflow-x-auto rounded-lg border border-edge bg-page p-3 text-xs leading-5">
      {snippet.lines.map((line, i) => {
        const n = snippet.line_start + i
        const inRange = n >= start && n <= end
        return (
          <div key={n} className={`flex whitespace-pre ${inRange ? 'bg-[var(--diff-add-bg)]' : ''}`}>
            <span className="w-10 shrink-0 select-none pr-3 text-right text-ink-3 tabular-nums">{n}</span>
            <span className={inRange ? 'text-ink' : 'text-ink-2'}>{line || ' '}</span>
          </div>
        )
      })}
    </pre>
  )
}
