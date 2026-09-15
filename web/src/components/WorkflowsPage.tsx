import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import { api } from '../api'
import { formatRelativeTime } from '../format'
import type {
  Job,
  JobEvent,
  JobStatus,
  JobStatusEvent,
  JobSummary,
  ModelInfo,
  ProjectSummary,
  WorkflowInfo,
  WorkflowInput,
  WorkflowResult,
  WorkflowStep,
  WorkflowStepEvent,
} from '../types'

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

const markdownComponents: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-2 list-disc pl-5 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 list-decimal pl-5 last:mb-0">{children}</ol>,
  h1: ({ children }) => <h1 className="mb-2 text-base font-semibold">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-2 text-base font-semibold">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-1 text-sm font-semibold">{children}</h3>,
  code: ({ children }) => (
    <code className="rounded bg-neutral-100 px-1 py-0.5 font-mono text-[13px]">{children}</code>
  ),
  pre: ({ children }) => (
    <pre className="mb-2 overflow-x-auto rounded-lg bg-neutral-900 p-3 font-mono text-[13px] text-neutral-100 last:mb-0">
      {children}
    </pre>
  ),
}

function Markdown({ text }: { text: string }) {
  return (
    <div className="text-sm leading-relaxed text-neutral-800">
      <ReactMarkdown components={markdownComponents}>{text}</ReactMarkdown>
    </div>
  )
}

const STARTER_YAML = `# A workflow is a DAG of steps, each run by the chat agent with only the
# tools listed. Placeholders: {inputs.<name>}, {steps.<id>.output},
# {item} (inside an each: step), {space_id}, {run_id}.
description: Draft and critique a short piece of writing
inputs:
  - name: topic
    type: string            # string | list | models
    description: What to write about
    required: true
steps:
  - id: draft
    name: Draft
    role: chat              # chat | coding | research | judge | fast — or model: <tag>
    tools: [search_documents]
    prompt: |
      Write a concise, well-structured piece about: {inputs.topic}
  - id: critique
    name: Critique
    role: judge
    depends_on: [draft]
    prompt: |
      Critique this draft. Be specific and list concrete fixes.

      {steps.draft.output}
  - id: revise
    name: Revise
    depends_on: [draft, critique]
    prompt: |
      Revise the draft using the critique. Output only the final piece.

      Draft:
      {steps.draft.output}

      Critique:
      {steps.critique.output}
output: revise
`

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

function Chip({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: 'neutral' | 'denim' | 'amber' }) {
  const cls =
    tone === 'denim'
      ? 'bg-denim-100 text-denim-700'
      : tone === 'amber'
        ? 'bg-amber-100 text-amber-700'
        : 'bg-neutral-100 text-neutral-600'
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs ${cls}`}>{children}</span>
}

// --- Job watching (start → stream → refetch), same shape as CodingPage -------

function useJobWatch() {
  const [job, setJob] = useState<Job | null>(null)
  const [liveEvents, setLiveEvents] = useState<JobEvent[]>([])
  const [liveStatus, setLiveStatus] = useState<JobStatus | null>(null)
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const watchIdRef = useRef<string | null>(null)
  // One live stream at most: starting a new watch, closing, or unmounting
  // aborts the previous fetch so it releases its connection instead of
  // reading silently until the run ends.
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
          'workflow',
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
            .job('workflow', summary.id)
            .then((full) => {
              if (watchIdRef.current === summary.id) setJob(full)
            })
            .catch((e) => setError(errorMessage(e)))
            .finally(() => onDone?.())
        })
    },
    [abortStream],
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
        .job('workflow', summary.id)
        .then((full) => {
          if (watchIdRef.current === summary.id) setJob(full)
        })
        .catch((e) => setError(errorMessage(e)))
    },
    [watch, abortStream],
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

  const events = job && job.events.length ? job.events : liveEvents
  const status: JobStatus | null = liveStatus ?? job?.status ?? null
  return { job, events, status, streaming, error, watch, open, close }
}

// --- Inputs ---------------------------------------------------------------------

type InputValues = Record<string, string | string[]>

function initialValues(inputs: WorkflowInput[]): InputValues {
  const values: InputValues = {}
  for (const input of inputs) {
    const def = input.default
    if (input.type === 'models') {
      values[input.name] = Array.isArray(def) ? def.map(String) : []
    } else if (input.type === 'list') {
      values[input.name] = Array.isArray(def) ? def.map(String).join('\n') : ''
    } else {
      values[input.name] = def == null ? '' : String(def)
    }
  }
  return values
}

function toPayload(inputs: WorkflowInput[], values: InputValues): Record<string, unknown> {
  const payload: Record<string, unknown> = {}
  for (const input of inputs) {
    const raw = values[input.name]
    if (input.type === 'models') {
      payload[input.name] = Array.isArray(raw) ? raw : []
    } else if (input.type === 'list') {
      const items = String(raw ?? '')
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean)
      payload[input.name] = items
    } else {
      payload[input.name] = String(raw ?? '')
    }
  }
  return payload
}

function missingRequired(inputs: WorkflowInput[], payload: Record<string, unknown>): string[] {
  return inputs
    .filter((input) => {
      if (!input.required) return false
      const value = payload[input.name]
      return Array.isArray(value) ? value.length === 0 : !String(value ?? '').trim()
    })
    .map((input) => input.name)
}

function InputControl({
  input,
  value,
  models,
  onChange,
}: {
  input: WorkflowInput
  value: string | string[]
  models: ModelInfo[]
  onChange: (value: string | string[]) => void
}) {
  const label = (
    <div className="flex items-baseline gap-2">
      <span className="text-sm font-medium text-neutral-800">{input.name}</span>
      {input.required && <span className="text-xs text-red-500">required</span>}
      <span className="text-xs text-neutral-400">{input.type}</span>
    </div>
  )
  if (input.type === 'models') {
    const selected = Array.isArray(value) ? value : []
    return (
      <div className="flex flex-col gap-1.5">
        {label}
        {input.description && <p className="text-xs text-neutral-500">{input.description}</p>}
        <div className="flex flex-wrap gap-1.5">
          {models.length === 0 && (
            <span className="text-xs text-neutral-400">No models installed.</span>
          )}
          {models.map((m) => {
            const on = selected.includes(m.name)
            return (
              <button
                key={m.name}
                type="button"
                onClick={() =>
                  onChange(on ? selected.filter((n) => n !== m.name) : [...selected, m.name])
                }
                className={`rounded-full border px-2.5 py-1 text-xs transition ${
                  on
                    ? 'border-denim-500 bg-denim-100 text-denim-800'
                    : 'border-neutral-300 bg-white text-neutral-600 hover:border-denim-400'
                }`}
              >
                {on ? '✓ ' : ''}
                {m.name}
                {!m.tool_capable && <span className="ml-1 text-neutral-400">(no tools)</span>}
              </button>
            )
          })}
        </div>
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-1.5">
      {label}
      {input.description && <p className="text-xs text-neutral-500">{input.description}</p>}
      <textarea
        value={Array.isArray(value) ? value.join('\n') : value}
        onChange={(e) => onChange(e.target.value)}
        rows={input.type === 'list' ? 4 : 2}
        placeholder={input.type === 'list' ? 'One item per line' : ''}
        className="w-full resize-y rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-denim-500 focus:outline-none"
      />
    </div>
  )
}

// --- Step diagram ----------------------------------------------------------------

function StepDefinitionCard({ step, index }: { step: WorkflowStep; index: number }) {
  return (
    <li className="flex gap-3 rounded-lg border border-neutral-200 bg-white px-3 py-2">
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-denim-100 text-xs font-semibold text-denim-700">
        {index + 1}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-neutral-800">{step.name}</span>
          <span className="font-mono text-xs text-neutral-400">{step.id}</span>
          {step.model ? (
            <Chip tone="denim">model: {step.model}</Chip>
          ) : (
            <Chip tone="denim">role: {step.role ?? 'chat'}</Chip>
          )}
          {step.each && <Chip tone="amber">each: {step.each}</Chip>}
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-neutral-500">
          {step.depends_on.length > 0 && <span>after {step.depends_on.join(', ')}</span>}
          {step.tools.length > 0 ? (
            step.tools.map((t) => <Chip key={t}>{t}</Chip>)
          ) : (
            <span className="text-neutral-400">no tools</span>
          )}
        </div>
      </div>
    </li>
  )
}

// --- Run view ----------------------------------------------------------------------

type InstanceState = {
  id: string
  status: 'pending' | 'running' | 'finished' | 'failed'
  model?: string
  output?: string
  seconds?: number
  tool_calls?: number
  error?: string
}

function instanceStates(steps: WorkflowStep[], events: JobEvent[]): InstanceState[] {
  const byId = new Map<string, InstanceState>()
  const order: string[] = []
  for (const raw of events) {
    const event = raw as unknown as WorkflowStepEvent
    if (!('step' in event)) continue
    if (!byId.has(event.step)) {
      byId.set(event.step, { id: event.step, status: 'running' })
      order.push(event.step)
    }
    const state = byId.get(event.step)!
    if (event.type === 'step_started') state.status = 'running'
    if (event.type === 'step_finished') {
      state.status = 'finished'
      state.model = event.model
      state.output = event.output
      state.seconds = event.seconds
      state.tool_calls = event.tool_calls
    }
    if (event.type === 'step_failed') {
      state.status = 'failed'
      state.error = event.error
    }
  }
  // Definition order first (instances of an `each` step grouped under it),
  // then anything the definition doesn't know about.
  const result: InstanceState[] = []
  const seen = new Set<string>()
  for (const step of steps) {
    const instances = order.filter((id) => id === step.id || id.startsWith(`${step.id}[`))
    if (instances.length === 0) {
      result.push({ id: step.id, status: 'pending' })
      continue
    }
    for (const id of instances) {
      result.push(byId.get(id)!)
      seen.add(id)
    }
  }
  for (const id of order) if (!seen.has(id)) result.push(byId.get(id)!)
  return result
}

function StepRunCard({ state }: { state: InstanceState }) {
  const long = (state.output ?? '').length > 600
  const [expanded, setExpanded] = useState(!long)
  const tone =
    state.status === 'failed'
      ? 'border-red-200 bg-red-50'
      : state.status === 'running'
        ? 'border-denim-200 bg-denim-50'
        : state.status === 'finished'
          ? 'border-neutral-200 bg-white'
          : 'border-dashed border-neutral-200 bg-neutral-50'
  const icon =
    state.status === 'failed'
      ? '⛔'
      : state.status === 'running'
        ? '⏳'
        : state.status === 'finished'
          ? '✅'
          : '○'
  return (
    <div className={`flex flex-col gap-1.5 rounded-lg border px-3 py-2 ${tone}`}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span aria-hidden className={state.status === 'running' ? 'animate-pulse' : ''}>
          {icon}
        </span>
        <span className="font-mono font-medium text-neutral-800">{state.id}</span>
        {state.model && <Chip tone="denim">{state.model}</Chip>}
        {state.status === 'finished' && (
          <span className="ml-auto text-xs text-neutral-400">
            {state.seconds?.toFixed(1)}s · {state.tool_calls ?? 0} tool call
            {state.tool_calls === 1 ? '' : 's'}
          </span>
        )}
        {state.status === 'pending' && (
          <span className="ml-auto text-xs text-neutral-400">waiting</span>
        )}
        {state.status === 'running' && (
          <span className="ml-auto text-xs text-denim-600">running…</span>
        )}
      </div>
      {state.status === 'failed' && (
        <p className="text-sm whitespace-pre-wrap text-red-700">{state.error}</p>
      )}
      {state.output && (
        <div>
          {expanded ? (
            <Markdown text={state.output} />
          ) : (
            <p className="text-sm text-neutral-500">
              {state.output.slice(0, 300).trimEnd()}…
            </p>
          )}
          {long && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="mt-1 text-xs font-medium text-denim-700 hover:underline"
            >
              {expanded ? 'Collapse' : 'Show full output'}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function RunHistory({
  runs,
  activeId,
  onOpen,
  onDelete,
}: {
  runs: JobSummary[]
  activeId: string | null
  onOpen: (run: JobSummary) => void
  onDelete: (run: JobSummary) => void
}) {
  if (runs.length === 0) {
    return <p className="text-sm text-neutral-400">No runs yet.</p>
  }
  return (
    <ul className="flex flex-col gap-1">
      {runs.map((run) => (
        <li
          key={run.id}
          className={`group flex items-center gap-2 rounded-md px-2 py-1.5 text-sm ${
            run.id === activeId ? 'bg-denim-100' : 'hover:bg-neutral-100'
          }`}
        >
          <button
            type="button"
            onClick={() => onOpen(run)}
            className="flex min-w-0 flex-1 items-center gap-2 text-left"
          >
            <span className="truncate font-medium text-neutral-800">
              {String(run.payload.name ?? 'workflow')}
            </span>
            <StatusBadge status={run.status} />
            <span className="ml-auto shrink-0 text-xs text-neutral-400">
              {formatRelativeTime(run.updated_at)}
            </span>
          </button>
          <button
            type="button"
            disabled={run.status === 'running'}
            onClick={() => onDelete(run)}
            className="shrink-0 text-xs text-neutral-400 opacity-0 group-hover:opacity-100 hover:text-red-600 disabled:cursor-not-allowed disabled:hover:text-neutral-400"
            aria-label={`Delete run ${run.id}`}
          >
            ✕
          </button>
        </li>
      ))}
    </ul>
  )
}

// --- Page -----------------------------------------------------------------------------

export function WorkflowsPage({
  models,
  initialJobId,
  onOpenSpace,
}: {
  models: ModelInfo[]
  initialJobId?: string | null
  onOpenSpace: (spaceId: string) => void
}) {
  const [definitions, setDefinitions] = useState<WorkflowInfo[]>([])
  const [loadErrors, setLoadErrors] = useState<string[]>([])
  const [selectedName, setSelectedName] = useState<string | null>(null)
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [projectId, setProjectId] = useState('')
  const [values, setValues] = useState<InputValues>({})
  const [history, setHistory] = useState<JobSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [savedToNotes, setSavedToNotes] = useState(false)
  const [copied, setCopied] = useState(false)

  // YAML editor: `editorName` null = closed; '' = new workflow (name typed).
  const [editorOpen, setEditorOpen] = useState(false)
  const [editorIsNew, setEditorIsNew] = useState(false)
  const [editorName, setEditorName] = useState('')
  const [yamlText, setYamlText] = useState('')
  const [saving, setSaving] = useState(false)

  const jobWatch = useJobWatch()
  const openedInitial = useRef(false)

  const selected = definitions.find((d) => d.name === selectedName) ?? null

  const refreshDefinitions = useCallback(async () => {
    const body = await api.workflows()
    setDefinitions(body.workflows)
    setLoadErrors(body.errors)
    setSelectedName((current) =>
      current && body.workflows.some((w) => w.name === current)
        ? current
        : (body.workflows[0]?.name ?? null),
    )
  }, [])

  const refreshHistory = useCallback(async () => {
    setHistory(await api.jobs('workflow'))
  }, [])

  useEffect(() => {
    Promise.all([refreshDefinitions(), refreshHistory()]).catch((e) =>
      setError(errorMessage(e)),
    )
    api
      .projects()
      .then((body) => {
        setProjects(body.projects)
        if (body.active) setProjectId(body.active)
      })
      .catch(() => {
        // projects are optional here — the run form still works without them
      })
  }, [refreshDefinitions, refreshHistory])

  useEffect(() => {
    if (!initialJobId || openedInitial.current) return
    openedInitial.current = true
    api
      .job('workflow', initialJobId)
      .then((full) => {
        jobWatch.open(full)
        const name = String(full.payload.name ?? '')
        if (name) setSelectedName(name)
      })
      .catch((e) => setError(errorMessage(e)))
  }, [initialJobId, jobWatch])

  // Reset the input form whenever a different workflow is selected.
  useEffect(() => {
    if (selected) setValues(initialValues(selected.inputs))
  }, [selected])

  useEffect(() => {
    setSavedToNotes(false)
    setCopied(false)
  }, [jobWatch.job?.id])

  const runDefinition = useMemo(() => {
    const name = jobWatch.job ? String(jobWatch.job.payload.name ?? '') : null
    return definitions.find((d) => d.name === name) ?? null
  }, [definitions, jobWatch.job])

  const stepStates = useMemo(
    () => (jobWatch.job ? instanceStates(runDefinition?.steps ?? [], jobWatch.events) : []),
    [jobWatch.job, jobWatch.events, runDefinition],
  )

  const result = (jobWatch.job?.result as WorkflowResult | null) ?? null
  const runSpaceId = jobWatch.job ? String(jobWatch.job.payload.space_id ?? '') : ''
  const runProjectId = jobWatch.job ? (jobWatch.job.payload.project_id as string | null) : null
  const isRunning = jobWatch.status === 'running' || jobWatch.streaming

  async function handleRun() {
    if (!selected) return
    const payload = toPayload(selected.inputs, values)
    const missing = missingRequired(selected.inputs, payload)
    if (missing.length) {
      setError(`Missing required input${missing.length > 1 ? 's' : ''}: ${missing.join(', ')}`)
      return
    }
    setStarting(true)
    setError(null)
    try {
      const job = await api.startWorkflow(selected.name, payload, projectId || null)
      jobWatch.watch(job, () => {
        refreshHistory().catch(() => {})
      })
      await refreshHistory()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setStarting(false)
    }
  }

  function openEditor(definition: WorkflowInfo | null) {
    setEditorOpen(true)
    setEditorIsNew(definition === null)
    setEditorName(definition?.name ?? '')
    setYamlText(definition?.yaml ?? STARTER_YAML)
    setError(null)
  }

  async function handleSave() {
    const name = editorName.trim()
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(name)) {
      setError('Workflow name must be lowercase letters, digits, and hyphens.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      await api.saveWorkflow(name, yamlText)
      await refreshDefinitions()
      setSelectedName(name)
      setEditorOpen(false)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setSaving(false)
    }
  }

  async function handleDeleteDefinition(name: string) {
    setError(null)
    try {
      await api.deleteWorkflow(name)
      if (editorName === name) setEditorOpen(false)
      await refreshDefinitions()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function handleDeleteRun(run: JobSummary) {
    setError(null)
    try {
      await api.deleteJob('workflow', run.id)
      if (jobWatch.job?.id === run.id) jobWatch.close()
      await refreshHistory()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function handleCopy() {
    if (!result) return
    try {
      await navigator.clipboard.writeText(result.output)
      setCopied(true)
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function handleSaveToNotes() {
    if (!result || !runProjectId || !runDefinition) return
    setError(null)
    try {
      await api.appendProjectNotes(runProjectId, result.output, `${runDefinition.name} run`)
      setSavedToNotes(true)
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  const pageError = error ?? jobWatch.error

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 py-6">
        <header className="flex flex-col gap-1">
          <h1 className="text-xl font-semibold text-neutral-900">Workflows</h1>
          <p className="text-sm text-neutral-500">
            Multi-step, multi-model pipelines. Each step runs the chat agent with only the
            tools it's granted, and every step posts its output to the run's shared space
            so the models — and you — can read the whole exchange.
          </p>
        </header>

        {pageError && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
            {pageError}
          </div>
        )}

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
          {/* Left column */}
          <div className="flex flex-col gap-6">
            <section className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <h2 className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
                  Definitions
                </h2>
                <button
                  type="button"
                  onClick={() => openEditor(null)}
                  className="rounded-md border border-neutral-300 bg-white px-2 py-1 text-xs font-medium text-neutral-700 hover:bg-neutral-100"
                >
                  + New workflow
                </button>
              </div>
              {definitions.length === 0 && (
                <p className="text-sm text-neutral-400">
                  No workflows yet — create one from the starter template.
                </p>
              )}
              <ul className="flex flex-col gap-1">
                {definitions.map((d) => (
                  <li
                    key={d.name}
                    className={`group flex items-start gap-2 rounded-md px-2 py-1.5 text-sm ${
                      d.name === selectedName
                        ? 'bg-denim-100 text-denim-800'
                        : 'text-neutral-700 hover:bg-neutral-100'
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => setSelectedName(d.name)}
                      className="flex min-w-0 flex-1 flex-col text-left"
                    >
                      <span className="truncate font-medium">{d.name}</span>
                      <span className="line-clamp-2 text-xs text-neutral-500">
                        {d.description || 'No description'}
                      </span>
                      <span className="text-xs text-neutral-400">
                        {d.steps.length} step{d.steps.length === 1 ? '' : 's'}
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDeleteDefinition(d.name)}
                      className="shrink-0 text-xs text-neutral-400 opacity-0 group-hover:opacity-100 hover:text-red-600"
                      aria-label={`Delete workflow ${d.name}`}
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
              {loadErrors.length > 0 && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  <p className="mb-1 font-medium">Skipped definitions</p>
                  <ul className="flex flex-col gap-0.5">
                    {loadErrors.map((e, i) => (
                      <li key={i} className="break-words">
                        {e}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
                Past runs
              </h2>
              <RunHistory
                runs={history}
                activeId={jobWatch.job?.id ?? null}
                onOpen={(run) => {
                  jobWatch.open(run)
                  const name = String(run.payload.name ?? '')
                  if (name && definitions.some((d) => d.name === name)) setSelectedName(name)
                }}
                onDelete={handleDeleteRun}
              />
            </section>
          </div>

          {/* Right column */}
          <div className="flex min-w-0 flex-col gap-6">
            {editorOpen ? (
              <section className="flex flex-col gap-3 rounded-xl border border-neutral-200 bg-white p-4">
                <div className="flex flex-wrap items-center gap-3">
                  <h2 className="text-base font-semibold text-neutral-900">
                    {editorIsNew ? 'New workflow' : `Edit ${editorName}`}
                  </h2>
                  {editorIsNew && (
                    <input
                      value={editorName}
                      onChange={(e) => setEditorName(e.target.value)}
                      placeholder="name (e.g. draft-and-critique)"
                      className="rounded-lg border border-neutral-300 px-3 py-1.5 font-mono text-sm focus:border-denim-500 focus:outline-none"
                    />
                  )}
                  <div className="ml-auto flex gap-2">
                    <button
                      type="button"
                      onClick={() => setEditorOpen(false)}
                      className="rounded-lg border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-100"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={handleSave}
                      disabled={saving}
                      className="rounded-lg bg-denim-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-denim-700 disabled:opacity-50"
                    >
                      {saving ? 'Saving…' : 'Save'}
                    </button>
                  </div>
                </div>
                <textarea
                  value={yamlText}
                  onChange={(e) => setYamlText(e.target.value)}
                  spellCheck={false}
                  rows={24}
                  className="w-full resize-y rounded-lg border border-neutral-300 bg-neutral-50 px-3 py-2 font-mono text-[13px] leading-relaxed focus:border-denim-500 focus:outline-none"
                />
                <p className="text-xs text-neutral-500">
                  Validated before anything is written: unknown tools, roles, dependencies,
                  cycles, and missing inputs are rejected with the reason.
                </p>
              </section>
            ) : selected ? (
              <>
                <section className="flex flex-col gap-4 rounded-xl border border-neutral-200 bg-white p-4">
                  <div className="flex flex-wrap items-start gap-3">
                    <div className="min-w-0 flex-1">
                      <h2 className="text-base font-semibold text-neutral-900">{selected.name}</h2>
                      <p className="text-sm text-neutral-500">{selected.description}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => openEditor(selected)}
                      className="rounded-lg border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-100"
                    >
                      YAML
                    </button>
                  </div>

                  <div className="flex flex-col gap-4">
                    {selected.inputs.length === 0 && (
                      <p className="text-sm text-neutral-400">This workflow takes no inputs.</p>
                    )}
                    {selected.inputs.map((input) => (
                      <InputControl
                        key={input.name}
                        input={input}
                        value={values[input.name] ?? (input.type === 'models' ? [] : '')}
                        models={models}
                        onChange={(v) => setValues((prev) => ({ ...prev, [input.name]: v }))}
                      />
                    ))}
                    <div className="flex flex-col gap-1.5">
                      <span className="text-sm font-medium text-neutral-800">Project</span>
                      <p className="text-xs text-neutral-500">
                        Optional — scopes document search to the project's attached documents
                        and links the run to it.
                      </p>
                      <select
                        value={projectId}
                        onChange={(e) => setProjectId(e.target.value)}
                        className="w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm focus:border-denim-500 focus:outline-none sm:max-w-sm"
                      >
                        <option value="">No project</option>
                        {projects.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      onClick={handleRun}
                      disabled={starting || isRunning}
                      className="rounded-lg bg-denim-600 px-4 py-2 text-sm font-medium text-white hover:bg-denim-700 disabled:opacity-50"
                    >
                      {starting ? 'Starting…' : isRunning ? 'Running…' : '▶ Run'}
                    </button>
                    <span className="text-xs text-neutral-400">
                      Each run creates its own shared space.
                    </span>
                  </div>
                </section>

                <section className="flex flex-col gap-2">
                  <h2 className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
                    Steps
                  </h2>
                  <ol className="flex flex-col gap-2">
                    {selected.steps.map((step, i) => (
                      <StepDefinitionCard key={step.id} step={step} index={i} />
                    ))}
                  </ol>
                  {selected.output && (
                    <p className="text-xs text-neutral-400">
                      Final output comes from <span className="font-mono">{selected.output}</span>.
                    </p>
                  )}
                </section>
              </>
            ) : (
              <div className="rounded-xl border border-dashed border-neutral-300 px-6 py-10 text-center text-sm text-neutral-400">
                Select a workflow on the left, or create a new one.
              </div>
            )}

            {jobWatch.job && (
              <section className="flex flex-col gap-3 rounded-xl border border-neutral-200 bg-neutral-50 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-base font-semibold text-neutral-900">
                    Run · {String(jobWatch.job.payload.name ?? 'workflow')}
                  </h2>
                  {jobWatch.status && <StatusBadge status={jobWatch.status} />}
                  {jobWatch.streaming && (
                    <span className="flex items-center gap-1 text-xs text-denim-600">
                      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-denim-500" />
                      live
                    </span>
                  )}
                  <span className="text-xs text-neutral-400">
                    {formatRelativeTime(jobWatch.job.created_at)} · {jobWatch.job.id}
                  </span>
                  <div className="ml-auto flex gap-2">
                    {runSpaceId && (
                      <button
                        type="button"
                        onClick={() => onOpenSpace(runSpaceId)}
                        className="rounded-lg border border-neutral-300 bg-white px-3 py-1.5 text-sm text-neutral-700 hover:border-denim-400 hover:text-denim-700"
                      >
                        🗣️ Open shared space
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={jobWatch.close}
                      className="rounded-lg border border-neutral-300 bg-white px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-100"
                    >
                      Close
                    </button>
                  </div>
                </div>

                {Object.keys(jobWatch.job.payload.inputs ?? {}).length > 0 && (
                  <div className="flex flex-wrap gap-1.5 text-xs">
                    {Object.entries(jobWatch.job.payload.inputs as Record<string, unknown>).map(
                      ([k, v]) => (
                        <Chip key={k}>
                          {k}: {Array.isArray(v) ? v.join(', ') : String(v)}
                        </Chip>
                      ),
                    )}
                  </div>
                )}

                {stepStates.length === 0 ? (
                  <p className="text-sm text-neutral-400">
                    {isRunning ? 'Waiting for the first step…' : 'No step events recorded.'}
                  </p>
                ) : (
                  <div className="flex flex-col gap-2">
                    {stepStates.map((state) => (
                      <StepRunCard key={state.id} state={state} />
                    ))}
                  </div>
                )}

                {jobWatch.status === 'failed' && jobWatch.job.error && (
                  <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                    {jobWatch.job.error}
                  </div>
                )}

                {result && jobWatch.status === 'succeeded' && (
                  <div className="flex flex-col gap-2 rounded-lg border border-green-200 bg-white p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-semibold text-neutral-900">Final output</h3>
                      <div className="ml-auto flex gap-2">
                        <button
                          type="button"
                          onClick={handleCopy}
                          className="rounded-lg border border-neutral-300 px-3 py-1 text-xs text-neutral-700 hover:bg-neutral-100"
                        >
                          {copied ? 'Copied ✓' : 'Copy'}
                        </button>
                        {runProjectId && (
                          <button
                            type="button"
                            onClick={handleSaveToNotes}
                            disabled={savedToNotes}
                            className="rounded-lg border border-denim-300 bg-denim-50 px-3 py-1 text-xs text-denim-700 hover:bg-denim-100 disabled:opacity-60"
                          >
                            {savedToNotes ? 'Saved to project notes ✓' : 'Save to project notes'}
                          </button>
                        )}
                      </div>
                    </div>
                    <Markdown text={result.output} />
                  </div>
                )}
              </section>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
