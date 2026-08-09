import type {
  FileContent, Finding, FixMap, FixPreview, FixResult, Job, RepoInfo, RepoSuggestion,
  ScoredFinding, Snippet,
} from './types'

async function get<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail ?? `${res.status} ${res.statusText}`)
  }
  return res.json()
}

const q = (params: Record<string, string | number>) =>
  new URLSearchParams(Object.fromEntries(
    Object.entries(params).map(([k, v]) => [k, String(v)]),
  )).toString()

export const api = {
  health: () => get<{ ok: boolean; project_root: string }>('/api/health'),
  repos: () => get<RepoSuggestion[]>('/api/repos'),
  validateRepo: (path: string) => get<RepoInfo>(`/api/repo/validate?${q({ path })}`),

  findings: (repo: string) => get<Finding[]>(`/api/data/findings?${q({ repo })}`),
  scored: (repo: string) => get<ScoredFinding[]>(`/api/data/scored?${q({ repo })}`),
  fixes: (repo: string) => get<FixMap>(`/api/data/fixes?${q({ repo })}`),
  roadmap: (repo: string) =>
    get<{ markdown: string | null; path: string | null }>(`/api/data/roadmap?${q({ repo })}`),
  snippet: (repo: string, path: string, start: number, end: number) =>
    get<Snippet>(`/api/data/snippet?${q({ repo, path, start, end })}`),
  fixPreview: (repo: string, findingId: string) =>
    get<FixPreview>(`/api/data/fix_preview?${q({ repo, finding_id: findingId })}`),
  fileContent: (repo: string, path: string) =>
    get<FileContent>(`/api/data/file?${q({ repo, path })}`),

  jobs: () => get<Job[]>('/api/jobs'),
  job: (id: number) => get<Job>(`/api/jobs/${id}`),
  createJob: async (body: {
    command: string; repo?: string; url?: string; top_n?: number;
    no_fixes?: boolean; no_rag?: boolean; strategy?: string; transport?: string
  }): Promise<Job> => {
    const res = await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => null)
      throw new Error(err?.detail ?? `${res.status} ${res.statusText}`)
    }
    return res.json()
  },

  applyFix: async (repo: string, findingId: string): Promise<{ ok: boolean; log: string }> => {
    const res = await fetch('/api/fixes/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo, finding_id: findingId }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => null)
      throw new Error(err?.detail ?? `${res.status} ${res.statusText}`)
    }
    return res.json()
  },

  createFix: async (
    repo: string, findingId: string, path: string, content: string,
  ): Promise<FixResult> => {
    const res = await fetch('/api/fixes/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo, finding_id: findingId, path, content }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => null)
      throw new Error(err?.detail ?? `${res.status} ${res.statusText}`)
    }
    return res.json()
  },

  updateFix: async (repo: string, findingId: string, content: string): Promise<FixResult> => {
    const res = await fetch('/api/fixes/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo, finding_id: findingId, content }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => null)
      throw new Error(err?.detail ?? `${res.status} ${res.statusText}`)
    }
    return res.json()
  },

  uploadRepo: async (
    items: { file: File; path: string }[],
    name = '',
  ): Promise<{ path: string; files: number }> => {
    const form = new FormData()
    for (const { file, path } of items) {
      form.append('files', file, file.name)
      form.append('paths', path)
    }
    form.append('name', name)
    const res = await fetch('/api/repos/upload', { method: 'POST', body: form })
    if (!res.ok) {
      const err = await res.json().catch(() => null)
      throw new Error(err?.detail ?? `${res.status} ${res.statusText}`)
    }
    return res.json()
  },
}

/** Subscribe to a job's SSE log stream. Returns an unsubscribe function. */
export function streamJob(
  id: number,
  onLine: (line: string) => void,
  onDone: (job: Job) => void,
  onError?: () => void,
): () => void {
  const es = new EventSource(`/api/jobs/${id}/stream`)
  es.onmessage = (ev) => {
    try { onLine(JSON.parse(ev.data).line) } catch { /* skip malformed frame */ }
  }
  es.addEventListener('done', (ev) => {
    es.close()
    try { onDone(JSON.parse((ev as MessageEvent).data)) } catch { /* stream is over either way */ }
  })
  es.onerror = () => { es.close(); onError?.() }
  return () => es.close()
}
