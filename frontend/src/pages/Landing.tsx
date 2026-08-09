import { Link } from 'react-router-dom'
import { useRepo } from '../lib/store'
import { FINDING_TYPES, typeLabel } from '../lib/types'

const STEPS = [
  {
    n: 1, title: 'Scan', icon: '⌕',
    text: 'Deterministic analyzers walk the codebase — AST complexity, dead code, duplication, missing tests and more. No API key needed.',
  },
  {
    n: 2, title: 'Score', icon: '⚖',
    text: 'An LLM weighs each finding: how much does it hurt (impact) vs. how hard is it to fix (effort), enriched with real fan-in signals via RAG.',
  },
  {
    n: 3, title: 'Route', icon: '⇄',
    text: 'A planner routes each finding to a specialist agent — Refactoring or Documentation — over in-process tools or a real MCP session.',
  },
  {
    n: 4, title: 'Fix & verify', icon: '✓',
    text: 'Agents propose fixes as unified diffs, apply them to a throwaway copy, run the tests, and an independent reviewer approves or rejects.',
  },
  {
    n: 5, title: 'Roadmap', icon: '⇗',
    text: 'Everything lands in a prioritized roadmap — Do now, Plan, Backlog — with verified diffs ready to apply.',
  },
]

const CAPABILITIES = [
  { title: '10 debt detectors', text: 'complexity, long functions, duplication, missing tests, dead code, parameter bloat, docstrings, unused code, magic numbers' },
  { title: 'Multi-agent fixes', text: 'specialist agents + an independent reviewer; rejected fixes are never presented as usable' },
  { title: 'RAG-grounded scoring', text: 'coding standards retrieved per finding type via a local TF-IDF index; fan-in computed from real import references' },
  { title: 'MCP tool server', text: 'the same 6 tools work in-process or over a real MCP stdio session, path-traversal guarded' },
  { title: 'Self-verifying', text: 'every fix runs the test suite in a sandbox copy — your working tree is never touched' },
  { title: 'Offline eval', text: 'precision / recall / F1 against planted ground-truth debt, no API key required' },
]

/* Stylized pipeline illustration: code file → gauge → diff → roadmap */
function HeroVisual() {
  return (
    <svg viewBox="0 0 520 200" className="w-full max-w-lg" role="img"
      aria-label="Pipeline: source code is scanned, scored, fixed and turned into a roadmap">
      <defs>
        <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0 0.5 L7.5 4 L0 7.5" fill="none" stroke="var(--baseline)" strokeWidth="1.4" />
        </marker>
      </defs>

      {/* code file */}
      <g>
        <rect x="14" y="46" width="108" height="112" rx="10" fill="var(--surface-1)" stroke="var(--grid)" />
        <rect x="30" y="66" width="56" height="6" rx="3" fill="var(--series-1)" opacity="0.85" />
        <rect x="30" y="82" width="76" height="6" rx="3" fill="var(--baseline)" />
        <rect x="42" y="98" width="52" height="6" rx="3" fill="var(--baseline)" />
        <rect x="42" y="114" width="64" height="6" rx="3" fill="var(--status-serious)" opacity="0.9" />
        <rect x="30" y="130" width="44" height="6" rx="3" fill="var(--baseline)" />
      </g>
      <line x1="130" y1="102" x2="176" y2="102" stroke="var(--baseline)" strokeWidth="1.4" markerEnd="url(#arrow)" />

      {/* gauge */}
      <g>
        <rect x="184" y="46" width="108" height="112" rx="10" fill="var(--surface-1)" stroke="var(--grid)" />
        <path d="M 206 128 A 34 34 0 0 1 274 128" fill="none" stroke="var(--grid)" strokeWidth="10" strokeLinecap="round" />
        <path d="M 206 128 A 34 34 0 0 1 252 97" fill="none" stroke="var(--series-1)" strokeWidth="10" strokeLinecap="round" />
        <circle cx="240" cy="128" r="4" fill="var(--text-secondary)" />
        <line x1="240" y1="128" x2="256" y2="106" stroke="var(--text-secondary)" strokeWidth="2.5" strokeLinecap="round" />
      </g>
      <line x1="300" y1="102" x2="346" y2="102" stroke="var(--baseline)" strokeWidth="1.4" markerEnd="url(#arrow)" />

      {/* diff */}
      <g>
        <rect x="354" y="46" width="108" height="112" rx="10" fill="var(--surface-1)" stroke="var(--grid)" />
        <rect x="368" y="66" width="80" height="10" rx="3" fill="var(--diff-del-bg)" />
        <rect x="372" y="68.5" width="34" height="5" rx="2.5" fill="var(--status-critical)" opacity="0.7" />
        <rect x="368" y="82" width="80" height="10" rx="3" fill="var(--diff-add-bg)" />
        <rect x="372" y="84.5" width="48" height="5" rx="2.5" fill="var(--status-good)" opacity="0.75" />
        <rect x="368" y="98" width="80" height="10" rx="3" fill="var(--diff-add-bg)" />
        <rect x="372" y="100.5" width="28" height="5" rx="2.5" fill="var(--status-good)" opacity="0.75" />
        <g transform="translate(430, 128)">
          <circle r="13" fill="var(--status-good)" opacity="0.15" />
          <path d="M -5 0 L -1.5 4 L 6 -4.5" fill="none" stroke="var(--status-good)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
        </g>
      </g>
    </svg>
  )
}

export function LandingPage() {
  const { findings, info, repo, suggestions } = useRepo()
  const repoLabel = suggestions.find(s => s.path === repo)?.label ?? 'your repo'

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-14 py-6">
      {/* hero */}
      <section className="hero-backdrop flex flex-col items-center gap-10 pt-4 lg:flex-row lg:items-center">
        <div className="rise-in flex-1">
          <p className="text-xs font-medium uppercase tracking-widest" style={{ color: 'var(--series-1)' }}>
            agentic tech-debt analysis
          </p>
          <h1 className="mt-4 text-5xl font-semibold leading-[1.1] tracking-tight text-ink">
            Your codebase owes you.
            <br />
            <span className="gradient-ink">Collect the debt.</span>
          </h1>
          <p className="mt-5 max-w-xl text-[15px] leading-7 text-ink-2">
            Code Debt Collector scans a repository for technical debt, has an LLM weigh every
            finding by impact and effort, dispatches specialist agents to propose and
            test-verify fixes, and hands you a prioritized refactoring roadmap — not a lecture.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Link to="/run"
              className="rounded-lg px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
              style={{ background: 'var(--series-1)' }}>
              Scan a repo
            </Link>
            <Link to="/overview"
              className="card-hover rounded-lg border border-edge bg-surface px-5 py-2.5 text-sm font-medium text-ink-2 hover:text-ink">
              View dashboard
            </Link>
          </div>
          {findings.length > 0 && (
            <p className="mt-5 text-xs text-ink-3">
              <span aria-hidden className="mr-1.5 inline-block size-2 rounded-full align-middle" style={{ background: 'var(--status-good)' }} />
              {findings.length} findings currently loaded from <span className="font-medium text-ink-2">{repoLabel}</span>
              {info ? ` (${info.py_files} Python files)` : ''}
            </p>
          )}
        </div>
        <div className="rise-in-late">
          <HeroVisual />
        </div>
      </section>

      {/* pipeline */}
      <section>
        <h2 className="text-center text-xs font-medium uppercase tracking-widest text-ink-3">how it works</h2>
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {STEPS.map((s, i) => (
            <div key={s.n} className="card-hover relative rounded-xl border border-edge bg-surface p-4">
              <div className="flex items-center gap-2.5">
                <span aria-hidden
                  className="flex size-7 items-center justify-center rounded-lg text-sm text-white"
                  style={{ background: 'var(--series-1)' }}>
                  {s.icon}
                </span>
                <span className="text-xs text-ink-3">step {s.n}</span>
              </div>
              <h3 className="mt-3 text-sm font-semibold text-ink">{s.title}</h3>
              <p className="mt-1.5 text-xs leading-5 text-ink-2">{s.text}</p>
              {i < STEPS.length - 1 && (
                <span aria-hidden className="absolute -right-3 top-1/2 hidden -translate-y-1/2 text-ink-3 lg:block">→</span>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* what it finds */}
      <section className="rounded-xl border border-edge bg-surface p-6">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
          <div className="lg:w-64 lg:shrink-0">
            <h2 className="text-sm font-semibold text-ink">What it hunts</h2>
            <p className="mt-1.5 text-xs leading-5 text-ink-2">
              Ten deterministic detectors, each with retrieval-backed coding standards
              the agents consult before proposing a fix.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {FINDING_TYPES.map(t => (
              <span key={t}
                className="inline-flex items-center gap-1.5 rounded-full border border-edge bg-page px-3 py-1.5 text-xs text-ink-2">
                <span aria-hidden className="size-1.5 rounded-full" style={{ background: 'var(--series-1)' }} />
                {typeLabel(t)}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* capabilities — bento: lead cards span wider */}
      <section>
        <h2 className="text-center text-xs font-medium uppercase tracking-widest text-ink-3">under the hood</h2>
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {CAPABILITIES.map((c, i) => (
            <div key={c.title}
              className={`card-hover rounded-xl border border-edge bg-surface p-5 ${
                i === 0 || i === CAPABILITIES.length - 1 ? 'lg:col-span-2' : ''
              }`}>
              <h3 className="text-sm font-semibold text-ink">{c.title}</h3>
              <p className="mt-1.5 text-xs leading-5 text-ink-2">{c.text}</p>
            </div>
          ))}
        </div>
      </section>

      <p className="text-center text-xs text-ink-3">
        Python · FastAPI · React · Mistral / any OpenAI-compatible LLM · local TF-IDF RAG · MCP
      </p>
    </div>
  )
}
