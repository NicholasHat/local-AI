import { useState } from 'react'

export function ToolEventCard({
  toolName,
  args,
  content,
}: {
  toolName: string
  args?: Record<string, unknown>
  content: string
}) {
  const [expanded, setExpanded] = useState(false)
  const argsText = args && Object.keys(args).length > 0 ? JSON.stringify(args, null, 2) : null

  return (
    <div className="rounded-lg border border-denim-200 bg-denim-50 text-sm">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-denim-800"
      >
        <span aria-hidden>🔧</span>
        <span className="font-medium">{toolName}</span>
        <span className="ml-auto text-xs text-denim-600">
          {expanded ? 'hide' : 'show'}
        </span>
      </button>
      {expanded && (
        <div className="border-t border-denim-200">
          {argsText && (
            <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words px-3 py-2 font-mono text-xs text-denim-900">
              {argsText}
            </pre>
          )}
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words border-t border-denim-100 px-3 py-2 font-mono text-xs text-denim-900">
            {content}
          </pre>
        </div>
      )}
    </div>
  )
}
