// The single choke point for all backend HTTP traffic — the frontend
// equivalent of ollama_client.py's thin-wrapper rule. Nothing else in the
// app should call fetch() directly against /api.

import type {
  ChatResponse,
  CodingEvent,
  CodingRun,
  CodingRunDetail,
  ConversationMessage,
  ConversationMeta,
  DocumentInfo,
  HealthResponse,
  ModelLibraryEntry,
  ModelsResponse,
  PullProgress,
  SkillInfo,
  SkillWriteRequest,
  StartCodingRunRequest,
  UploadResponse,
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

async function pullModel(
  name: string,
  onProgress: (update: PullProgress) => void,
): Promise<void> {
  const response = await fetch(`${BASE}/models/pull`, json({ name }))
  if (!response.ok || !response.body) {
    const detail = await response.text()
    throw new Error(`/models/pull failed (${response.status}): ${detail}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
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
      if (!payload) continue
      const update = JSON.parse(payload) as PullProgress
      // The backend emits a structured error event (rather than aborting the
      // stream) when a pull fails mid-way — turn it into a real rejection so
      // the caller shows the actual reason, not a generic stream failure.
      if (update.error) throw new Error(update.error)
      onProgress(update)
    }
  }
}

async function codingRunEvents(
  runId: string,
  onEvent: (event: CodingEvent) => void,
): Promise<void> {
  const response = await fetch(`${BASE}/coding/runs/${encodeURIComponent(runId)}/events`)
  if (!response.ok || !response.body) {
    const detail = await response.text()
    throw new Error(`/coding/runs/${runId}/events failed (${response.status}): ${detail}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
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
      if (payload) onEvent(JSON.parse(payload) as CodingEvent)
    }
  }
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
    request<SkillInfo>(`/skills/${encodeURIComponent(name)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

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
}
