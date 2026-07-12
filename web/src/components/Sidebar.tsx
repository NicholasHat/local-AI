import { useRef } from 'react'
import type { DocumentInfo, HealthResponse, ModelInfo } from '../types'
import { ModelPicker } from './ModelPicker'

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function Sidebar({
  open,
  health,
  documents,
  uploading,
  onUpload,
  onReset,
  onRecheckHealth,
  models,
  currentModel,
  switchingModel,
  onSelectModel,
}: {
  open: boolean
  health: HealthResponse | null
  documents: DocumentInfo[]
  uploading: boolean
  onUpload: (file: File) => void
  onReset: () => void
  onRecheckHealth: () => void
  models: ModelInfo[]
  currentModel: string | null
  switchingModel: boolean
  onSelectModel: (name: string) => void
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
            tone: 'text-emerald-700',
            dot: 'bg-emerald-500',
          }

  return (
    <aside
      className={`w-72 shrink-0 border-r border-neutral-200 bg-neutral-50 transition-all duration-200 ${
        open ? 'block' : 'hidden'
      } md:block`}
    >
      <div className="flex h-full flex-col gap-6 overflow-y-auto p-5">
        <div>
          <h1 className="text-lg font-semibold text-neutral-900">
            Local AI Assistant
          </h1>
          <button
            type="button"
            onClick={onRecheckHealth}
            className="mt-2 flex items-center gap-2 text-sm"
          >
            <span className={`h-2 w-2 rounded-full ${statusLabel.dot}`} />
            <span className={statusLabel.tone}>{statusLabel.text}</span>
          </button>
        </div>

        <ModelPicker
          models={models}
          current={currentModel}
          switching={switchingModel}
          onSelect={onSelectModel}
        />

        <div>
          <h2 className="mb-2 text-xs font-semibold tracking-wide text-neutral-500 uppercase">
            Documents
          </h2>
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            disabled={uploading}
            className="w-full rounded-lg border border-dashed border-neutral-300 px-3 py-2 text-sm text-neutral-600 hover:border-neutral-400 disabled:opacity-50"
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
          onClick={onReset}
          className="mt-auto w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm text-neutral-700 hover:bg-neutral-100"
        >
          Clear conversation
        </button>
      </div>
    </aside>
  )
}
