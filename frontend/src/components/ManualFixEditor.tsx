import { useEffect, useRef, useState } from 'react'
import { DiffEditor, type DiffOnMount } from '@monaco-editor/react'
import type * as monacoNs from 'monaco-editor'
import { api } from '../lib/api'
import { clampDiffSash, defineEditorThemes, languageFromPath } from '../lib/monaco'
import { useTheme } from '../lib/store'
import { FIX_STATUS_META, fixStatus, type Finding, type FixResult } from '../lib/types'
import { ApplyButton, Spinner, StatusBadge } from './ui'

type ModifiedEditor = ReturnType<Parameters<DiffOnMount>[0]['getModifiedEditor']>

/** Hand-written fix editor for the editor tab: the file as it exists on disk
 *  on the left (read-only), your edit of it on the right. Unlike
 *  SplitFixEditor there's no LLM suggestion to start from -- both panes open
 *  with the disk content and the right pane is yours to change. Saving diffs
 *  the edit against the disk file and verifies it in a sandbox exactly like
 *  a model-proposed fix, so a manual fix earns the same status badge. */
export function ManualFixEditor({ repo, finding, onSaved }: {
  repo: string
  finding: Finding
  onSaved?: (fix: FixResult) => void
}) {
  const { theme } = useTheme()
  const [content, setContent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [savedFix, setSavedFix] = useState<FixResult | null>(null)

  const modifiedRef = useRef<ModifiedEditor | null>(null)
  const baselineRef = useRef<string | null>(null)
  const saveRef = useRef<() => void>(() => {})

  useEffect(() => {
    let cancelled = false
    setContent(null)
    setError(null)
    setLoading(true)
    setDirty(false)
    setSaveError(null)
    setSavedFix(null)
    api.fileContent(repo, finding.file)
      .then(f => {
        if (cancelled) return
        setContent(f.content)
        baselineRef.current = f.content
      })
      .catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [repo, finding.id, finding.file])

  const language = languageFromPath(finding.file)
  const monacoTheme = theme === 'dark' ? 'cdc-dark' : 'cdc-light'

  const handleSave = async () => {
    const modified = modifiedRef.current
    if (!modified || saving) return
    setSaving(true)
    setSaveError(null)
    try {
      const value = modified.getValue()
      const fix = await api.createFix(repo, finding.id, finding.file, value)
      baselineRef.current = value
      setDirty(false)
      setSavedFix(fix)
      onSaved?.(fix)
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }
  saveRef.current = handleSave

  const handleRevert = () => {
    if (content !== null) modifiedRef.current?.setValue(content)
  }

  const handleApplied = () => {
    setSavedFix(prev => {
      const updated = prev ? { ...prev, applied_to_repo: true } : prev
      if (updated) onSaved?.(updated)
      return updated
    })
  }

  const handleMount: DiffOnMount = (editor, monacoInstance: typeof monacoNs) => {
    clampDiffSash(editor)
    const modified = editor.getModifiedEditor()
    modifiedRef.current = modified
    modified.revealLineInCenter(finding.line_start)
    modified.setPosition({ lineNumber: finding.line_start, column: 1 })
    modified.onDidChangeModelContent(() => {
      setDirty(modified.getValue() !== baselineRef.current)
      setSavedFix(null)
    })
    modified.addCommand(monacoInstance.KeyMod.CtrlCmd | monacoInstance.KeyCode.KeyS, () => {
      saveRef.current()
    })
  }

  return (
    <div className="rise-in flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-edge bg-page">
      <div className="flex flex-wrap items-center gap-3 border-b border-edge bg-surface px-3 py-2">
        <span className="truncate font-mono text-xs text-ink-2">
          {finding.file}:{finding.line_start}
        </span>

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
                {saving ? 'Verifying…' : 'Save & verify'}
              </button>
            </>
          ) : savedFix ? (
            <StatusBadge
              kind={FIX_STATUS_META[fixStatus(savedFix)].kind}
              label={FIX_STATUS_META[fixStatus(savedFix)].label}
            />
          ) : (
            <span className="text-ink-3">Editable — write the fix by hand, then save</span>
          )}
        </span>
      </div>

      {!dirty && savedFix && fixStatus(savedFix) === 'verified' && (
        <div className="flex items-center justify-between gap-3 border-b border-edge bg-page px-3 py-2.5">
          {savedFix.applied_to_repo ? (
            <>
              <StatusBadge kind="good" label="Applied to your repo" />
              <span className="text-xs text-ink-3">re-run a scan to refresh the findings</span>
            </>
          ) : (
            <ApplyButton repo={repo} findingId={finding.id} onApplied={handleApplied} />
          )}
        </div>
      )}

      {saveError && (
        <p className="border-b border-edge px-3 py-1.5 text-xs" style={{ color: 'var(--status-critical)' }}>
          Save failed: {saveError}
        </p>
      )}

      {error ? (
        <p className="p-3 text-xs" style={{ color: 'var(--status-critical)' }}>
          Could not load {finding.file}: {error}
        </p>
      ) : loading ? (
        <div className="flex items-center justify-center py-16">
          <Spinner label="Loading file…" />
        </div>
      ) : content !== null ? (
        <div className="min-h-0 flex-1">
          <DiffEditor
            original={content}
            modified={content}
            language={language}
            theme={monacoTheme}
            beforeMount={defineEditorThemes}
            onMount={handleMount}
            options={{
              originalEditable: false,
              readOnly: false,
              renderSideBySide: true,
              useInlineViewWhenSpaceIsLimited: false,
              automaticLayout: true,
              minimap: { enabled: false },
              fontFamily: '"JetBrains Mono", ui-monospace, Consolas, monospace',
              fontSize: 12.5,
              lineHeight: 19,
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
