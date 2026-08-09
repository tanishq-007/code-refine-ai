export interface Finding {
  type: string
  file: string
  line_start: number
  line_end: number
  description: string
  symbol: string | null
  metric: Record<string, unknown> | null
  evidence: string | null
  severity: string | null
  id: string
}

export interface ScoredFinding extends Finding {
  impact: number
  effort: number
  ratio: number
  justification: string
}

export interface Review {
  verdict: 'approve' | 'reject' | 'revise' | 'skipped' | string
  rationale?: string
}

export interface FixResult {
  applied: boolean
  tests_passed: boolean | null
  diff: string | null
  agent?: string
  routing_reason?: string
  planner_order?: number
  planner_group?: string
  error?: string
  review?: Review
  retry?: string
  retry_used?: boolean
  applied_to_repo?: boolean
  applied_at?: number
  edited_by_user?: boolean
}

export type FixMap = Record<string, FixResult>

export interface Job {
  id: number
  command: string
  repo: string
  status: 'running' | 'succeeded' | 'failed'
  returncode: number | null
  started_at: number
  finished_at: number | null
  line_count: number
  lines?: string[]
}

export interface RepoInfo {
  ok: boolean
  path: string
  py_files: number
  has_findings: boolean
  has_scored: boolean
  has_fixes: boolean
  has_roadmap: boolean
}

export interface RepoSuggestion {
  label: string
  path: string
}

export interface Snippet {
  path: string
  line_start: number
  line_end: number
  total_lines: number
  lines: string[]
}

export interface FixPreview {
  path: string
  original: string
  modified: string
}

export interface FileContent {
  path: string
  content: string
}

export type Tier = 'do-now' | 'plan' | 'backlog'

/* Mirrors agent/roadmap.py::_tier */
export function tierOf(impact: number, ratio: number): Tier {
  if (impact >= 3 && ratio >= 2.0) return 'do-now'
  if (ratio >= 1.0) return 'plan'
  return 'backlog'
}

export const TIER_META: Record<Tier, { label: string; blurb: string }> = {
  'do-now': { label: 'Do now', blurb: 'high impact / low effort' },
  plan: { label: 'Plan', blurb: 'balanced impact/effort' },
  backlog: { label: 'Backlog', blurb: 'low ratio — nice to have' },
}

/* Mirrors agent/roadmap.py::_rejected */
export function isRejected(fix: FixResult): boolean {
  if (fix.retry_used) return false
  return fix.review?.verdict === 'reject'
}

export type FixStatus = 'error' | 'rejected' | 'verified' | 'tests-failed' | 'not-applied'

export function fixStatus(fix: FixResult): FixStatus {
  if (fix.error) return 'error'
  if (isRejected(fix)) return 'rejected'
  if (fix.tests_passed) return 'verified'
  if (fix.applied) return 'tests-failed'
  return 'not-applied'
}

export const FIX_STATUS_META: Record<FixStatus, { label: string; kind: 'good' | 'warning' | 'critical' | 'muted' }> = {
  verified: { label: 'Tests pass', kind: 'good' },
  'tests-failed': { label: 'Applied, tests failed', kind: 'warning' },
  rejected: { label: 'Reviewer rejected', kind: 'critical' },
  'not-applied': { label: 'Did not apply', kind: 'muted' },
  error: { label: 'Agent error', kind: 'critical' },
}

export const FINDING_TYPES = [
  'high_complexity', 'long_function', 'duplication', 'missing_tests',
  'dead_code', 'long_parameter_list', 'missing_docstring', 'unused_import',
  'unused_variable', 'magic_number',
] as const

export function typeLabel(t: string): string {
  return t.replace(/_/g, ' ')
}
