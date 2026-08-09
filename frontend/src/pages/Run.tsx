import { useCallback, useEffect, useRef, useState } from 'react'
import { api, streamJob } from '../lib/api'
import { useRepo } from '../lib/store'
import { Card, Spinner, StatusBadge } from '../components/ui'
import type { Job } from '../lib/types'

const COMMANDS = [
  { id: 'scan', label: 'Scan', blurb: 'deterministic findings — fast, no API key' },
  { id: 'score', label: 'Score', blurb: 'LLM impact/effort scores (heuristic fallback offline)' },
  { id: 'run', label: 'Full pipeline', blurb: 'scan → score → fixes → roadmap (slow, LLM key needed for fixes)' },
  { id: 'eval', label: 'Eval', blurb: 'precision/recall vs planted debt — offline' },
] as const

type CommandId = typeof COMMANDS[number]['id']

function jobBadge(status: Job['status']) {
  if (status === 'running') return <StatusBadge kind="warning" label="Running" />
  if (status === 'succeeded') return <StatusBadge kind="good" label="Succeeded" />
  return <StatusBadge kind="critical" label="Failed" />
}

function fmtTime(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString()
}

export function RunPage() {
  const { repo, refresh } = useRepo()
  const [command, setCommand] = useState<CommandId>('scan')
  const [topN, setTopN] = useState(10)
  const [noFixes, setNoFixes] = useState(false)
  const [noRag, setNoRag] = useState(false)
  const [strategy, setStrategy] = useState<'multi' | 'single'>('multi')

  const [jobs, setJobs] = useState<Job[]>([])
  const [active, setActive] = useState<Job | null>(null)
  const [lines, setLines] = useState<string[]>([])
  const [startError, setStartError] = useState<string | null>(null)
  const logRef = useRef<HTMLPreElement>(null)
  const unsubRef = useRef<(() => void) | null>(null)

  const loadJobs = useCallback(() => { api.jobs().then(setJobs).catch(() => {}) }, [])
  useEffect(() => { loadJobs() }, [loadJobs])
  useEffect(() => () => { unsubRef.current?.() }, [])

  // keep the log pinned to the bottom as lines stream in
  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [lines])

  const attach = useCallback((job: Job, existing: string[] = []) => {
    unsubRef.current?.()
    setActive(job)
    setLines(existing)
    if (job.status !== 'running') return
    unsubRef.current = streamJob(
      job.id,
      line => setLines(prev => [...prev, line]),
      done => {
        setActive(done)
        loadJobs()
        refresh() // pull fresh findings/scored/fixes into every view
      },
      () => loadJobs(),
    )
  }, [loadJobs, refresh])

  const start = async () => {
    setStartError(null)
    try {
      const job = await api.createJob({
        command, repo,
        top_n: topN, no_fixes: noFixes, no_rag: noRag, strategy,
      })
      loadJobs()
      attach(job)
    } catch (e) {
      setStartError(e instanceof Error ? e.message : String(e))
    }
  }

  const openJob = async (id: number) => {
    try {
      const job = await api.job(id)
      attach(job, job.lines ?? [])
    } catch { /* job list will refresh on next action */ }
  }

  const running = active?.status === 'running'

  return (
    <div className="grid gap-4 xl:grid-cols-[380px_minmax(0,1fr)]">
      <div className="flex flex-col gap-4">
        <Card title="Run the pipeline" subtitle={`against ${repo || '(pick a repo above)'}`}>
          <div className="flex flex-col gap-2">
            {COMMANDS.map(c => (
              <label
                key={c.id}
                className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
                  command === c.id ? 'border-baseline bg-page' : 'border-edge hover:bg-page/60'
                }`}
              >
                <input
                  type="radio"
                  name="command"
                  className="mt-1 accent-[var(--series-1)]"
                  checked={command === c.id}
                  onChange={() => setCommand(c.id)}
                />
                <span>
                  <span className="block text-sm font-medium text-ink">{c.label}</span>
                  <span className="block text-xs text-ink-3">{c.blurb}</span>
                </span>
              </label>
            ))}
          </div>

          {command === 'run' && (
            <div className="mt-4 flex flex-col gap-3 border-t border-edge pt-4">
              <label className="flex items-center justify-between gap-3 text-sm text-ink-2">
                Top N findings to fix
                <input
                  type="number" min={1} max={50} value={topN}
                  onChange={e => setTopN(Number(e.target.value))}
                  className="w-20 rounded-lg border border-edge bg-surface px-2 py-1 text-right text-sm text-ink outline-none"
                />
              </label>
              <label className="flex items-center gap-2.5 text-sm text-ink-2">
                <input type="checkbox" className="accent-[var(--series-1)]" checked={noFixes}
                  onChange={e => setNoFixes(e.target.checked)} />
                Skip fix generation (score + roadmap only)
              </label>
              <label className="flex items-center justify-between gap-3 text-sm text-ink-2">
                Agent strategy
                <select
                  value={strategy}
                  onChange={e => setStrategy(e.target.value as 'multi' | 'single')}
                  className="rounded-lg border border-edge bg-surface px-2 py-1 text-sm text-ink outline-none"
                >
                  <option value="multi">multi (specialists)</option>
                  <option value="single">single (generalist)</option>
                </select>
              </label>
            </div>
          )}
          {command === 'score' && (
            <div className="mt-4 border-t border-edge pt-4">
              <label className="flex items-center gap-2.5 text-sm text-ink-2">
                <input type="checkbox" className="accent-[var(--series-1)]" checked={noRag}
                  onChange={e => setNoRag(e.target.checked)} />
                Skip fan-in enrichment
              </label>
            </div>
          )}

          <button
            onClick={start}
            disabled={running || !repo}
            className="mt-4 w-full rounded-lg px-4 py-2 text-sm font-medium text-white transition-opacity disabled:opacity-40"
            style={{ background: 'var(--series-1)' }}
          >
            {running ? 'A job is running…' : `Start ${COMMANDS.find(c => c.id === command)?.label.toLowerCase()}`}
          </button>
          {startError && <p className="mt-2 text-xs" style={{ color: 'var(--status-critical)' }}>{startError}</p>}
          {command === 'run' && !noFixes && (
            <p className="mt-2 text-xs text-ink-3">
              Heads up: the full pipeline makes many LLM calls with rate-limit pacing — expect several minutes.
            </p>
          )}
        </Card>

        <Card title="Job history">
          {jobs.length === 0 ? (
            <p className="text-xs text-ink-3">No jobs yet this session.</p>
          ) : (
            <div className="flex flex-col gap-1.5">
              {jobs.map(j => (
                <button
                  key={j.id}
                  onClick={() => openJob(j.id)}
                  className={`flex items-center gap-3 rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                    active?.id === j.id ? 'border-baseline bg-page' : 'border-edge hover:bg-page/60'
                  }`}
                >
                  <span className="font-mono text-ink-3">#{j.id}</span>
                  <span className="font-medium text-ink">{j.command}</span>
                  <span className="text-ink-3">{fmtTime(j.started_at)}</span>
                  <span className="ml-auto">{jobBadge(j.status)}</span>
                </button>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card
        title={active ? `Job #${active.id} — ${active.command}` : 'Output'}
        subtitle={active ? active.repo : 'start a job to stream its output here'}
        className="flex min-h-[60vh] flex-col"
      >
        {active && (
          <div className="mb-3 flex items-center gap-3">
            {jobBadge(active.status)}
            {running && <Spinner label="streaming…" />}
            {active.finished_at && (
              <span className="text-xs text-ink-3">
                finished in {(active.finished_at - active.started_at).toFixed(1)}s
                {active.returncode !== null && ` · exit ${active.returncode}`}
              </span>
            )}
          </div>
        )}
        <pre
          ref={logRef}
          className="log-pane min-h-0 flex-1 overflow-auto rounded-lg border border-edge bg-page p-3 text-xs leading-5 text-ink-2"
        >
          {lines.length === 0
            ? (running ? 'Waiting for output…' : 'No output yet.')
            : lines.join('\n')}
        </pre>
      </Card>
    </div>
  )
}
