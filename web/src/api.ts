// The single choke point for all backend HTTP traffic — the frontend
// equivalent of ollama_client.py's thin-wrapper rule. Nothing else in the
// app should call fetch() directly against /api.

import type {
  ChatResponse,
  ConversationMessage,
  DocumentInfo,
  HealthResponse,
  ModelsResponse,
  UploadResponse,
} from './types'

const BASE = '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init)
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`${path} failed (${response.status}): ${detail}`)
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

export const api = {
  health: () => request<HealthResponse>('/health'),

  getConversation: () => request<ConversationMessage[]>('/conversation'),

  resetConversation: () =>
    request<{ status: string }>('/conversation/reset', { method: 'POST' }),

  chat: (message: string) =>
    request<ChatResponse>('/chat', json({ message })),

  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<UploadResponse>('/upload', { method: 'POST', body: form })
  },

  documents: () => request<DocumentInfo[]>('/documents'),

  models: () => request<ModelsResponse>('/models'),

  setModel: (model: string) =>
    request<ModelsResponse>('/settings/model', json({ model })),
}
