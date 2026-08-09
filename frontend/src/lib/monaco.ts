import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'

/* @monaco-editor/react fetches Monaco from a CDN by default. This project
   is built and tested offline (see README's "Testing notes"), so it's
   pointed at the npm-bundled `monaco-editor` package instead -- the split
   editor works with no network access, same as the rest of the tool. */
loader.config({ monaco })

const LANG_BY_EXT: Record<string, string> = {
  py: 'python', js: 'javascript', jsx: 'javascript', mjs: 'javascript',
  ts: 'typescript', tsx: 'typescript', json: 'json', md: 'markdown',
  css: 'css', html: 'html', yml: 'yaml', yaml: 'yaml', sh: 'shell',
  toml: 'ini', go: 'go', rs: 'rust', java: 'java', c: 'c', h: 'c',
  cpp: 'cpp', hpp: 'cpp', rb: 'ruby', php: 'php', sql: 'sql',
}

export function languageFromPath(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() ?? ''
  return LANG_BY_EXT[ext] ?? 'plaintext'
}

const MIN_PANE_RATIO = 0.2

interface SashLayoutInternals {
  _sashLayout?: {
    sashLeft?: { get(): number; set(value: number, tx: undefined): void }
  }
}

/** Keep each side of a split diff editor at ≥ 20% of its width. Monaco's own
   sash clamp stops at a fixed 100px — on a wide screen that leaves a sliver
   that reads as "one side completely covers the other". Snaps the sash back
   whenever a drag crosses the line. Reaches into the widget's internal
   SashLayout (fine for the pinned monaco-editor version); if a future rename
   hides it, monaco's built-in 100px clamp is the graceful fallback. */
export function clampDiffSash(editor: monaco.editor.IStandaloneDiffEditor) {
  const sashLeft = (editor as unknown as SashLayoutInternals)._sashLayout?.sashLeft
  if (!sashLeft) return
  editor.getOriginalEditor().onDidLayoutChange(() => {
    const total = editor.getContainerDomNode().clientWidth
    if (total <= 0) return
    const lo = total * MIN_PANE_RATIO
    const hi = total * (1 - MIN_PANE_RATIO)
    const left = sashLeft.get()
    if (left < lo) sashLeft.set(lo, undefined)
    else if (left > hi) sashLeft.set(hi, undefined)
  })
}

/* Two Monaco themes mirroring index.css's light/dark tokens exactly (same
   hex values, alpha channels converted to hex suffixes) so the editor reads
   as part of the app rather than a bolted-on widget. */
export function defineEditorThemes(m: typeof monaco) {
  m.editor.defineTheme('cdc-light', {
    base: 'vs',
    inherit: true,
    rules: [
      { token: 'comment', foreground: '898781', fontStyle: 'italic' },
      { token: 'keyword', foreground: '2a78d6' },
      { token: 'string', foreground: '1baf7a' },
      { token: 'number', foreground: 'eda100' },
    ],
    colors: {
      'editor.background': '#fcfcfb',
      'editor.foreground': '#0b0b0b',
      'editorLineNumber.foreground': '#89878199',
      'editorLineNumber.activeForeground': '#52514e',
      'editor.lineHighlightBackground': '#0b0b0b08',
      'editor.lineHighlightBorder': '#00000000',
      'editorCursor.foreground': '#2a78d6',
      'editorIndentGuide.background1': '#0b0b0b12',
      'editorIndentGuide.activeBackground1': '#0b0b0b22',
      'diffEditor.insertedTextBackground': '#0ca30c1a',
      'diffEditor.removedTextBackground': '#d03b3b1a',
      'diffEditor.insertedLineBackground': '#0ca30c10',
      'diffEditor.removedLineBackground': '#d03b3b10',
      'diffEditor.border': '#0b0b0b1a',
      'diffEditor.diagonalFill': '#0b0b0b0d',
      'editorGutter.background': '#fcfcfb',
      'scrollbarSlider.background': '#c3c2b755',
      'scrollbarSlider.hoverBackground': '#c3c2b788',
      'scrollbarSlider.activeBackground': '#c3c2b7aa',
      'editorWidget.background': '#fcfcfb',
      'editorWidget.border': '#0b0b0b1a',
    },
  })

  m.editor.defineTheme('cdc-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'comment', foreground: '898781', fontStyle: 'italic' },
      { token: 'keyword', foreground: '3987e5' },
      { token: 'string', foreground: '199e70' },
      { token: 'number', foreground: 'c98500' },
    ],
    colors: {
      'editor.background': '#1a1a19',
      'editor.foreground': '#ffffff',
      'editorLineNumber.foreground': '#89878199',
      'editorLineNumber.activeForeground': '#c3c2b7',
      'editor.lineHighlightBackground': '#ffffff08',
      'editor.lineHighlightBorder': '#00000000',
      'editorCursor.foreground': '#3987e5',
      'editorIndentGuide.background1': '#ffffff12',
      'editorIndentGuide.activeBackground1': '#ffffff22',
      'diffEditor.insertedTextBackground': '#0ca30c24',
      'diffEditor.removedTextBackground': '#e6676724',
      'diffEditor.insertedLineBackground': '#0ca30c14',
      'diffEditor.removedLineBackground': '#e6676714',
      'diffEditor.border': '#ffffff1a',
      'diffEditor.diagonalFill': '#ffffff0d',
      'editorGutter.background': '#1a1a19',
      'scrollbarSlider.background': '#38383555',
      'scrollbarSlider.hoverBackground': '#38383588',
      'scrollbarSlider.activeBackground': '#383835aa',
      'editorWidget.background': '#1a1a19',
      'editorWidget.border': '#ffffff1a',
    },
  })
}
