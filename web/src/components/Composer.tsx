import { useState } from 'react'
import type { KeyboardEvent } from 'react'

export function Composer({
  disabled,
  onSend,
}: {
  disabled: boolean
  onSend: (message: string) => void
}) {
  const [value, setValue] = useState('')

  function submit() {
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue('')
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="border-t border-neutral-200 bg-white px-6 py-4">
      <div className="flex items-end gap-3 rounded-xl border border-neutral-300 bg-neutral-50 px-3 py-2 focus-within:border-neutral-400">
        <textarea
          rows={1}
          value={value}
          disabled={disabled}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask a question, or ask about your documents…"
          className="max-h-40 flex-1 resize-none bg-transparent text-[15px] text-neutral-900 outline-none placeholder:text-neutral-400 disabled:opacity-50"
        />
        <button
          type="button"
          onClick={submit}
          disabled={disabled || !value.trim()}
          className="rounded-lg bg-neutral-900 px-4 py-2 text-sm font-medium text-white transition disabled:cursor-not-allowed disabled:opacity-30"
        >
          Send
        </button>
      </div>
    </div>
  )
}
