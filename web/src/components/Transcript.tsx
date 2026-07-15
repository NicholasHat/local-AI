import { useEffect, useRef } from 'react'
import type { ConversationMessage } from '../types'
import { MessageBubble } from './MessageBubble'

export function Transcript({
  messages,
  pendingMessage,
  thinking,
}: {
  messages: ConversationMessage[]
  pendingMessage: string | null
  thinking: boolean
}) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, pendingMessage, thinking])

  const rendered = messages.filter(
    (m): m is ConversationMessage & { role: 'user' | 'assistant' } =>
      (m.role === 'user' || m.role === 'assistant') && !!m.content,
  )

  if (rendered.length === 0 && !pendingMessage) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center text-neutral-400">
        <p className="text-lg font-medium text-neutral-500">
          Ask a question, or upload a document to chat with it.
        </p>
        <p className="text-sm">
          Everything runs locally through Ollama — nothing leaves this machine.
        </p>
      </div>
    )
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-3 overflow-y-auto px-6 py-6">
      {rendered.map((m, i) => (
        <MessageBubble key={i} role={m.role} content={m.content ?? ''} />
      ))}
      {pendingMessage && (
        <MessageBubble role="user" content={pendingMessage} pending />
      )}
      {thinking && (
        <div className="self-start rounded-2xl bg-white px-4 py-3 text-sm text-neutral-400 shadow-sm ring-1 ring-neutral-200">
          Thinking…
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  )
}
