import { useState } from 'react'

export function ToolEventCard({
  toolName,
  content,
}: {
  toolName: string
  content: string
}) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="max-w-2xl self-start rounded-lg border border-amber-200 bg-amber-50 text-sm">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-amber-800"
      >
        <span aria-hidden>🔧</span>
        <span className="font-medium">{toolName}</span>
        <span className="ml-auto text-xs text-amber-600">
          {expanded ? 'hide result' : 'show result'}
        </span>
      </button>
      {expanded && (
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words border-t border-amber-200 px-3 py-2 font-mono text-xs text-amber-900">
          {content}
        </pre>
      )}
    </div>
  )
}
