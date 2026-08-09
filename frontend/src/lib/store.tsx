import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
  type ReactNode,
} from 'react'
import { api } from './api'
import type { Finding, FixMap, RepoInfo, RepoSuggestion, ScoredFinding } from './types'

/* ---------------------------- theme ---------------------------- */

type Theme = 'light' | 'dark'

const ThemeCtx = createContext<{ theme: Theme; toggle: () => void }>({
  theme: 'light',
  toggle: () => {},
})

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => {
    const fromUrl = new URLSearchParams(window.location.search).get('theme')
    if (fromUrl === 'light' || fromUrl === 'dark') return fromUrl
    const saved = localStorage.getItem('cdc-theme')
    if (saved === 'light' || saved === 'dark') return saved
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  })
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('cdc-theme', theme)
  }, [theme])
  const toggle = useCallback(() => setTheme(t => (t === 'light' ? 'dark' : 'light')), [])
  return <ThemeCtx.Provider value={{ theme, toggle }}>{children}</ThemeCtx.Provider>
}

export const useTheme = () => useContext(ThemeCtx)

/* ------------------------- repo + data ------------------------- */

interface RepoState {
  repo: string
  setRepo: (path: string) => void
  suggestions: RepoSuggestion[]
  reloadRepos: () => void
  info: RepoInfo | null
  findings: Finding[]
  scored: ScoredFinding[]
  fixes: FixMap
  roadmapMd: string | null
  loading: boolean
  error: string | null
  refresh: () => void
}

const RepoCtx = createContext<RepoState | null>(null)

export function RepoProvider({ children }: { children: ReactNode }) {
  const [repo, setRepoState] = useState(() =>
    new URLSearchParams(window.location.search).get('repo')
    ?? localStorage.getItem('cdc-repo') ?? '')
  const [suggestions, setSuggestions] = useState<RepoSuggestion[]>([])
  const [info, setInfo] = useState<RepoInfo | null>(null)
  const [findings, setFindings] = useState<Finding[]>([])
  const [scored, setScored] = useState<ScoredFinding[]>([])
  const [fixes, setFixes] = useState<FixMap>({})
  const [roadmapMd, setRoadmapMd] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  const setRepo = useCallback((path: string) => {
    localStorage.setItem('cdc-repo', path)
    setRepoState(path)
  }, [])

  const refresh = useCallback(() => setTick(t => t + 1), [])

  const reloadRepos = useCallback(() => {
    api.repos().then(s => {
      setSuggestions(s)
      // default to the first suggested repo on first launch
      setRepoState(cur => cur || (s[0]?.path ?? ''))
    }).catch(() => {})
  }, [])

  useEffect(() => { reloadRepos() }, [reloadRepos])

  useEffect(() => {
    if (!repo) return
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([
      api.validateRepo(repo),
      api.findings(repo).catch(() => []),
      api.scored(repo).catch(() => []),
      api.fixes(repo).catch(() => ({})),
      api.roadmap(repo).catch(() => ({ markdown: null, path: null })),
    ]).then(([inf, f, s, fx, rm]) => {
      if (cancelled) return
      setInfo(inf)
      setFindings(f)
      setScored(s)
      setFixes(fx)
      setRoadmapMd(rm.markdown)
    }).catch(e => {
      if (!cancelled) setError(e instanceof Error ? e.message : String(e))
    }).finally(() => {
      if (!cancelled) setLoading(false)
    })
    return () => { cancelled = true }
  }, [repo, tick])

  const value = useMemo(() => ({
    repo, setRepo, suggestions, reloadRepos, info, findings, scored, fixes, roadmapMd,
    loading, error, refresh,
  }), [repo, setRepo, suggestions, reloadRepos, info, findings, scored, fixes, roadmapMd, loading, error, refresh])

  return <RepoCtx.Provider value={value}>{children}</RepoCtx.Provider>
}

export function useRepo(): RepoState {
  const ctx = useContext(RepoCtx)
  if (!ctx) throw new Error('useRepo outside RepoProvider')
  return ctx
}
