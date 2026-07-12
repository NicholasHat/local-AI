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
