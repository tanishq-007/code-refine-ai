import { useEffect, useMemo, useRef, useState } from 'react'
import { DiffEditor, type DiffOnMount } from '@monaco-editor/react'
import type * as monacoNs from 'monaco-editor'
import { api } from '../lib/api'
import { clampDiffSash, defineEditorThemes, languageFromPath } from '../lib/monaco'
import { useTheme } from '../lib/store'
import type { FixPreview, FixResult } from '../lib/types'
import { DiffView } from './DiffView'
import { Spinner } from './ui'

type ViewMode = 'split' | 'unified'
type ModifiedEditor = ReturnType<Parameters<DiffOnMount>[0]['getModifiedEditor']>

const MIN_HEIGHT = 160
const MAX_HEIGHT = 560
const LINE_HEIGHT = 19

function diffStats(diff: string) {
  let add = 0
  let del = 0
  for (const line of diff.split('\n')) {
    if (line.startsWith('+++') || line.startsWith('---')) continue
    if (line.startsWith('+')) add++
    else if (line.startsWith('-')) del++
  }
  return { add, del }
}

/** Split-screen "before / after" code editor for a proposed fix, backed by
 *  Monaco's diff editor: the original file on the left (read-only), the
 *  LLM's suggested fix on the right -- fully editable, so the suggestion is
 *  a starting point, not the final word. Saving rebuilds the diff from
 *  whatever's in the right pane and re-verifies it in a sandbox exactly like
 *  a model-proposed fix, so an edit can't claim "tests pass" without proof.
 *  Falls back to the plain unified-diff view if the live preview can't be
 *  reconstructed (e.g. the source file has since changed). */
export function SplitFixEditor({ repo, findingId, diff, onSaved }: {
  repo: string
  findingId: string
  diff: string
  onSaved?: (fix: FixResult) => void
}) {
  const { theme } = useTheme()
  const [mode, setMode] = useState<ViewMode>('split')
  const [preview, setPreview] = useState<FixPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [height, setHeight] = useState(280)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [savedFlash, setSavedFlash] = useState(false)

  const modifiedRef = useRef<ModifiedEditor | null>(null)
  const baselineRef = useRef<string | null>(null)
  const saveRef = useRef<() => void>(() => {})

  useEffect(() => {
    let cancelled = false
    setPreview(null)
    setError(null)
    setLoading(true)
    setMode('split')
    setDirty(false)
    setSaveError(null)
    api.fixPreview(repo, findingId)
      .then(p => {
        if (cancelled) return
        setPreview(p)
        baselineRef.current = p.modified
      })
      .catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [repo, findingId])

  const stats = useMemo(() => diffStats(diff), [diff])
  const canSplit = !error && !!preview
  const language = preview ? languageFromPath(preview.path) : 'plaintext'
  const monacoTheme = theme === 'dark' ? 'cdc-dark' : 'cdc-light'

  const handleSave = async () => {
    const modified = modifiedRef.current
    if (!modified || saving) return
    setSaving(true)
    setSaveError(null)
    try {
      const content = modified.getValue()
      const updated = await api.updateFix(repo, findingId, content)
      const fresh = await api.fixPreview(repo, findingId)
      setPreview(fresh)
      baselineRef.current = fresh.modified
      setDirty(false)
      setSavedFlash(true)
      setTimeout(() => setSavedFlash(false), 2200)
      onSaved?.(updated)
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }
  saveRef.current = handleSave

  const handleRevert = () => {
    if (preview) modifiedRef.current?.setValue(preview.modified)
  }

  const handleMount: DiffOnMount = (editor, monacoInstance: typeof monacoNs) => {
    clampDiffSash(editor)
    const modified = editor.getModifiedEditor()
    modifiedRef.current = modified
    const resize = () => {
      const lines = modified.getModel()?.getLineCount() ?? 12
      setHeight(Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, lines * LINE_HEIGHT + 28)))
    }
    resize()
    editor.onDidUpdateDiff(resize)
    modified.onDidChangeModelContent(() => {
      setDirty(modified.getValue() !== baselineRef.current)
    })
    modified.addCommand(monacoInstance.KeyMod.CtrlCmd | monacoInstance.KeyCode.KeyS, () => {
      saveRef.current()
    })
  }

  return (
    <div className="rise-in overflow-hidden rounded-xl border border-edge bg-page">
      <div className="flex flex-wrap items-center gap-3 border-b border-edge bg-surface px-3 py-2">
        <span className="truncate font-mono text-xs text-ink-2">
          {preview?.path ?? (loading ? 'Loading file…' : 'Preview unavailable')}
        </span>
        <span className="flex items-center gap-2 text-xs font-medium tabular-nums">
          <span style={{ color: 'var(--status-good)' }}>+{stats.add}</span>
          <span style={{ color: 'var(--status-critical)' }}>-{stats.del}</span>
        </span>

        {canSplit && mode === 'split' && (
          <span className="flex items-center gap-2 text-xs">
            {dirty ? (
              <>
                <span className="text-ink-3">Edited</span>
                <button
                  type="button"
                  onClick={handleRevert}
                  className="text-ink-3 underline decoration-dotted hover:text-ink-2"
                >
                  Revert
                </button>
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={saving}
                  className="rounded-full px-2.5 py-1 font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60"
                  style={{ background: 'var(--series-1)' }}
                >
                  {saving ? 'Verifying…' : 'Save & re-verify'}
                </button>
              </>
            ) : savedFlash ? (
              <span style={{ color: 'var(--status-good)' }}>✓ Saved &amp; re-verified</span>
            ) : (
              <span className="text-ink-3">Editable — tweak the suggestion, then save</span>
            )}
          </span>
        )}

        <div className="ml-auto inline-flex rounded-full border border-edge bg-page p-0.5 text-xs">
          {(['split', 'unified'] as const).map(m => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              disabled={m === 'split' && !canSplit}
              className={`rounded-full px-2.5 py-1 font-medium capitalize transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                mode === m ? 'bg-surface text-ink shadow-sm' : 'text-ink-3 hover:text-ink-2'
              }`}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      {saveError && (
        <p className="border-b border-edge px-3 py-1.5 text-xs" style={{ color: 'var(--status-critical)' }}>
          Save failed: {saveError}
        </p>
      )}

      {mode === 'unified' || error ? (
        <div className="p-3">
          {error && (
            <p className="mb-2 text-xs text-ink-3">
              Live before/after preview unavailable ({error}) — showing the unified diff.
            </p>
          )}
          <DiffView diff={diff} />
        </div>
      ) : loading ? (
        <div className="flex items-center justify-center py-16">
          <Spinner label="Reconstructing before / after…" />
        </div>
      ) : preview ? (
        <div style={{ height }} className="transition-[height] duration-300 ease-out">
          <DiffEditor
            original={preview.original}
            modified={preview.modified}
            language={language}
            theme={monacoTheme}
            beforeMount={defineEditorThemes}
            onMount={handleMount}
            options={{
              originalEditable: false,
              readOnly: false,
              renderSideBySide: true,
              useInlineViewWhenSpaceIsLimited: false,
              minimap: { enabled: false },
              fontFamily: '"JetBrains Mono", ui-monospace, Consolas, monospace',
              fontSize: 12.5,
              lineHeight: LINE_HEIGHT,
              scrollBeyondLastLine: false,
              renderOverviewRuler: false,
              folding: false,
              smoothScrolling: true,
              cursorSmoothCaretAnimation: 'on',
              padding: { top: 10, bottom: 10 },
              renderLineHighlight: 'line',
              diffAlgorithm: 'advanced',
            }}
          />
        </div>
      ) : null}
    </div>
  )
}
