import { useRef } from 'react'
import type { DocumentInfo, HealthResponse } from '../types'

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export type View = 'chat' | 'skills'

function NavButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean
  onClick: () => void
  icon: string
  label: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm font-medium transition ${
        active
          ? 'bg-denim-100 text-denim-800'
          : 'text-neutral-600 hover:bg-neutral-100'
      }`}
    >
      <span aria-hidden>{icon}</span>
      {label}
    </button>
  )
}

export function Sidebar({
  open,
  view,
  onChangeView,
  health,
  documents,
  uploading,
  onUpload,
  onNewChat,
  onRecheckHealth,
}: {
  open: boolean
  view: View
  onChangeView: (view: View) => void
  health: HealthResponse | null
  documents: DocumentInfo[]
  uploading: boolean
  onUpload: (file: File) => void
  onNewChat: () => void
  onRecheckHealth: () => void
}) {
  const fileInput = useRef<HTMLInputElement>(null)

  const statusLabel = !health
    ? { text: 'Checking…', tone: 'text-neutral-400', dot: 'bg-neutral-300' }
    : !health.healthy
      ? {
          text: 'Ollama not reachable',
          tone: 'text-red-600',
          dot: 'bg-red-500',
        }
      : !health.model
        ? {
            text: 'Set OLLAMA_MODEL',
            tone: 'text-amber-600',
            dot: 'bg-amber-500',
          }
        : {
            text: `Connected · ${health.model}`,
            tone: 'text-denim-700',
            dot: 'bg-denim-500',
          }

  return (
    <aside
      className={`w-64 shrink-0 border-r border-neutral-200 bg-neutral-50 transition-all duration-200 ${
        open ? 'block' : 'hidden'
      } md:block`}
    >
      <div className="flex h-full flex-col gap-5 p-4">
        <h1 className="px-1 text-lg font-semibold text-neutral-900">
          Local AI Assistant
        </h1>

        <button
          type="button"
          onClick={onNewChat}
          className="flex w-full items-center gap-2 rounded-lg border border-neutral-300 bg-white px-2.5 py-2 text-sm font-medium text-neutral-800 hover:bg-neutral-100"
        >
          <span aria-hidden>+</span> New chat
        </button>

        <nav className="flex flex-col gap-1">
          <NavButton
            active={view === 'chat'}
            onClick={() => onChangeView('chat')}
            icon="💬"
            label="Chat"
          />
          <NavButton
            active={view === 'skills'}
            onClick={() => onChangeView('skills')}
            icon="⚙️"
            label="Skills"
          />
        </nav>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <h2 className="mb-2 text-xs font-semibold tracking-wide text-neutral-500 uppercase">
            Documents
          </h2>
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            disabled={uploading}
            className="w-full rounded-lg border border-dashed border-neutral-300 px-3 py-2 text-sm text-neutral-600 hover:border-denim-400 disabled:opacity-50"
          >
            {uploading ? 'Indexing…' : 'Upload a PDF'}
          </button>
          <input
            ref={fileInput}
            type="file"
            accept="application/pdf"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) onUpload(file)
              e.target.value = ''
            }}
          />

          <ul className="mt-3 flex flex-col gap-1">
            {documents.length === 0 && (
              <li className="text-sm text-neutral-400">
                No documents uploaded yet.
              </li>
            )}
            {documents.map((doc) => (
              <li
                key={doc.filename}
                className="flex items-center justify-between rounded-md px-2 py-1 text-sm text-neutral-700"
                title={doc.filename}
              >
                <span className="truncate">{doc.filename}</span>
                <span className="ml-2 shrink-0 text-xs text-neutral-400">
                  {formatSize(doc.size_bytes)}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <button
          type="button"
          onClick={onRecheckHealth}
          className="flex items-center gap-2 border-t border-neutral-200 pt-3 text-sm"
        >
          <span className={`h-2 w-2 rounded-full ${statusLabel.dot}`} />
          <span className={statusLabel.tone}>{statusLabel.text}</span>
        </button>
      </div>
    </aside>
  )
}
