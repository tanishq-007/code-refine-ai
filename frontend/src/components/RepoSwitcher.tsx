import { useEffect, useRef, useState } from 'react'
import { useRepo } from '../lib/store'
import { AddRepoModal } from './AddRepoModal'
import { Spinner } from './ui'

function shorten(path: string, max = 38): string {
  if (path.length <= max) return path
  return `…${path.slice(-(max - 1))}`
}

export function RepoSwitcher() {
  const { repo, setRepo, suggestions, info, loading } = useRepo()
  const [open, setOpen] = useState(false)
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState('')
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const current = suggestions.find(s => s.path === repo)
  const label = current?.label ?? (repo ? shorten(repo, 24) : 'Pick a repo')

  const commitDraft = () => {
    const p = draft.trim()
    if (p) { setRepo(p); setDraft(''); setOpen(false) }
  }

  return (
    <div className="relative" ref={panelRef}>
      <button
        onClick={() => setOpen(o => !o)}
        className="flex w-full items-center gap-2.5 rounded-lg border border-edge bg-page px-3 py-2 text-left transition-colors duration-200 hover:border-baseline"
      >
        <span aria-hidden
          className="flex size-7 shrink-0 items-center justify-center rounded-md text-xs font-semibold text-white"
          style={{ background: 'var(--series-1)' }}>
          {(label[0] ?? '?').toUpperCase()}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-ink">{label}</span>
          <span className="block truncate text-xs text-ink-3">
            {loading ? 'loading…' : info ? `${info.py_files} .py files` : 'repository'}
          </span>
        </span>
        <span aria-hidden className="text-xs text-ink-3">⌄</span>
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-30 mt-2 w-72 rounded-xl border border-edge bg-surface p-2 shadow-lg">
          <p className="px-2 pb-1.5 pt-1 text-xs font-medium text-ink-3">Repositories</p>
          <div className="flex max-h-64 flex-col gap-0.5 overflow-y-auto">
            {suggestions.map(s => (
              <button
                key={s.path}
                onClick={() => { setRepo(s.path); setOpen(false) }}
                className={`flex items-center gap-2.5 rounded-lg px-2 py-2 text-left transition-colors duration-200 ${
                  s.path === repo ? 'bg-page' : 'hover:bg-page'
                }`}
                title={s.path}
              >
                <span aria-hidden
                  className="flex size-6 shrink-0 items-center justify-center rounded-md text-[10px] font-semibold text-white"
                  style={{ background: s.path === repo ? 'var(--series-1)' : 'var(--baseline)' }}>
                  {s.label[0]?.toUpperCase()}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-ink">{s.label}</span>
                  <span className="block truncate text-xs text-ink-3">{shorten(s.path)}</span>
                </span>
                {s.path === repo && <span aria-hidden className="text-xs" style={{ color: 'var(--series-1)' }}>✓</span>}
              </button>
            ))}
            {suggestions.length === 0 && <Spinner label="Loading repos…" />}
          </div>

          <div className="mt-2 border-t border-edge pt-2">
            <div className="flex gap-1.5 px-1">
              <input
                className="min-w-0 flex-1 rounded-lg border border-edge bg-page px-2.5 py-1.5 text-xs text-ink outline-none placeholder:text-ink-3 focus:border-baseline"
                placeholder="Custom absolute path…"
                value={draft}
                onChange={e => setDraft(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') commitDraft() }}
              />
              <button
                onClick={commitDraft}
                disabled={!draft.trim()}
                className="shrink-0 rounded-lg border border-edge px-2.5 text-xs text-ink-2 hover:bg-page disabled:opacity-40"
              >
                Open
              </button>
            </div>
            <button
              onClick={() => { setOpen(false); setAdding(true) }}
              className="mt-1.5 flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm text-ink-2 transition-colors duration-200 hover:bg-page hover:text-ink"
            >
              <span aria-hidden className="flex size-6 items-center justify-center rounded-md border border-dashed border-baseline text-xs">+</span>
              Add repo — clone URL or upload
            </button>
          </div>
        </div>
      )}

      {adding && <AddRepoModal onClose={() => setAdding(false)} />}
    </div>
  )
}
