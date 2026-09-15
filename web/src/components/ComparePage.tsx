import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import { api } from '../api'
import { formatRelativeTime } from '../format'
import type {
  ArenaAnswer,
  ArenaVerdict,
  BenchCategory,
  BenchResult,
  BenchSuite,
  BenchTaskEvent,
  Job,
  JobEvent,
  JobStatus,
  JobStatusEvent,
  JobSummary,
  LeaderboardRow,
  ModelInfo,
} from '../types'

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

const CATEGORIES: BenchCategory[] = [
  'reasoning',
  'coding',
  'instruction',
  'tools',
  'json',
  'knowledge',
]

const markdownComponents: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-2 list-disc pl-5 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 list-decimal pl-5 last:mb-0">{children}</ol>,
  code: ({ children }) => (
    <code className="rounded bg-neutral-100 px-1 py-0.5 font-mono text-[13px]">{children}</code>
  ),
  pre: ({ children }) => (
    <pre className="mb-2 overflow-x-auto rounded-lg bg-neutral-900 p-3 font-mono text-[13px] text-neutral-100 last:mb-0">
      {children}
    </pre>
  ),
}

const STATUS_STYLES: Record<string, string> = {
  running: 'bg-denim-100 text-denim-700',
  succeeded: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-block shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${
        STATUS_STYLES[status] ?? 'bg-neutral-200 text-neutral-600'
      }`}
    >
      {status}
    </span>
  )
}

function pct(value: number | undefined | null): string {
  return value === undefined || value === null ? '–' : `${Math.round(value * 100)}%`
}

function num(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? '–' : value.toFixed(digits)
}

function ScoreBar({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-neutral-200">
        <div className="h-full bg-denim-500" style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
      <span className="tabular-nums">{pct(value)}</span>
    </div>
  )
}

function ModelSelect({
  models,
  value,
  onChange,
  allowAll = false,
}: {
  models: ModelInfo[]
  value: string
  onChange: (v: string) => void
  allowAll?: boolean
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-lg border border-neutral-300 bg-white px-2.5 py-1.5 text-sm text-neutral-800"
    >
      {allowAll && <option value="">Choose a model…</option>}
      {models.map((m) => (
        <option key={m.name} value={m.name}>
          {m.name}
          {m.tool_capable ? '' : ' (no tools)'}
        </option>
      ))}
    </select>
  )
}

const inputClass =
  'rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm text-neutral-800 focus:border-denim-400 focus:outline-none'
const primaryButton =
  'rounded-lg bg-denim-600 px-3.5 py-1.5 text-sm font-medium text-white hover:bg-denim-700 disabled:opacity-50'
const secondaryButton =
  'rounded-lg border border-neutral-300 bg-white px-3 py-1.5 text-sm font-medium text-neutral-700 hover:bg-neutral-100 disabled:opacity-50'

// Shared "watch a job" hook: start streaming a job's events, then refetch
// the persisted record when the stream reports a terminal status — the
// same start → stream → refetch shape CodingPage uses for coding runs.
function useJobWatch(kind: 'bench' | 'arena') {
  const [job, setJob] = useState<Job | null>(null)
  const [liveEvents, setLiveEvents] = useState<JobEvent[]>([])
  const [liveStatus, setLiveStatus] = useState<JobStatus | null>(null)
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const watchIdRef = useRef<string | null>(null)
  // One live stream at most: starting a new watch, closing, or unmounting
  // aborts the previous fetch so it releases its connection instead of
  // reading silently until the job ends.
  const abortRef = useRef<AbortController | null>(null)

  const abortStream = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
  }, [])

  useEffect(() => abortStream, [abortStream])

  const watch = useCallback(
    (summary: JobSummary, onDone?: () => void) => {
      abortStream()
      const controller = new AbortController()
      abortRef.current = controller
      watchIdRef.current = summary.id
      setJob({ ...summary, events: [], result: null })
      setLiveEvents([])
      setLiveStatus(summary.status)
      setStreaming(true)
      setError(null)
      api
        .jobEvents(
          kind,
          summary.id,
          (event) => {
            if (watchIdRef.current !== summary.id) return
            if (event.type === 'status') {
              const statusEvent = event as JobStatusEvent
              setLiveStatus(statusEvent.status)
              if (statusEvent.error) setError(statusEvent.error)
              return
            }
            setLiveEvents((prev) => [...prev, event as JobEvent])
          },
          controller.signal,
        )
        .catch((e) => {
          if (watchIdRef.current === summary.id) setError(errorMessage(e))
        })
        .finally(() => {
          if (watchIdRef.current !== summary.id) return
          setStreaming(false)
          api
            .job(kind, summary.id)
            .then((full) => {
              if (watchIdRef.current === summary.id) setJob(full)
            })
            .catch((e) => setError(errorMessage(e)))
            .finally(() => onDone?.())
        })
    },
    [kind, abortStream],
  )

  const open = useCallback(
    (summary: JobSummary) => {
      if (summary.status === 'running') {
        watch(summary)
        return
      }
      abortStream()
      watchIdRef.current = summary.id
      setStreaming(false)
      setLiveEvents([])
      setLiveStatus(summary.status)
      setError(null)
      setJob({ ...summary, events: [], result: null })
      api
        .job(kind, summary.id)
        .then((full) => {
          if (watchIdRef.current === summary.id) setJob(full)
        })
        .catch((e) => setError(errorMessage(e)))
    },
    [kind, watch, abortStream],
  )

  const close = useCallback(() => {
    abortStream()
    watchIdRef.current = null
    setJob(null)
    setLiveEvents([])
    setLiveStatus(null)
    setStreaming(false)
    setError(null)
  }, [abortStream])

  const events = streaming || job?.events.length === 0 ? liveEvents : (job?.events ?? liveEvents)
  const status: JobStatus | null = streaming ? 'running' : (liveStatus ?? job?.status ?? null)
  return { job, events, status, streaming, error, setError, watch, open, close }
}

function JobHistory({
  jobs,
  activeId,
  onOpen,
  onDelete,
  label,
}: {
  jobs: JobSummary[]
  activeId: string | null
  onOpen: (job: JobSummary) => void
  onDelete: (job: JobSummary) => void
  label: (job: JobSummary) => string
}) {
  if (jobs.length === 0) {
    return <p className="text-sm text-neutral-400">No past runs yet.</p>
  }
  return (
    <ul className="flex flex-col gap-1">
      {jobs.map((j) => (
        <li
          key={j.id}
          className={`group flex items-center gap-2 rounded-md px-2 py-1.5 text-sm ${
            j.id === activeId ? 'bg-denim-100 text-denim-800' : 'text-neutral-700 hover:bg-neutral-100'
          }`}
        >
          <button
            type="button"
            onClick={() => onOpen(j)}
            className="flex min-w-0 flex-1 items-center gap-2 text-left"
          >
            <span className="truncate">{label(j)}</span>
            <span className="ml-auto shrink-0 text-xs text-neutral-400">
              {formatRelativeTime(j.updated_at)}
            </span>
            <StatusBadge status={j.status} />
          </button>
          <button
            type="button"
            onClick={() => onDelete(j)}
            className="shrink-0 text-xs text-neutral-400 opacity-0 group-hover:opacity-100 hover:text-red-600"
            aria-label="Delete run"
            disabled={j.status === 'running'}
          >
            ✕
          </button>
        </li>
      ))}
    </ul>
  )
}

// --- Leaderboard & benchmarks ------------------------------------------------

function TaskRow({
  id,
  category,
  passed,
  seconds,
  answer,
  expected,
  error,
}: {
  id: string
  category: string
  passed: boolean
  seconds: number
  answer: string
  expected: string
  error?: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <li className="rounded-md border border-neutral-200 bg-white text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left"
      >
        <span className={passed ? 'text-green-600' : 'text-red-600'}>{passed ? '✓' : '✗'}</span>
        <span className="font-medium text-neutral-800">{id}</span>
        <span className="rounded-full bg-neutral-100 px-1.5 py-0.5 text-neutral-500">{category}</span>
        <span className="ml-auto tabular-nums text-neutral-400">{num(seconds)}s</span>
      </button>
      {open && (
        <div className="grid gap-2 border-t border-neutral-100 px-2.5 py-2 sm:grid-cols-2">
          <div>
            <p className="mb-1 font-semibold text-neutral-500 uppercase">Answer</p>
            <p className="whitespace-pre-wrap text-neutral-700">{error ? `Error: ${error}` : answer || '(empty)'}</p>
          </div>
          <div>
            <p className="mb-1 font-semibold text-neutral-500 uppercase">Expected</p>
            <p className="whitespace-pre-wrap text-neutral-700">{expected}</p>
          </div>
        </div>
      )}
    </li>
  )
}

function LeaderboardTable({
  rows,
  expanded,
  onToggle,
  details,
}: {
  rows: LeaderboardRow[]
  expanded: string | null
  onToggle: (model: string) => void
  details: BenchResult | null
}) {
  if (rows.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-neutral-300 px-4 py-6 text-center text-sm text-neutral-400">
        No benchmark results yet — run one to rank your installed models.
      </p>
    )
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-neutral-200 bg-white">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-neutral-200 text-left text-xs font-semibold tracking-wide text-neutral-500 uppercase">
            <th className="px-3 py-2">Model</th>
            <th className="px-3 py-2">Overall</th>
            {CATEGORIES.map((c) => (
              <th key={c} className="px-2 py-2">
                {c}
              </th>
            ))}
            <th className="px-2 py-2">tok/s</th>
            <th className="px-2 py-2">load</th>
            <th className="px-2 py-2">ran</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <Fragment key={row.model}>
              <tr
                onClick={() => onToggle(row.model)}
                className={`cursor-pointer border-b border-neutral-100 hover:bg-neutral-50 ${
                  expanded === row.model ? 'bg-denim-50' : ''
                }`}
              >
                <td className="px-3 py-2 font-medium text-neutral-800">
                  {row.model}
                  {!row.tool_capable && (
                    <span className="ml-1.5 rounded-full bg-amber-100 px-1.5 py-0.5 text-xs text-amber-700">
                      no tools
                    </span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <ScoreBar value={row.overall} />
                </td>
                {CATEGORIES.map((c) => (
                  <td key={c} className="px-2 py-2 tabular-nums text-neutral-700">
                    {pct(row.categories[c])}
                  </td>
                ))}
                <td className="px-2 py-2 tabular-nums text-neutral-700">{num(row.tokens_per_sec)}</td>
                <td className="px-2 py-2 tabular-nums text-neutral-700">
                  {row.load_seconds === null ? '–' : `${num(row.load_seconds)}s`}
                </td>
                <td className="px-2 py-2 text-xs text-neutral-400">{formatRelativeTime(row.ran_at)}</td>
              </tr>
              {expanded === row.model && (
                <tr className="border-b border-neutral-100 bg-neutral-50">
                  <td colSpan={CATEGORIES.length + 5} className="px-3 py-3">
                    {details && details.model === row.model ? (
                      <ul className="flex flex-col gap-1">
                        {details.tasks.map((t) => (
                          <TaskRow key={t.id} {...t} />
                        ))}
                      </ul>
                    ) : (
                      <p className="text-xs text-neutral-400">Loading task results…</p>
                    )}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SuiteSection({ suite }: { suite: BenchSuite | null }) {
  const [open, setOpen] = useState(false)
  return (
    <section className="rounded-lg border border-neutral-200 bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium text-neutral-800"
      >
        <span>
          Suite {suite ? `v${suite.version} · ${suite.tasks.length} tasks` : ''}
        </span>
        <span className="text-neutral-400">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="grid gap-4 border-t border-neutral-100 px-4 py-3 sm:grid-cols-2">
          {!suite ? (
            <p className="text-sm text-neutral-400">Loading…</p>
          ) : (
            CATEGORIES.map((c) => (
              <div key={c}>
                <p className="mb-1 text-xs font-semibold tracking-wide text-neutral-500 uppercase">{c}</p>
                <ul className="flex flex-col gap-1">
                  {suite.tasks
                    .filter((t) => t.category === c)
                    .map((t) => (
                      <li key={t.id} className="rounded-md bg-neutral-50 px-2 py-1.5 text-xs text-neutral-700">
                        <span className="font-medium text-neutral-800">{t.id}</span>
                        <span className="ml-1.5 text-neutral-400">{t.check_type}</span>
                        <p className="mt-0.5 line-clamp-2 text-neutral-600">{t.prompt}</p>
                      </li>
                    ))}
                </ul>
              </div>
            ))
          )}
        </div>
      )}
    </section>
  )
}

function BenchTab({
  models,
  initialJobId,
}: {
  models: ModelInfo[]
  initialJobId: string | null
}) {
  const [rows, setRows] = useState<LeaderboardRow[]>([])
  const [suite, setSuite] = useState<BenchSuite | null>(null)
  const [history, setHistory] = useState<JobSummary[]>([])
  const [expanded, setExpanded] = useState<string | null>(null)
  const [details, setDetails] = useState<BenchResult | null>(null)
  const [model, setModel] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const jobWatch = useJobWatch('bench')
  const openedInitial = useRef(false)

  const refresh = useCallback(async () => {
    const [board, jobs] = await Promise.all([api.leaderboard(), api.jobs('bench')])
    setRows(board)
    setHistory(jobs)
  }, [])

  useEffect(() => {
    refresh().catch((e) => setError(errorMessage(e)))
    api.benchSuite().then(setSuite).catch((e) => setError(errorMessage(e)))
  }, [refresh])

  useEffect(() => {
    if (!initialJobId || openedInitial.current) return
    openedInitial.current = true
    api
      .job('bench', initialJobId)
      .then((full) => jobWatch.open(full))
      .catch((e) => setError(errorMessage(e)))
  }, [initialJobId, jobWatch])

  useEffect(() => {
    setModel((current) => current || (models.find((m) => m.tool_capable)?.name ?? models[0]?.name ?? ''))
  }, [models])

  async function toggleRow(name: string) {
    if (expanded === name) {
      setExpanded(null)
      return
    }
    setExpanded(name)
    setDetails(null)
    try {
      setDetails(await api.benchResult(name))
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function runBench() {
    if (!model || busy) return
    setBusy(true)
    setError(null)
    try {
      const job = await api.startBench(model)
      jobWatch.watch(job, () => {
        refresh().catch((e) => setError(errorMessage(e)))
      })
      setHistory((prev) => [job, ...prev])
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  async function deleteJob(job: JobSummary) {
    // Close first: a watched stream ends the moment the record is gone, and
    // its terminal refetch would otherwise surface a 404 for a delete that
    // succeeded.
    if (jobWatch.job?.id === job.id) jobWatch.close()
    try {
      await api.deleteJob('bench', job.id)
      await refresh()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  const taskEvents = jobWatch.events.filter((e) => e.type === 'task') as BenchTaskEvent[]
  const total = suite?.tasks.length ?? null
  const passed = taskEvents.filter((t) => t.passed).length
  const activeModel = (jobWatch.job?.payload.model as string | undefined) ?? null
  const combinedError = error ?? jobWatch.error

  return (
    <div className="flex flex-col gap-6">
      {combinedError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {combinedError}
        </div>
      )}

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-base font-semibold text-neutral-900">Leaderboard</h2>
          <button type="button" onClick={() => refresh().catch((e) => setError(errorMessage(e)))} className={secondaryButton}>
            Refresh
          </button>
          <div className="ml-auto flex items-center gap-2">
            <ModelSelect models={models} value={model} onChange={setModel} allowAll />
            <button
              type="button"
              onClick={runBench}
              disabled={!model || busy || jobWatch.streaming}
              className={primaryButton}
            >
              {jobWatch.streaming ? 'Running…' : busy ? 'Starting…' : 'Run benchmark'}
            </button>
          </div>
        </div>
        <p className="text-xs text-neutral-500">
          Scores are deterministic checks run locally; the recommended provider is composed from
          this table (Models → Providers).
        </p>
        <LeaderboardTable rows={rows} expanded={expanded} onToggle={toggleRow} details={details} />
      </section>

      {jobWatch.job && (
        <section className="flex flex-col gap-2 rounded-lg border border-neutral-200 bg-white p-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium text-neutral-800">Benchmark run · {activeModel}</span>
            {jobWatch.status && <StatusBadge status={jobWatch.status} />}
            <span className="ml-auto tabular-nums text-neutral-500">
              {taskEvents.length}
              {total ? ` / ${total}` : ''} tasks · {passed} passed
            </span>
          </div>
          {total && (
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-neutral-200">
              <div
                className={`h-full bg-denim-500 transition-all duration-300 ${jobWatch.streaming && taskEvents.length === 0 ? 'w-1/4 animate-pulse' : ''}`}
                style={{ width: `${Math.round((taskEvents.length / total) * 100)}%` }}
              />
            </div>
          )}
          {taskEvents.length === 0 ? (
            <p className="text-xs text-neutral-400">
              {jobWatch.streaming ? 'Waiting for the first task (model may be loading)…' : 'No task events recorded.'}
            </p>
          ) : (
            <ul className="flex flex-col gap-1">
              {taskEvents.map((t) => (
                <TaskRow
                  key={t.id}
                  id={t.id}
                  category={t.category}
                  passed={t.passed}
                  seconds={t.seconds}
                  answer={t.answer}
                  expected={t.expected}
                  error={t.error}
                />
              ))}
            </ul>
          )}
        </section>
      )}

      <SuiteSection suite={suite} />

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold tracking-wide text-neutral-500 uppercase">Past benchmark runs</h2>
        <JobHistory
          jobs={history}
          activeId={jobWatch.job?.id ?? null}
          onOpen={jobWatch.open}
          onDelete={deleteJob}
          label={(j) => String(j.payload.model ?? j.id)}
        />
      </section>
    </div>
  )
}

// --- Arena -------------------------------------------------------------------

function ArenaColumn({
  model,
  answer,
  verdict,
  top,
}: {
  model: string
  answer: ArenaAnswer | undefined
  verdict: ArenaVerdict | undefined
  top: boolean
}) {
  return (
    <div
      className={`flex min-w-0 flex-col gap-2 rounded-lg border bg-white p-3 ${
        top ? 'border-denim-400 ring-2 ring-denim-100' : 'border-neutral-200'
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="truncate text-sm font-medium text-neutral-800" title={model}>
          {model}
        </span>
        {top && <span className="rounded-full bg-denim-100 px-1.5 py-0.5 text-xs text-denim-700">top</span>}
      </div>
      {!answer ? (
        <p className="animate-pulse text-sm text-neutral-400">Answering…</p>
      ) : answer.error ? (
        <p className="rounded-md bg-red-50 px-2 py-1 text-sm text-red-700">{answer.error}</p>
      ) : (
        <div className="text-sm leading-relaxed text-neutral-800">
          <ReactMarkdown components={markdownComponents}>{answer.content}</ReactMarkdown>
        </div>
      )}
      {answer && (
        <p className="text-xs tabular-nums text-neutral-400">
          {num(answer.stats.seconds)}s · {num(answer.stats.tokens_per_sec)} tok/s ·{' '}
          {answer.stats.eval_count ?? '–'} tokens
        </p>
      )}
      {verdict && (
        <div className="mt-auto rounded-md border border-neutral-200 bg-neutral-50 px-2.5 py-2 text-xs">
          <span className="font-semibold text-neutral-800">
            {verdict.score === null ? 'Unscored' : `${verdict.score} / 10`}
          </span>
          {verdict.rationale && <p className="mt-1 text-neutral-600">{verdict.rationale}</p>}
          {verdict.unparsed && (
            <p className="mt-1 whitespace-pre-wrap text-neutral-500">{verdict.unparsed}</p>
          )}
        </div>
      )}
    </div>
  )
}

function ArenaTab({
  models,
  initialJobId,
}: {
  models: ModelInfo[]
  initialJobId: string | null
}) {
  const [prompt, setPrompt] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [judge, setJudge] = useState<string>('auto')
  const [history, setHistory] = useState<JobSummary[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const jobWatch = useJobWatch('arena')
  const openedInitial = useRef(false)

  const refreshHistory = useCallback(async () => setHistory(await api.jobs('arena')), [])

  useEffect(() => {
    refreshHistory().catch((e) => setError(errorMessage(e)))
  }, [refreshHistory])

  useEffect(() => {
    if (!initialJobId || openedInitial.current) return
    openedInitial.current = true
    api
      .job('arena', initialJobId)
      .then((full) => jobWatch.open(full))
      .catch((e) => setError(errorMessage(e)))
  }, [initialJobId, jobWatch])

  function toggle(name: string) {
    setSelected((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : prev.length >= 8 ? prev : [...prev, name],
    )
  }

  async function run() {
    if (!prompt.trim() || selected.length < 2 || busy) return
    setBusy(true)
    setError(null)
    try {
      const job = await api.startArena(prompt.trim(), selected, judge === '' ? null : judge)
      jobWatch.watch(job, () => {
        refreshHistory().catch((e) => setError(errorMessage(e)))
      })
      setHistory((prev) => [job, ...prev])
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  async function deleteJob(job: JobSummary) {
    if (jobWatch.job?.id === job.id) jobWatch.close()
    try {
      await api.deleteJob('arena', job.id)
      await refreshHistory()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  const job = jobWatch.job
  const runModels = (job?.payload.models as string[] | undefined) ?? []
  const runPrompt = (job?.payload.prompt as string | undefined) ?? ''
  const runJudge = (job?.payload.judge as string | null | undefined) ?? null
  const answers = jobWatch.events.filter((e) => e.type === 'answer') as unknown as ArenaAnswer[]
  const verdicts = jobWatch.events.filter((e) => e.type === 'verdict') as unknown as ArenaVerdict[]
  const scores = verdicts.map((v) => v.score).filter((s): s is number => s !== null)
  const topScore = scores.length ? Math.max(...scores) : null
  const combinedError = error ?? jobWatch.error

  return (
    <div className="flex flex-col gap-6">
      {combinedError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {combinedError}
        </div>
      )}

      <section className="flex flex-col gap-3 rounded-lg border border-neutral-200 bg-white p-4">
        <h2 className="text-base font-semibold text-neutral-900">Arena</h2>
        <p className="text-xs text-neutral-500">
          One prompt, several models side by side, with timing — and an optional judge model
          scoring each answer.
        </p>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
          placeholder="Ask something every model should answer…"
          className={`${inputClass} resize-y`}
        />
        <div className="flex flex-wrap gap-1.5">
          {models.length === 0 && <span className="text-sm text-neutral-400">No installed models.</span>}
          {models.map((m) => {
            const on = selected.includes(m.name)
            return (
              <button
                key={m.name}
                type="button"
                onClick={() => toggle(m.name)}
                className={`rounded-full border px-2.5 py-1 text-xs font-medium ${
                  on
                    ? 'border-denim-500 bg-denim-100 text-denim-800'
                    : 'border-neutral-300 bg-white text-neutral-600 hover:border-denim-400'
                }`}
              >
                {on ? '✓ ' : ''}
                {m.name}
              </button>
            )
          })}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-neutral-600">
            Judge
            <select
              value={judge}
              onChange={(e) => setJudge(e.target.value)}
              className="rounded-lg border border-neutral-300 bg-white px-2.5 py-1.5 text-sm text-neutral-800"
            >
              <option value="">None</option>
              <option value="auto">auto (provider's judge route)</option>
              {models.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name}
                </option>
              ))}
            </select>
          </label>
          <span className="text-xs text-neutral-400">
            {selected.length} selected · pick 2–8
          </span>
          <button
            type="button"
            onClick={run}
            disabled={!prompt.trim() || selected.length < 2 || busy || jobWatch.streaming}
            className={`ml-auto ${primaryButton}`}
          >
            {jobWatch.streaming ? 'Running…' : busy ? 'Starting…' : 'Run arena'}
          </button>
        </div>
      </section>

      {job && (
        <section className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium text-neutral-800">Run</span>
            {jobWatch.status && <StatusBadge status={jobWatch.status} />}
            <span className="text-neutral-500">
              judge: {runJudge ?? 'none'}
            </span>
            <span className="ml-auto text-xs text-neutral-400">{formatRelativeTime(job.updated_at)}</span>
          </div>
          <p className="rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2 text-sm whitespace-pre-wrap text-neutral-700">
            {runPrompt}
          </p>
          <div
            className="grid gap-3"
            style={{ gridTemplateColumns: `repeat(${Math.min(runModels.length, 4)}, minmax(0, 1fr))` }}
          >
            {runModels.map((m) => {
              const verdict = verdicts.find((v) => v.model === m)
              return (
                <ArenaColumn
                  key={m}
                  model={m}
                  answer={answers.find((a) => a.model === m)}
                  verdict={verdict}
                  top={topScore !== null && verdict?.score === topScore}
                />
              )
            })}
          </div>
        </section>
      )}

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold tracking-wide text-neutral-500 uppercase">Past arena runs</h2>
        <JobHistory
          jobs={history}
          activeId={job?.id ?? null}
          onOpen={jobWatch.open}
          onDelete={deleteJob}
          label={(j) => {
            const p = String(j.payload.prompt ?? '')
            const ms = (j.payload.models as string[] | undefined)?.length ?? 0
            return `${p.length > 60 ? `${p.slice(0, 60)}…` : p || j.id} · ${ms} models`
          }}
        />
      </section>
    </div>
  )
}

// --- Page --------------------------------------------------------------------

export function ComparePage({
  models,
  initialJob,
}: {
  models: ModelInfo[]
  initialJob?: { kind: 'bench' | 'arena'; id: string } | null
}) {
  const [tab, setTab] = useState<'bench' | 'arena'>(initialJob?.kind ?? 'bench')

  return (
    <div className="flex-1 overflow-y-auto px-6 py-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-4">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900">Compare</h1>
          <p className="text-sm text-neutral-500">
            Rank your installed models on a local benchmark suite, or pit them against each other on
            one prompt.
          </p>
        </div>
        <div className="flex gap-1 border-b border-neutral-200">
          {(
            [
              ['bench', 'Leaderboard & benchmarks'],
              ['arena', 'Arena'],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
                tab === key
                  ? 'border-denim-600 text-denim-800'
                  : 'border-transparent text-neutral-500 hover:text-neutral-800'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        {tab === 'bench' ? (
          <BenchTab models={models} initialJobId={initialJob?.kind === 'bench' ? initialJob.id : null} />
        ) : (
          <ArenaTab models={models} initialJobId={initialJob?.kind === 'arena' ? initialJob.id : null} />
        )}
      </div>
    </div>
  )
}
