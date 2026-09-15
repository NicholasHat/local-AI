export type ToolCall = {
  function: {
    name: string
    arguments: Record<string, unknown>
  }
}

export type ConversationMessage = {
  role: 'system' | 'user' | 'assistant' | 'tool'
  content?: string | null
  tool_calls?: ToolCall[] | null
  tool_name?: string
}

export type HealthResponse = {
  healthy: boolean
  model: string | null
}

export type ChatResponse = {
  reply: string
}

export type UploadResponse = {
  filename: string
  chunks: number
}

export type DocumentInfo = {
  filename: string
  size_bytes: number
}

export type ModelInfo = {
  name: string
  size: number
  tool_capable: boolean
}

export type ModelsResponse = {
  models: ModelInfo[]
  current: string | null
}

export type SkillInfo = {
  name: string
  description: string
  kind: 'instruction' | 'code'
  parameters: Record<string, unknown>
  required: string[]
  body: string
}

export type SkillWriteRequest = {
  name: string
  description: string
  parameters: Record<string, unknown>
  required: string[]
  prompt?: string
  code?: string
}

export type ConversationMeta = {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export type ModelLibraryEntry = {
  name: string
  description: string
  tool_capable: boolean
}

export type PullProgress = {
  status?: string
  completed?: number
  total?: number
  error?: string
}

// Coding agent (Phase 16 backend / Phase 17 frontend). Steps are the loosely
// typed dicts coding_agent.py appends to runs/<id>.json — modeled here for
// the known fields (see coding_agent.py's _run()) with extras allowed so an
// unrecognized field never breaks rendering.
export type CodingStepType = 'assistant' | 'tool_call' | 'stopped' | 'error'

export type CodingStep = {
  type: CodingStepType
  model?: string
  ts?: string
  content?: string | null
  tool_calls?: ToolCall[] | null
  tool?: string
  args?: Record<string, unknown>
  result?: string
  [key: string]: unknown
}

// The extra line server.py's /events route synthesizes once the run leaves
// `running` — not part of the persisted step log, only the SSE wire shape.
export type CodingStatusEvent = {
  type: 'status'
  status: string
}

export type CodingEvent = CodingStep | CodingStatusEvent

export type CodingRun = {
  id: string
  repo_path: string
  instruction: string
  model: string
  status: string
  created_at: string
  updated_at: string
  base_commit: string
}

export type CodingRunDetail = CodingRun & {
  steps: CodingStep[]
  diff: string
}

export type StartCodingRunRequest = {
  repo_path: string
  instruction: string
  model?: string
}

// --- Phases 19–26: model-sovereignty expansion ------------------------------

// jobstore.py record, served for every kind by /api/jobs/{kind}/{id}.
export type JobKind = 'bench' | 'arena' | 'workflow'

export type JobStatus = 'running' | 'succeeded' | 'failed'

export type JobEvent = {
  type: string
  ts?: string
  [key: string]: unknown
}

export type JobSummary = {
  id: string
  kind: JobKind
  status: JobStatus
  created_at: string
  updated_at: string
  payload: Record<string, unknown>
  error: string | null
}

export type Job = JobSummary & {
  events: JobEvent[]
  result: Record<string, unknown> | null
}

// The extra line /events synthesizes once a job leaves `running`.
export type JobStatusEvent = {
  type: 'status'
  status: JobStatus
  error: string | null
}

export type SpaceSummary = {
  id: string
  name: string
  purpose: string
  created_at: string
  updated_at: string
  post_count: number
}

export type SpacePost = {
  id: string
  ts: string
  author: string
  content: string
}

export type SpaceDetail = Omit<SpaceSummary, 'post_count'> & {
  posts: SpacePost[]
}

export type ProviderRole = 'chat' | 'coding' | 'research' | 'judge' | 'fast' | 'embedding'

export type ProviderInfo = {
  name: string
  description: string
  routes: Partial<Record<ProviderRole, string>>
  options: Partial<Record<ProviderRole, Record<string, unknown>>>
  builtin: boolean
}

export type ProvidersResponse = {
  providers: ProviderInfo[]
  active: string
  roles: ProviderRole[]
  resolved: Record<ProviderRole, string | null>
}

export type ProviderWriteRequest = {
  name: string
  description: string
  routes: Partial<Record<ProviderRole, string>>
  options?: Partial<Record<ProviderRole, Record<string, unknown>>>
}

export type ProjectLinkKind = 'workflow' | 'arena' | 'bench'

export type ProjectSummary = {
  id: string
  name: string
  goal: string
  created_at: string
  updated_at: string
  document_count: number
}

export type ProjectLink = {
  kind: ProjectLinkKind
  id: string
  title: string
  ts: string
}

export type ProjectDetail = {
  id: string
  name: string
  goal: string
  notes: string
  documents: string[]
  conversation_ids: string[]
  links: ProjectLink[]
  space_id: string
  created_at: string
  updated_at: string
}

export type ProjectsResponse = {
  projects: ProjectSummary[]
  active: string | null
}

// --- Models page (Phase 25) --------------------------------------------------

export type InstalledModel = {
  name: string
  size: number
  digest: string | null
  capabilities: string[]
  tool_capable: boolean
  running: boolean
  family: string
  families: string[]
  parameter_size: string
  quantization_level: string
  format: string
  architecture: string
  context_length: number | null
  parameter_count: number | null
  license: string
  license_link: string
  base_model: string
  modified_at: string | null
  template: string
  system: string
  parameters: string
}

export type RunningModel = {
  name: string
  size: number | null
  size_vram: number | null
  expires_at: string | null
}

export type CatalogTag = {
  tag: string
  size: string
  installed: boolean
}

export type CatalogModel = {
  name: string
  org: string
  family: string
  category: string
  description: string
  license: string
  capabilities: string[]
  recommended: boolean
  ollama_tags: CatalogTag[]
  hf_repo: string | null
  notes: string
  installed_tags: string[]
  installed_any: boolean
}

export type CatalogResponse = {
  updated: string
  note: string
  errors: string[]
  models: CatalogModel[]
}

export type TrendingEntry = {
  repo: string
  pull_tag: string
  likes: number | null
  downloads: number | null
  trending_score: number | null
  pipeline: string | null
  license: string | null
  created_at: string | null
}

export type TrendingResponse = {
  entries: TrendingEntry[]
  fetched_at: string | null
  error: string | null
  offline: boolean
}

export type UpdateStatus = 'up_to_date' | 'update_available' | 'unknown' | 'skipped'

export type ModelUpdate = {
  name: string
  status: UpdateStatus
  reason: string | null
  local_digest: string | null
  remote_digest: string | null
}

export type UpdatesResponse = {
  models: ModelUpdate[]
  checked_at: string | null
  error: string | null
  offline: boolean
}

export type CreateModelRequest = {
  name: string
  from_model: string
  system?: string
  parameters?: Record<string, unknown>
  template?: string
}

export type VaultEntry = {
  name: string
  safe_name: string
  exported_at: string | null
  size: number | null
  blobs: number | null
  details: Record<string, unknown> | null
  error: string | null
  installed: boolean
}

export type VaultResponse = {
  vault_dir: string
  entries: VaultEntry[]
}

export type VaultTransfer = {
  name: string
  size: number
  blobs: number
  copied_blobs: number
}

// --- Compare page (Phase 22) -------------------------------------------------

export type BenchCategory =
  | 'reasoning'
  | 'coding'
  | 'instruction'
  | 'tools'
  | 'json'
  | 'knowledge'

export type BenchTask = {
  id: string
  category: BenchCategory
  prompt: string
  check_type: string
  expected: string
}

export type BenchSuite = {
  version: number
  tasks: BenchTask[]
}

export type LeaderboardRow = {
  model: string
  tool_capable: boolean
  overall: number
  categories: Partial<Record<BenchCategory, number>>
  tokens_per_sec: number | null
  load_seconds: number | null
  ran_at: string
  suite_version: number
}

export type BenchTaskResult = {
  id: string
  category: BenchCategory
  passed: boolean
  seconds: number
  tokens_per_sec: number | null
  answer: string
  expected: string
  error?: string
}

export type BenchResult = LeaderboardRow & {
  tasks: BenchTaskResult[]
}

export type BenchTaskEvent = JobEvent & {
  type: 'task'
  id: string
  category: BenchCategory
  passed: boolean
  seconds: number
  tokens_per_sec: number | null
  answer: string
  expected: string
  error?: string
}

export type ArenaAnswer = {
  type: 'answer'
  model: string
  content: string
  stats: {
    tokens_per_sec: number | null
    eval_count: number | null
    eval_seconds: number | null
    load_seconds: number | null
    seconds: number
  }
  error?: string
  ts?: string
}

export type ArenaVerdict = {
  type: 'verdict'
  model: string
  score: number | null
  rationale: string | null
  unparsed?: string
  ts?: string
}

export type ArenaResult = {
  prompt: string
  judge: string | null
  answers: ArenaAnswer[]
  verdicts: ArenaVerdict[]
}

// --- Workflows page (Phase 23) -----------------------------------------------

export type WorkflowInputType = 'string' | 'list' | 'models'

export type WorkflowInput = {
  name: string
  type: WorkflowInputType
  description: string
  required: boolean
  default: unknown
}

export type WorkflowStep = {
  id: string
  name: string
  prompt: string
  role: ProviderRole | null
  model: string | null
  system: string | null
  tools: string[]
  depends_on: string[]
  each: string | null
  options: Record<string, unknown> | null
}

export type WorkflowInfo = {
  name: string
  description: string
  inputs: WorkflowInput[]
  steps: WorkflowStep[]
  system: string | null
  output: string | null
  yaml: string
  builtin: boolean
}

export type WorkflowsResponse = {
  workflows: WorkflowInfo[]
  errors: string[]
}

export type WorkflowStepEvent =
  | { type: 'step_started'; step: string; ts?: string }
  | {
      type: 'step_finished'
      step: string
      model: string
      output: string
      seconds: number
      tool_calls: number
      tools_dropped?: boolean
      ts?: string
    }
  | { type: 'step_failed'; step: string; error: string; ts?: string }

export type WorkflowResult = {
  output: string
  outputs: Record<string, string>
  space_id: string
}
