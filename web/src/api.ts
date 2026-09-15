// The single choke point for all backend HTTP traffic — the frontend
// equivalent of ollama_client.py's thin-wrapper rule. Nothing else in the
// app should call fetch() directly against /api.

import type {
  BenchResult,
  BenchSuite,
  CatalogResponse,
  ChatResponse,
  CodingEvent,
  CreateModelRequest,
  CodingRun,
  CodingRunDetail,
  ConversationMessage,
  ConversationMeta,
  DocumentInfo,
  HealthResponse,
  InstalledModel,
  Job,
  JobEvent,
  LeaderboardRow,
  JobKind,
  JobStatusEvent,
  JobSummary,
  ModelLibraryEntry,
  ModelsResponse,
  ProjectDetail,
  ProjectLinkKind,
  ProjectsResponse,
  ProviderInfo,
  ProviderWriteRequest,
  ProvidersResponse,
  PullProgress,
  SkillInfo,
  SkillWriteRequest,
  SpaceDetail,
  SpacePost,
  SpaceSummary,
  RunningModel,
  StartCodingRunRequest,
  TrendingResponse,
  UpdatesResponse,
  UploadResponse,
  VaultResponse,
  VaultTransfer,
  WorkflowInfo,
  WorkflowsResponse,
} from './types'

const BASE = '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init)
  if (!response.ok) {
    // Prefer FastAPI's `{detail: "..."}` message so users see the actual
    // reason (e.g. an apply conflict) rather than a raw JSON blob.
    const body = await response.text()
    let message = body
    try {
      message = (JSON.parse(body).detail as string) ?? body
    } catch {
      // non-JSON body — keep the raw text
    }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

function json(body: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

function put(body: unknown): RequestInit {
  return {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

function isAbort(e: unknown): boolean {
  return e instanceof DOMException && e.name === 'AbortError'
}

// One reader for every SSE route (model pull, coding-run events, job
// events): splits the chunked body on blank lines and hands each `data:`
// payload to the caller, parsed. Every streaming route in server.py emits
// the same `data: <json>\n\n` shape, so the reading side lives once too.
//
// `signal` lets the caller cancel the stream (a page unmounting, a run being
// reopened). Without it the fetch keeps reading until the backend generator
// ends — for a long job that pins one of the browser's few per-origin
// connections and stalls every other /api call. Aborting resolves normally
// rather than rejecting: cancellation is not an error to show the user.
async function readSSE<T>(
  path: string,
  init: RequestInit | undefined,
  onEvent: (event: T) => void,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, { ...init, signal })
  } catch (e) {
    if (isAbort(e)) return
    throw e
  }
  if (!response.ok || !response.body) {
    const detail = await response.text()
    throw new Error(`${path} failed (${response.status}): ${detail}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const events = buffer.split('\n\n')
      buffer = events.pop() ?? ''
      for (const event of events) {
        const line = event.trim()
        if (!line.startsWith('data:')) continue
        const payload = line.slice('data:'.length).trim()
        if (payload) onEvent(JSON.parse(payload) as T)
      }
    }
  } catch (e) {
    if (isAbort(e)) return
    throw e
  }
}

function pullModel(
  name: string,
  onProgress: (update: PullProgress) => void,
  signal?: AbortSignal,
): Promise<void> {
  return readSSE<PullProgress>(
    '/models/pull',
    json({ name }),
    (update) => {
      // The backend emits a structured error event (rather than aborting the
      // stream) when a pull fails mid-way — turn it into a real rejection so
      // the caller shows the actual reason, not a generic stream failure.
      if (update.error) throw new Error(update.error)
      onProgress(update)
    },
    signal,
  )
}

function codingRunEvents(
  runId: string,
  onEvent: (event: CodingEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return readSSE<CodingEvent>(
    `/coding/runs/${encodeURIComponent(runId)}/events`,
    undefined,
    onEvent,
    signal,
  )
}

function jobEvents(
  kind: JobKind,
  jobId: string,
  onEvent: (event: JobEvent | JobStatusEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return readSSE<JobEvent | JobStatusEvent>(
    `/jobs/${kind}/${encodeURIComponent(jobId)}/events`,
    undefined,
    onEvent,
    signal,
  )
}

export const api = {
  health: () => request<HealthResponse>('/health'),

  getConversation: () => request<ConversationMessage[]>('/conversation'),

  conversations: () => request<ConversationMeta[]>('/conversations'),

  activeConversation: () => request<ConversationMeta>('/conversations/active'),

  newConversation: () =>
    request<ConversationMeta>('/conversations', { method: 'POST' }),

  activateConversation: (id: string) =>
    request<ConversationMeta>(`/conversations/${encodeURIComponent(id)}/activate`, {
      method: 'POST',
    }),

  deleteConversation: (id: string) =>
    request<{ status: string }>(`/conversations/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),

  chat: (message: string) =>
    request<ChatResponse>('/chat', json({ message })),

  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<UploadResponse>('/upload', { method: 'POST', body: form })
  },

  documents: () => request<DocumentInfo[]>('/documents'),

  deleteDocument: (filename: string) =>
    request<{ status: string }>(`/documents/${encodeURIComponent(filename)}`, {
      method: 'DELETE',
    }),

  models: () => request<ModelsResponse>('/models'),

  setModel: (model: string) =>
    request<ModelsResponse>('/settings/model', json({ model })),

  modelLibrary: () => request<ModelLibraryEntry[]>('/models/library'),

  pullModel,

  deleteModel: (name: string) =>
    request<{ status: string }>(`/models/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),

  skills: () => request<SkillInfo[]>('/skills'),

  createSkill: (payload: SkillWriteRequest) =>
    request<SkillInfo>('/skills', json(payload)),

  updateSkill: (name: string, payload: SkillWriteRequest) =>
    request<SkillInfo>(`/skills/${encodeURIComponent(name)}`, put(payload)),

  deleteSkill: (name: string) =>
    request<{ status: string }>(`/skills/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),

  codingRuns: () => request<CodingRun[]>('/coding/runs'),

  codingRun: (id: string) =>
    request<CodingRunDetail>(`/coding/runs/${encodeURIComponent(id)}`),

  startCodingRun: (payload: StartCodingRunRequest) =>
    request<CodingRun>('/coding/runs', json(payload)),

  applyCodingRun: (id: string) =>
    request<CodingRun>(`/coding/runs/${encodeURIComponent(id)}/apply`, {
      method: 'POST',
    }),

  discardCodingRun: (id: string) =>
    request<CodingRun>(`/coding/runs/${encodeURIComponent(id)}/discard`, {
      method: 'POST',
    }),

  codingRunEvents,

  // --- Phases 19–26 ---------------------------------------------------------

  jobs: (kind: JobKind, limit = 20) =>
    request<JobSummary[]>(`/jobs/${kind}?limit=${limit}`),

  job: (kind: JobKind, id: string) =>
    request<Job>(`/jobs/${kind}/${encodeURIComponent(id)}`),

  deleteJob: (kind: JobKind, id: string) =>
    request<{ status: string }>(`/jobs/${kind}/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),

  jobEvents,

  spaces: () => request<SpaceSummary[]>('/spaces'),

  space: (id: string) => request<SpaceDetail>(`/spaces/${encodeURIComponent(id)}`),

  createSpace: (name: string, purpose = '') =>
    request<SpaceDetail>('/spaces', json({ name, purpose })),

  postToSpace: (id: string, content: string, author = 'user') =>
    request<SpacePost>(
      `/spaces/${encodeURIComponent(id)}/posts`,
      json({ content, author }),
    ),

  deleteSpace: (id: string) =>
    request<{ status: string }>(`/spaces/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),

  providers: () => request<ProvidersResponse>('/providers'),

  createProvider: (payload: ProviderWriteRequest) =>
    request<ProvidersResponse>('/providers', json(payload)),

  updateProvider: (name: string, payload: ProviderWriteRequest) =>
    request<ProvidersResponse>(`/providers/${encodeURIComponent(name)}`, put(payload)),

  deleteProvider: (name: string) =>
    request<ProvidersResponse>(`/providers/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),

  activateProvider: (name: string) =>
    request<ProvidersResponse>(`/providers/${encodeURIComponent(name)}/activate`, {
      method: 'POST',
    }),

  recommendProvider: (save = false, name = 'recommended') =>
    request<ProviderInfo>('/providers/recommend', json({ save, name })),

  projects: () => request<ProjectsResponse>('/projects'),

  project: (id: string) => request<ProjectDetail>(`/projects/${encodeURIComponent(id)}`),

  createProject: (name: string, goal = '') =>
    request<ProjectDetail>('/projects', json({ name, goal })),

  updateProject: (id: string, patch: { name?: string; goal?: string; notes?: string }) =>
    request<ProjectDetail>(`/projects/${encodeURIComponent(id)}`, put(patch)),

  deleteProject: (id: string) =>
    request<{ status: string }>(`/projects/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),

  activateProject: (id: string) =>
    request<ProjectsResponse>(`/projects/${encodeURIComponent(id)}/activate`, {
      method: 'POST',
    }),

  deactivateProject: () =>
    request<ProjectsResponse>('/projects/deactivate', { method: 'POST' }),

  attachProjectDocument: (id: string, filename: string) =>
    request<ProjectDetail>(`/projects/${encodeURIComponent(id)}/documents`, json({ filename })),

  detachProjectDocument: (id: string, filename: string) =>
    request<ProjectDetail>(
      `/projects/${encodeURIComponent(id)}/documents/${encodeURIComponent(filename)}`,
      { method: 'DELETE' },
    ),

  appendProjectNotes: (id: string, text: string, heading?: string) =>
    request<ProjectDetail>(
      `/projects/${encodeURIComponent(id)}/notes/append`,
      json({ text, heading }),
    ),

  linkProject: (id: string, kind: ProjectLinkKind, jobId: string, title = '') =>
    request<ProjectDetail>(
      `/projects/${encodeURIComponent(id)}/links`,
      json({ kind, id: jobId, title }),
    ),

  installedModels: () => request<InstalledModel[]>('/models/installed'),

  installedModel: (name: string) =>
    request<InstalledModel>(`/models/installed/${encodeURIComponent(name)}`),

  runningModels: () => request<RunningModel[]>('/models/running'),

  catalog: () => request<CatalogResponse>('/models/catalog'),

  trending: (limit = 20, refresh = false) =>
    request<TrendingResponse>(`/models/trending?limit=${limit}&refresh=${refresh}`),

  modelUpdates: (refresh = false) =>
    request<UpdatesResponse>(`/models/updates?refresh=${refresh}`),

  createModel: (payload: CreateModelRequest) =>
    request<{ name: string; status: string }>('/models/create', json(payload)),

  vault: () => request<VaultResponse>('/models/vault'),

  vaultExport: (name: string) =>
    request<VaultTransfer>('/models/vault/export', json({ name })),

  vaultImport: (name: string) =>
    request<VaultTransfer>('/models/vault/import', json({ name })),

  vaultDelete: (name: string) =>
    request<VaultResponse>(`/models/vault/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),

  benchSuite: () => request<BenchSuite>('/bench/suite'),

  startBench: (model: string, options?: Record<string, unknown>) =>
    request<Job>('/bench/runs', json({ model, options })),

  leaderboard: () => request<LeaderboardRow[]>('/bench/results'),

  benchResult: (model: string) =>
    request<BenchResult>(`/bench/results/${encodeURIComponent(model)}`),

  startArena: (prompt: string, models: string[], judge: string | null) =>
    request<Job>('/bench/arena', json({ prompt, models, judge })),

  workflows: () => request<WorkflowsResponse>('/workflows'),

  workflow: (name: string) =>
    request<WorkflowInfo>(`/workflows/${encodeURIComponent(name)}`),

  saveWorkflow: (name: string, yaml: string) =>
    request<WorkflowInfo>(`/workflows/${encodeURIComponent(name)}`, put({ yaml })),

  deleteWorkflow: (name: string) =>
    request<{ status: string }>(`/workflows/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),

  startWorkflow: (name: string, inputs: Record<string, unknown>, projectId?: string | null) =>
    request<Job>(
      `/workflows/${encodeURIComponent(name)}/runs`,
      json({ inputs, project_id: projectId ?? null }),
    ),
}
