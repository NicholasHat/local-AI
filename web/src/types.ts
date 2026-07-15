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
