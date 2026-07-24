import { useState } from 'react'
import { api } from '../api'
import { formatBytes } from '../format'
import type { ModelInfo, ModelLibraryEntry, PullProgress } from '../types'

// Ollama streams the same `status` string for many events while only the
// completed/total byte counts advance, so the bar is driven by the byte
// counts (when a layer is downloading) and the status line carries the phase.
function PullProgressPanel({ name, progress }: { name: string; progress: PullProgress | null }) {
  const total = progress?.total
  const completed = progress?.completed ?? 0
  const pct = total ? Math.min(100, Math.round((completed / total) * 100)) : null

  return (
    <div className="mt-3 flex flex-col gap-1.5 rounded-md border border-denim-100 bg-denim-50 p-2.5">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="truncate font-medium text-denim-700">Pulling {name}</span>
        <span className="shrink-0 text-denim-600">
          {progress?.status ?? 'starting…'}
          {pct !== null ? ` · ${pct}%` : ''}
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-denim-100">
        <div
          className={`h-full bg-denim-500 transition-all duration-300 ${
            pct === null ? 'w-1/3 animate-pulse' : ''
          }`}
          style={pct === null ? undefined : { width: `${pct}%` }}
        />
      </div>
      {total ? (
        <span className="text-xs text-neutral-400">
          {formatBytes(completed)} / {formatBytes(total)}
        </span>
      ) : null}
    </div>
  )
}

export function ModelManager({
  open,
  onClose,
  installed,
  library,
  onChanged,
}: {
  open: boolean
  onClose: () => void
  installed: ModelInfo[]
  library: ModelLibraryEntry[]
  onChanged: () => Promise<void>
}) {
  const [customTag, setCustomTag] = useState('')
  const [pulling, setPulling] = useState<string | null>(null)
  const [progress, setProgress] = useState<PullProgress | null>(null)
  const [error, setError] = useState<string | null>(null)

  if (!open) return null

  const installedNames = new Set(installed.map((m) => m.name.split(':')[0]))

  async function pull(name: string) {
    setError(null)
    setPulling(name)
    setProgress(null)
    try {
      await api.pullModel(name, setProgress)
      await onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setPulling(null)
      setProgress(null)
    }
  }

  async function remove(name: string) {
    setError(null)
    try {
      await api.deleteModel(name)
      await onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <>
      <div
        aria-hidden
        onClick={onClose}
        className="fixed inset-0 z-30 bg-neutral-900/20"
      />
      <div className="fixed top-16 right-4 z-40 flex w-80 flex-col gap-3 rounded-xl border border-neutral-200 bg-white p-4 shadow-xl">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-neutral-900">Manage models</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close model manager"
            className="rounded-md p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700"
          >
            ✕
          </button>
        </div>

        <div className="flex flex-col gap-1">
          {installed.map((m) => (
            <div
              key={m.name}
              className="flex items-center justify-between rounded-md px-2 py-1 text-sm text-neutral-700"
            >
              <span className="truncate">{m.name}</span>
              <button
                type="button"
                onClick={() => remove(m.name)}
                className="shrink-0 text-xs text-neutral-400 hover:text-red-600"
                aria-label={`Delete ${m.name}`}
              >
                ✕
              </button>
            </div>
          ))}
        </div>

        <div className="border-t border-neutral-200 pt-3">
          <h3 className="mb-2 text-xs font-semibold tracking-wide text-neutral-500 uppercase">
            Add a model
          </h3>
          <div className="flex flex-col gap-1">
            {library
              .filter((entry) => !installedNames.has(entry.name))
              .map((entry) => (
                <button
                  key={entry.name}
                  type="button"
                  onClick={() => pull(entry.name)}
                  disabled={pulling !== null}
                  className="flex items-center justify-between rounded-md px-2 py-1.5 text-left text-sm hover:bg-denim-50 disabled:opacity-50"
                >
                  <span>
                    {entry.name}
                    {!entry.tool_capable && (
                      <span className="ml-1 text-xs text-neutral-400">(no tools)</span>
                    )}
                  </span>
                  {pulling === entry.name && (
                    <span className="text-xs text-denim-600">pulling…</span>
                  )}
                </button>
              ))}
          </div>

          <div className="mt-2 flex gap-2">
            <input
              value={customTag}
              onChange={(e) => setCustomTag(e.target.value)}
              placeholder="or type any tag…"
              className="min-w-0 flex-1 rounded-md border border-neutral-300 px-2 py-1 text-sm"
            />
            <button
              type="button"
              onClick={() => customTag.trim() && pull(customTag.trim())}
              disabled={pulling !== null || !customTag.trim()}
              className="rounded-md bg-denim-600 px-3 py-1 text-sm font-medium text-white hover:bg-denim-700 disabled:opacity-50"
            >
              Pull
            </button>
          </div>

          {pulling && <PullProgressPanel name={pulling} progress={progress} />}
          {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
        </div>
      </div>
    </>
  )
}
