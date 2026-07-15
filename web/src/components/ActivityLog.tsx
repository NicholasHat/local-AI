import { useEffect, useMemo, useRef } from 'react'
import type { ConversationMessage } from '../types'
import { ToolEventCard } from './ToolEventCard'

type LogEntry = {
  toolName: string
  args?: Record<string, unknown>
  content: string
}

function buildLog(messages: ConversationMessage[]): LogEntry[] {
  const entries: LogEntry[] = []
  const pendingCalls: { name: string; args: Record<string, unknown> }[] = []

  for (const m of messages) {
    if (m.role === 'assistant' && m.tool_calls) {
      for (const call of m.tool_calls) {
        pendingCalls.push({
          name: call.function.name,
          args: call.function.arguments,
        })
      }
    } else if (m.role === 'tool') {
      const call = pendingCalls.shift()
      entries.push({
        toolName: m.tool_name ?? call?.name ?? 'unknown',
        args: call?.args,
        content: m.content ?? '',
      })
    }
  }

  return entries
}

export function ActivityLog({
  open,
  onClose,
  messages,
  thinking,
}: {
  open: boolean
  onClose: () => void
  messages: ConversationMessage[]
  thinking: boolean
}) {
  const log = useMemo(() => buildLog(messages), [messages])
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [open, log.length, thinking])

  return (
    <>
      <div
        aria-hidden
        onClick={onClose}
        className={`fixed inset-0 z-30 bg-neutral-900/20 transition-opacity ${
          open ? 'opacity-100' : 'pointer-events-none opacity-0'
        }`}
      />
      <aside
        className={`fixed top-0 right-0 z-40 flex h-full w-full max-w-md flex-col border-l border-neutral-200 bg-white shadow-xl transition-transform duration-200 ${
          open ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        <div className="flex items-center justify-between border-b border-neutral-200 px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-neutral-900">Activity log</h2>
            <p className="text-xs text-neutral-500">Tool calls the model made this session</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close activity log"
            className="rounded-md p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700"
          >
            ✕
          </button>
        </div>

        <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-4">
          {log.length === 0 && !thinking && (
            <p className="text-sm text-neutral-400">
              No tool activity yet — it'll show up here as the model works.
            </p>
          )}
          {log.map((entry, i) => (
            <ToolEventCard
              key={i}
              toolName={entry.toolName}
              args={entry.args}
              content={entry.content}
            />
          ))}
          {thinking && (
            <div className="rounded-lg border border-denim-200 bg-denim-50 px-3 py-2 text-sm text-denim-700">
              Working…
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </aside>
    </>
  )
}
