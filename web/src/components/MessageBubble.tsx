export function MessageBubble({
  role,
  content,
  pending = false,
}: {
  role: 'user' | 'assistant'
  content: string
  pending?: boolean
}) {
  const isUser = role === 'user'
  return (
    <div
      className={`max-w-2xl rounded-2xl px-4 py-3 text-[15px] leading-relaxed whitespace-pre-wrap ${
        isUser
          ? 'self-end bg-neutral-900 text-white'
          : 'self-start bg-white text-neutral-800 shadow-sm ring-1 ring-neutral-200'
      } ${pending ? 'opacity-60' : ''}`}
    >
      {content}
    </div>
  )
}
