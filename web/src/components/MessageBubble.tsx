import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'

const markdownComponents: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }) => (
    <ul className="mb-2 list-disc pl-5 last:mb-0">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-2 list-decimal pl-5 last:mb-0">{children}</ol>
  ),
  code: ({ children }) => (
    <code className="rounded bg-neutral-100 px-1 py-0.5 font-mono text-[13px]">
      {children}
    </code>
  ),
  pre: ({ children }) => (
    <pre className="mb-2 overflow-x-auto rounded-lg bg-neutral-900 p-3 font-mono text-[13px] text-neutral-100 last:mb-0">
      {children}
    </pre>
  ),
}

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
      className={`max-w-2xl rounded-2xl px-4 py-3 text-[15px] leading-relaxed ${
        isUser
          ? 'self-end bg-neutral-900 text-white whitespace-pre-wrap'
          : 'self-start bg-white text-neutral-800 shadow-sm ring-1 ring-neutral-200'
      } ${pending ? 'opacity-60' : ''}`}
    >
      {isUser ? (
        content
      ) : (
        <ReactMarkdown components={markdownComponents}>{content}</ReactMarkdown>
      )}
    </div>
  )
}
