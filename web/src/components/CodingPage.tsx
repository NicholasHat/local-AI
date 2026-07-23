import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../api'
import { formatRelativeTime } from '../format'
import type { CodingRun, CodingRunDetail, CodingStep, ModelInfo } from '../types'
import { ModelPicker } from './ModelPicker'
import { ToolEventCard } from './ToolEventCard'

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

const STATUS_STYLES: Record<string, string> = {
  running: 'bg-denim-100 text-denim-700',
  awaiting_approval: 'bg-amber-100 text-amber-700',
  applied: 'bg-green-100 text-green-700',
  discarded: 'bg-neutral-200 text-neutral-600',
  failed: 'bg-red-100 text-red-700',
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-block shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${
        STATUS_STYLES[status] ?? 'bg-neutral-200 text-neutral-600'
      }`}
    >
      {status.replace('_', ' ')}
    </span>
  )
}

function StepCard({ step }: { step: CodingStep }) {
  const ts = step.ts ? formatRelativeTime(step.ts) : null
  const meta = [step.model, ts].filter(Boolean).join(' · ')

  if (step.type === 'tool_call') {
    return (
      <div className="flex flex-col gap-1">
        <ToolEventCard
          toolName={step.tool ?? 'unknown'}
          args={step.args}
          content={step.result ?? ''}
        />
        {meta && <span className="px-1 text-xs text-neutral-400">{meta}</span>}
      </div>
    )
  }

  const tone =
    step.type === 'error'
      ? 'border-red-200 bg-red-50 text-red-800'
      : step.type === 'stopped'
        ? 'border-amber-200 bg-amber-50 text-amber-800'
        : 'border-neutral-200 bg-white text-neutral-800'
  const icon = step.type === 'error' ? '⛔' : step.type === 'stopped' ? '⏹️' : '🤖'

  return (
    <div className={`flex flex-col gap-1 rounded-lg border px-3 py-2 text-sm ${tone}`}>
      <div className="flex items-center gap-2">
        <span aria-hidden>{icon}</span>
        <span className="font-medium capitalize">{step.type}</span>
        {meta && <span className="ml-auto text-xs text-neutral-400">{meta}</span>}
      </div>
      {step.content && <p className="whitespace-pre-wrap">{step.content}</p>}
    </div>
  )
}

function diffLineClass(line: string): string {
  if (line.startsWith('+++') || line.startsWith('---')) return 'text-neutral-500 font-semibold'
  if (line.startsWith('@@')) return 'text-denim-600'
  if (line.startsWith('+')) return 'bg-green-50 text-green-700'
  if (line.startsWith('-')) return 'bg-red-50 text-red-700'
  return 'text-neutral-700'
}

function DiffViewer({ diff }: { diff: string }) {
  if (!diff.trim()) {
    return <p className="text-sm text-neutral-400">No diff to show yet.</p>
  }
  const lines = diff.split('\n')
  return (
    <div className="overflow-x-auto rounded-lg border border-neutral-200 bg-white">
      <div className="min-w-max p-3 font-mono text-xs leading-relaxed">
        {lines.map((line, i) => (
          <div key={i} className={`whitespace-pre px-1 ${diffLineClass(line)}`}>
            {line.length ? line : ' '}
          </div>
        ))}
      </div>
    </div>
  )
}

export function CodingPage({
  models,
  currentModel,
}: {
  models: ModelInfo[]
  currentModel: string | null
}) {
  const [pastRuns, setPastRuns] = useState<CodingRun[]>([])
  const [repoPath, setRepoPath] = useState('')
  const [instruction, setInstruction] = useState('')
  const [model, setModel] = useState('')
  const [formBusy, setFormBusy] = useState(false)
  const [actionBusy, setActionBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // activeMeta is known the instant a run is started or a past run is
  // clicked; activeDetail (steps + diff) only lands once codingRun(id) has
  // been fetched — while streaming that's deliberately null and the log
  // renders from liveSteps instead (see startWatching below).
  const [activeMeta, setActiveMeta] = useState<CodingRun | null>(null)
  const [activeDetail, setActiveDetail] = useState<CodingRunDetail | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [liveSteps, setLiveSteps] = useState<CodingStep[]>([])
  const [streaming, setStreaming] = useState(false)
  const watchIdRef = useRef<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  const refreshPastRuns = useCallback(async () => {
    setPastRuns(await api.codingRuns())
  }, [])

  useEffect(() => {
    refreshPastRuns().catch((e) => setError(errorMessage(e)))
  }, [refreshPastRuns])

  // Suggest the most recently used repo path once, without ever overwriting
  // what the human is actively typing.
  useEffect(() => {
    setRepoPath((current) => current || (pastRuns[0]?.repo_path ?? current))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pastRuns])

  // Prefer the persisted detail once it's loaded, but fall back to whatever
  // steps we already streamed in this session (activeDetail can be null
  // even for a terminal run — see the GET /coding/runs/{id} 500 note in
  // startWatching below — and re-deriving "no steps" in that case would be
  // dishonest when we watched the run happen).
  const steps = streaming ? liveSteps : (activeDetail?.steps ?? liveSteps)
  // status comes from activeMeta ONLY, never activeDetail: activeMeta is
  // kept fresh on every transition (start, open, and — crucially — right
  // after apply/discard), whereas activeDetail is a best-effort enrichment
  // that can fail independently (see the same 500 note) and, if it failed
  // to refetch after a mutation, would otherwise still hold the pre-mutation
  // status and silently mask the very update the user just made.
  const status = streaming ? 'running' : (activeMeta?.status ?? null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [steps.length])

  function startWatching(runMeta: CodingRun) {
    watchIdRef.current = runMeta.id
    setActiveMeta(runMeta)
    setActiveDetail(null)
    setDetailError(null)
    setLiveSteps([])
    setStreaming(true)

    api
      .codingRunEvents(runMeta.id, (event) => {
        if (watchIdRef.current !== runMeta.id) return
        if (event.type === 'status') return // terminal signal only; detail refetch below is the source of truth
        setLiveSteps((prev) => [...prev, event])
      })
      .catch((e) => {
        if (watchIdRef.current === runMeta.id) setError(errorMessage(e))
      })
      .finally(() => {
        if (watchIdRef.current !== runMeta.id) return
        setStreaming(false)
        // NOTE: the backend has a known gap here — GET /coding/runs/{id} can
        // 500 for a run whose worktree has already been torn down (notably
        // right after apply(), which removes it as its last step). Degrade
        // to the steps/diff we already have rather than surfacing a raw
        // fetch failure as if the run itself had failed.
        api
          .codingRun(runMeta.id)
          .then((detail) => {
            setActiveDetail(detail)
            setDetailError(null)
          })
          .catch((e) => setDetailError(errorMessage(e)))
        refreshPastRuns()
      })
  }

  function openRun(run: CodingRun) {
    setError(null)
    setActiveMeta(run)
    setActiveDetail(null)
    setDetailError(null)
    setLiveSteps([])
    if (run.status === 'running') {
      startWatching(run)
    } else {
      watchIdRef.current = null
      setStreaming(false)
      api
        .codingRun(run.id)
        .then((detail) => {
          setActiveDetail(detail)
          setDetailError(null)
        })
        .catch((e) => setDetailError(errorMessage(e)))
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!repoPath.trim() || !instruction.trim() || formBusy || streaming) return
    setError(null)
    setFormBusy(true)
    try {
      const run = await api.startCodingRun({
        repo_path: repoPath.trim(),
        instruction: instruction.trim(),
        model: model || undefined,
      })
      setInstruction('')
      await refreshPastRuns()
      startWatching(run)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setFormBusy(false)
    }
  }

  // Shared by apply/discard: the mutation itself is the thing that must
  // succeed or fail loudly (setError). The detail refetch afterward is
  // best-effort — see the 500-after-apply note in startWatching — so its
  // failure is reported via detailError, not treated as the action failing.
  async function refreshAfterMutation(id: string, updated: CodingRun) {
    setActiveMeta(updated)
    try {
      setActiveDetail(await api.codingRun(id))
      setDetailError(null)
    } catch (e) {
      setDetailError(errorMessage(e))
    }
    await refreshPastRuns()
  }

  async function handleApply() {
    if (!activeMeta) return
    setActionBusy(true)
    setError(null)
    try {
      const updated = await api.applyCodingRun(activeMeta.id)
      await refreshAfterMutation(activeMeta.id, updated)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setActionBusy(false)
    }
  }

  async function handleDiscard() {
    if (!activeMeta) return
    setActionBusy(true)
    setError(null)
    try {
      const updated = await api.discardCodingRun(activeMeta.id)
      await refreshAfterMutation(activeMeta.id, updated)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setActionBusy(false)
    }
  }

  const canApprove = status === 'awaiting_approval'
  const canDiscard = status === 'awaiting_approval' || status === 'failed'

  return (
    <div className="flex flex-1 overflow-hidden">
      <div className="flex-1 overflow-y-auto px-6 py-8">
        <div className="mx-auto flex max-w-3xl flex-col gap-6">
          <div>
            <h1 className="text-xl font-semibold text-neutral-900">Coding</h1>
            <p className="mt-1 text-sm text-neutral-500">
              Point the agent at a local repo, describe a change, and review a
              diff before anything is applied. It only ever edits inside a
              throwaway git worktree — your working branch is untouched until
              you click Approve.
            </p>
          </div>

          <form
            onSubmit={handleSubmit}
            className="flex flex-col gap-3 rounded-xl border border-neutral-200 bg-white p-5"
          >
            <input
              value={repoPath}
              onChange={(e) => setRepoPath(e.target.value)}
              placeholder="/path/to/repo (inside the allowed coding workspace root)"
              disabled={formBusy}
              className="rounded-md border border-neutral-300 px-3 py-2 text-sm disabled:opacity-50"
            />
            <textarea
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder="Describe the change to make…"
              rows={3}
              disabled={formBusy}
              className="rounded-md border border-neutral-300 px-3 py-2 text-sm disabled:opacity-50"
            />
            <div className="flex items-center justify-between gap-3">
              <ModelPicker
                compact
                models={models}
                current={model || currentModel}
                switching={formBusy}
                onSelect={setModel}
              />
              <button
                type="submit"
                disabled={formBusy || !repoPath.trim() || !instruction.trim()}
                className="rounded-full bg-denim-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-denim-700 disabled:cursor-not-allowed disabled:opacity-30"
              >
                {formBusy ? 'Starting…' : 'Start run'}
              </button>
            </div>
          </form>

          {error && <p className="text-sm text-red-600">{error}</p>}

          {activeMeta && (
            <div className="flex flex-col gap-4 rounded-xl border border-neutral-200 bg-white p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-neutral-900">
                    {activeMeta.instruction}
                  </p>
                  <p className="truncate text-xs text-neutral-500">
                    {activeMeta.repo_path}
                  </p>
                </div>
                {status && <StatusBadge status={status} />}
              </div>

              <div>
                <h2 className="mb-2 text-xs font-semibold tracking-wide text-neutral-500 uppercase">
                  Steps
                </h2>
                <div className="flex max-h-96 flex-col gap-2 overflow-y-auto">
                  {steps.length === 0 && (
                    <p className="text-sm text-neutral-400">
                      {streaming ? 'Waiting for the first step…' : 'No steps recorded.'}
                    </p>
                  )}
                  {steps.map((step, i) => (
                    <StepCard key={i} step={step} />
                  ))}
                  <div ref={bottomRef} />
                </div>
              </div>

              {status === 'failed' && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  This run failed — see the error step above. The worktree is
                  left in place so you can inspect what happened before
                  discarding it.
                </div>
              )}

              <div>
                <h2 className="mb-2 text-xs font-semibold tracking-wide text-neutral-500 uppercase">
                  Diff
                </h2>
                {detailError && !activeDetail && (
                  <p className="mb-2 text-xs text-amber-600">
                    Couldn't load the diff from the server: {detailError}
                  </p>
                )}
                {detailError && activeDetail && (
                  <p className="mb-2 text-xs text-amber-600">
                    Showing the diff from before the last action — the server
                    couldn't refresh it just now: {detailError}
                  </p>
                )}
                <DiffViewer diff={activeDetail?.diff ?? ''} />
              </div>

              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={handleApply}
                  disabled={!canApprove || actionBusy}
                  className="rounded-md bg-denim-600 px-4 py-2 text-sm font-medium text-white hover:bg-denim-700 disabled:opacity-40"
                >
                  Approve
                </button>
                <button
                  type="button"
                  onClick={handleDiscard}
                  disabled={!canDiscard || actionBusy}
                  className="rounded-md border border-neutral-300 px-4 py-2 text-sm hover:bg-neutral-50 disabled:opacity-40"
                >
                  Discard
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      <aside className="hidden w-72 shrink-0 overflow-y-auto border-l border-neutral-200 bg-neutral-50 p-4 lg:block">
        <h2 className="mb-3 text-xs font-semibold tracking-wide text-neutral-500 uppercase">
          Past runs
        </h2>
        <ul className="flex flex-col gap-1">
          {pastRuns.length === 0 && <li className="text-sm text-neutral-400">No runs yet.</li>}
          {pastRuns.map((run) => (
            <li key={run.id}>
              <button
                type="button"
                onClick={() => openRun(run)}
                className={`flex w-full flex-col gap-1 rounded-md px-2 py-2 text-left text-sm ${
                  run.id === activeMeta?.id ? 'bg-denim-100' : 'hover:bg-neutral-100'
                }`}
              >
                <span className="truncate font-medium text-neutral-800">
                  {run.instruction}
                </span>
                <span className="flex items-center justify-between gap-2 text-xs text-neutral-500">
                  <StatusBadge status={run.status} />
                  <span>{formatRelativeTime(run.updated_at)}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </aside>
    </div>
  )
}
