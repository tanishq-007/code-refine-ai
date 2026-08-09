interface Line {
  kind: 'add' | 'del' | 'hunk' | 'meta' | 'ctx'
  text: string
}

function parse(diff: string): Line[] {
  return diff.split('\n').map((text): Line => {
    if (text.startsWith('@@')) return { kind: 'hunk', text }
    if (text.startsWith('+++') || text.startsWith('---') ||
        text.startsWith('diff ') || text.startsWith('index ')) return { kind: 'meta', text }
    if (text.startsWith('+')) return { kind: 'add', text }
    if (text.startsWith('-')) return { kind: 'del', text }
    return { kind: 'ctx', text }
  })
}

const LINE_STYLE: Record<Line['kind'], string> = {
  add: 'bg-[var(--diff-add-bg)] text-ink',
  del: 'bg-[var(--diff-del-bg)] text-ink',
  hunk: 'text-[var(--series-1)] font-medium',
  meta: 'text-ink-3',
  ctx: 'text-ink-2',
}

export function DiffView({ diff }: { diff: string }) {
  const lines = parse(diff)
  return (
    <pre className="log-pane overflow-x-auto rounded-lg border border-edge bg-page p-3 text-xs leading-5">
      {lines.map((l, i) => (
        <div key={i} className={`px-1 whitespace-pre ${LINE_STYLE[l.kind]}`}>
          {l.text || ' '}
        </div>
      ))}
    </pre>
  )
}
