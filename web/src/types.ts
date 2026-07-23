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
