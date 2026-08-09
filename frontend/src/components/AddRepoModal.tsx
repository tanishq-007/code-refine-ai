import { useEffect, useRef, useState, type DragEvent } from 'react'
import { api, streamJob } from '../lib/api'
import { useRepo } from '../lib/store'
import { Spinner } from './ui'

/* Directories nobody wants scanned or uploaded — skipped during traversal. */
const JUNK_DIRS = new Set([
  '.git', 'node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build',
  '.idea', '.vscode', '.mypy_cache', '.pytest_cache', '.tox', 'site-packages',
])

interface Item { file: File; path: string }

async function traverseEntry(entry: FileSystemEntry, prefix: string, out: Item[]): Promise<void> {
  if (entry.isFile) {
    const file = await new Promise<File>((res, rej) =>
      (entry as FileSystemFileEntry).file(res, rej))
    out.push({ file, path: prefix + entry.name })
  } else if (entry.isDirectory) {
    if (JUNK_DIRS.has(entry.name)) return
    const reader = (entry as FileSystemDirectoryEntry).createReader()
    // readEntries returns batches of ≤100 — keep reading until empty
    for (;;) {
      const batch = await new Promise<FileSystemEntry[]>((res, rej) =>
        reader.readEntries(res, rej))
      if (batch.length === 0) break
      for (const e of batch) await traverseEntry(e, `${prefix}${entry.name}/`, out)
    }
  }
}

function filterPicked(files: FileList): Item[] {
  return [...files]
    .map(f => ({ file: f, path: f.webkitRelativePath || f.name }))
    .filter(({ path }) => !path.split('/').some(part => JUNK_DIRS.has(part)))
}

export function AddRepoModal({ onClose }: { onClose: () => void }) {
  const { setRepo, reloadRepos } = useRepo()

  const [url, setUrl] = useState('')
  const [cloneLines, setCloneLines] = useState<string[]>([])
  const [cloning, setCloning] = useState(false)

  const [uploading, setUploading] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const folderInput = useRef<HTMLInputElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const unsubRef = useRef<(() => void) | null>(null)
  useEffect(() => () => { unsubRef.current?.() }, [])

  const busy = cloning || uploading !== null

  const finish = (path: string) => {
    reloadRepos()
    setRepo(path)
    onClose()
  }

  const clone = async () => {
    setError(null)
    setCloneLines([])
    setCloning(true)
    try {
      const job = await api.createJob({ command: 'clone', url: url.trim() })
      unsubRef.current = streamJob(
        job.id,
        line => setCloneLines(prev => [...prev, line]),
        done => {
          setCloning(false)
          if (done.status === 'succeeded') finish(done.repo)
          else setError(`clone failed (exit ${done.returncode ?? '?'}) — see log above`)
        },
        () => { setCloning(false); setError('lost connection to the clone job') },
      )
    } catch (e) {
      setCloning(false)
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const upload = async (items: Item[]) => {
    setError(null)
    if (items.length === 0) {
      setError('nothing to upload (only ignored folders like .git / node_modules?)')
      return
    }
    setUploading(`Uploading ${items.length} file(s)…`)
    try {
      const res = await api.uploadRepo(items)
      finish(res.path)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setUploading(null)
    }
  }

  const onDrop = async (ev: DragEvent) => {
    ev.preventDefault()
    setDragOver(false)
    if (busy) return
    setError(null)
    const entries = [...ev.dataTransfer.items]
      .map(item => item.webkitGetAsEntry())
      .filter((e): e is FileSystemEntry => e !== null)
    if (entries.length === 0) return
    setUploading('Reading dropped folder…')
    try {
      const items: Item[] = []
      for (const entry of entries) await traverseEntry(entry, '', items)
      await upload(items)
    } catch (e) {
      setUploading(null)
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={() => !busy && onClose()}
    >
      <div
        className="w-full max-w-lg rounded-xl border border-edge bg-surface p-6"
        onClick={e => e.stopPropagation()}
      >
        <header className="mb-5 flex items-start justify-between">
          <div>
            <h2 className="text-sm font-semibold text-ink">Add a repo</h2>
            <p className="mt-0.5 text-xs text-ink-3">
              Clones and uploads land in <span className="font-mono">.code_debt_workspace/</span> and appear in the repo list.
            </p>
          </div>
          <button onClick={onClose} disabled={busy}
            className="rounded-lg px-2 py-1 text-sm text-ink-3 hover:bg-page hover:text-ink disabled:opacity-40">
            ✕
          </button>
        </header>

        <section>
          <h3 className="text-xs font-medium text-ink-2">Clone from URL</h3>
          <div className="mt-2 flex gap-2">
            <input
              className="min-w-0 flex-1 rounded-lg border border-edge bg-page px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-3 focus:border-baseline"
              placeholder="https://github.com/user/repo"
              value={url}
              disabled={busy}
              onChange={e => setUrl(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && url.trim() && !busy) clone() }}
            />
            <button
              onClick={clone}
              disabled={busy || !url.trim()}
              className="shrink-0 rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
              style={{ background: 'var(--series-1)' }}
            >
              {cloning ? 'Cloning…' : 'Clone'}
            </button>
          </div>
          {cloneLines.length > 0 && (
            <pre className="log-pane mt-2 max-h-32 overflow-auto rounded-lg border border-edge bg-page p-2 text-xs leading-5 text-ink-2">
              {cloneLines.join('\n')}
            </pre>
          )}
        </section>

        <div className="my-5 flex items-center gap-3 text-xs text-ink-3">
          <span className="h-px flex-1 bg-grid" aria-hidden /> or <span className="h-px flex-1 bg-grid" aria-hidden />
        </div>

        <section>
          <h3 className="text-xs font-medium text-ink-2">Upload from this machine</h3>
          <div
            onDragOver={e => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            className={`mt-2 rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors ${
              dragOver ? 'border-baseline bg-page' : 'border-grid'
            }`}
          >
            {uploading ? (
              <Spinner label={uploading} />
            ) : (
              <>
                <p className="text-sm text-ink-2">Drag a folder (or files) here</p>
                <p className="mt-1 text-xs text-ink-3">
                  or{' '}
                  <button className="underline hover:text-ink-2" disabled={busy}
                    onClick={() => folderInput.current?.click()}>
                    pick a folder
                  </button>
                  {' / '}
                  <button className="underline hover:text-ink-2" disabled={busy}
                    onClick={() => fileInput.current?.click()}>
                    pick files
                  </button>
                </p>
                <p className="mt-2 text-xs text-ink-3">
                  .git, node_modules, venvs and similar are skipped automatically
                </p>
              </>
            )}
          </div>
          <input
            ref={folderInput} type="file" multiple hidden
            /* non-standard but universal in Chromium/Firefox/Safari */
            {...{ webkitdirectory: '' }}
            onChange={e => { if (e.target.files) upload(filterPicked(e.target.files)); e.target.value = '' }}
          />
          <input
            ref={fileInput} type="file" multiple hidden
            onChange={e => { if (e.target.files) upload(filterPicked(e.target.files)); e.target.value = '' }}
          />
        </section>

        {error && (
          <p className="mt-4 text-xs" style={{ color: 'var(--status-critical)' }}>{error}</p>
        )}
      </div>
    </div>
  )
}
