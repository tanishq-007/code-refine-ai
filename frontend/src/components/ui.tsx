import { useEffect, useState, type ReactNode } from 'react'
import { api } from '../lib/api'
import { typeLabel } from '../lib/types'

/** Counts up from 0 to `value` with an ease-out curve. Falls back to the
 *  final value instantly when the user prefers reduced motion. */
export function AnimatedNumber({ value, duration = 900 }: { value: number; duration?: number }) {
  const [display, setDisplay] = useState(0)
  useEffect(() => {
    if (value === 0 || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setDisplay(value)
      return
    }
    let raf: number
    const start = performance.now()
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - t, 3)
      setDisplay(Math.round(eased * value))
      if (t < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value, duration])
  return <>{display.toLocaleString()}</>
}

/* Series color for the finding-type accent dot. Types are identity, but 10
   classes exceeds the palette cap — so every type wears the same slot-1 hue
   and identity comes from the label text beside it, never hue alone. */
export function TypeBadge({ type }: { type: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-edge bg-surface px-2 py-0.5 text-xs text-ink-2 whitespace-nowrap">
      <span aria-hidden className="size-2 rounded-full" style={{ background: 'var(--series-1)' }} />
      {typeLabel(type)}
    </span>
  )
}

const KIND_STYLES: Record<string, { color: string; icon: string }> = {
  good: { color: 'var(--status-good)', icon: '✓' },
  warning: { color: 'var(--status-warning)', icon: '▲' },
  serious: { color: 'var(--status-serious)', icon: '▲' },
  critical: { color: 'var(--status-critical)', icon: '✕' },
  muted: { color: 'var(--text-muted)', icon: '○' },
}

/* Status colors ship with icon + label — never color alone. */
export function StatusBadge({ kind, label }: { kind: string; label: string }) {
  const s = KIND_STYLES[kind] ?? KIND_STYLES.muted
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-edge bg-surface px-2 py-0.5 text-xs font-medium text-ink-2 whitespace-nowrap">
      <span aria-hidden style={{ color: s.color }}>{s.icon}</span>
      {label}
    </span>
  )
}

export function Card({ title, subtitle, children, className = '' }: {
  title?: string; subtitle?: string; children: ReactNode; className?: string
}) {
  return (
    <section className={`rounded-xl border border-edge bg-surface p-5 ${className}`}>
      {title && (
        <header className="mb-4">
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          {subtitle && <p className="mt-0.5 text-xs text-ink-3">{subtitle}</p>}
        </header>
      )}
      {children}
    </section>
  )
}

export function StatTile({ label, value, detail }: {
  label: string; value: ReactNode; detail?: ReactNode
}) {
  return (
    <div className="card-hover rounded-xl border border-edge bg-surface p-4">
      <div className="text-xs text-ink-3">{label}</div>
      <div className="mt-1 text-[28px] font-semibold leading-9 tracking-tight text-ink">
        {typeof value === 'number' ? <AnimatedNumber value={value} /> : value}
      </div>
      {detail && <div className="mt-1 text-xs text-ink-2">{detail}</div>}
    </div>
  )
}

export function EmptyState({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-baseline bg-surface px-6 py-14 text-center">
      <p className="text-sm font-medium text-ink-2">{title}</p>
      {hint && <p className="mt-1.5 text-xs text-ink-3">{hint}</p>}
    </div>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-xs text-ink-3">
      <span className="size-3.5 animate-spin rounded-full border-2 border-baseline border-t-transparent" aria-hidden />
      {label}
    </span>
  )
}

/* Two-step apply: first click arms the confirmation, second click ships the
   diff to the real repo through the backend. Shared by the Fixes page
   (model-proposed fixes) and the Editor tab (manual hand-fixes) -- both
   write into the same fixes.json shape, so the same apply flow works for
   either origin. */
export function ApplyButton({ repo, findingId, onApplied }: {
  repo: string; findingId: string; onApplied: () => void
}) {
  const [arming, setArming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { setArming(false); setError(null) }, [findingId])

  const apply = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.applyFix(repo, findingId)
      onApplied()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setArming(false)
    } finally {
      setBusy(false)
    }
  }

  if (busy) return <Spinner label="Applying to repo…" />

  return (
    <span className="flex flex-wrap items-center gap-2">
      {arming ? (
        <>
          <span className="text-xs text-ink-2">Apply this diff to your real files?</span>
          <button onClick={apply}
            className="rounded-lg px-3 py-1.5 text-xs font-medium text-white"
            style={{ background: 'var(--status-good)' }}>
            Yes, apply
          </button>
          <button onClick={() => setArming(false)}
            className="rounded-lg border border-edge px-3 py-1.5 text-xs text-ink-2 hover:bg-page">
            Cancel
          </button>
        </>
      ) : (
        <button onClick={() => setArming(true)}
          className="rounded-lg px-3 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90"
          style={{ background: 'var(--series-1)' }}>
          Apply to repo
        </button>
      )}
      {error && <span className="w-full text-xs" style={{ color: 'var(--status-critical)' }}>{error}</span>}
    </span>
  )
}
