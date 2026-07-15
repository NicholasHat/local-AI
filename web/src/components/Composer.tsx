import { useLayoutEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import type { ModelInfo } from '../types'
import { ModelPicker } from './ModelPicker'

const MIN_HEIGHT = 52
const MAX_HEIGHT = 240

export function Composer({
  disabled,
  onSend,
  models,
  currentModel,
  switchingModel,
  onSelectModel,
}: {
  disabled: boolean
  onSend: (message: string) => void
  models: ModelInfo[]
  currentModel: string | null
  switchingModel: boolean
  onSelectModel: (name: string) => void
}) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useLayoutEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(Math.max(el.scrollHeight, MIN_HEIGHT), MAX_HEIGHT)}px`
  }, [value])

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
      <div className="mx-auto flex max-w-3xl flex-col gap-2 rounded-2xl border border-neutral-300 bg-neutral-50 px-3 py-2 focus-within:border-denim-400">
        <textarea
          ref={textareaRef}
          rows={1}
          value={value}
          disabled={disabled}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask a question, or ask about your documents…"
          style={{ height: MIN_HEIGHT }}
          className="w-full resize-none overflow-y-auto bg-transparent px-1 py-1 text-[15px] text-neutral-900 outline-none transition-[height] duration-100 placeholder:text-neutral-400 disabled:opacity-50"
        />
        <div className="flex items-center justify-between gap-3">
          <ModelPicker
            compact
            models={models}
            current={currentModel}
            switching={switchingModel}
            onSelect={onSelectModel}
          />
          <button
            type="button"
            onClick={submit}
            disabled={disabled || !value.trim()}
            className="rounded-full bg-denim-600 px-4 py-1.5 text-sm font-medium text-white transition hover:bg-denim-700 disabled:cursor-not-allowed disabled:opacity-30"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  )
}
