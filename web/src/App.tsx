import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { Composer } from './components/Composer'
import { Sidebar } from './components/Sidebar'
import { Transcript } from './components/Transcript'
import type {
  ConversationMessage,
  DocumentInfo,
  HealthResponse,
  ModelsResponse,
} from './types'

const EMPTY_MODELS: ModelsResponse = { models: [], current: null }

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

function App() {
  const [initializing, setInitializing] = useState(true)
  const [initError, setInitError] = useState<string | null>(null)

  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [messages, setMessages] = useState<ConversationMessage[]>([])
  const [documents, setDocuments] = useState<DocumentInfo[]>([])
  const [modelsInfo, setModelsInfo] = useState<ModelsResponse>(EMPTY_MODELS)

  const [pendingMessage, setPendingMessage] = useState<string | null>(null)
  const [thinking, setThinking] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [switchingModel, setSwitchingModel] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const refreshHealth = useCallback(async () => setHealth(await api.health()), [])
  const refreshConversation = useCallback(
    async () => setMessages(await api.getConversation()),
    [],
  )
  const refreshDocuments = useCallback(
    async () => setDocuments(await api.documents()),
    [],
  )
  const refreshModels = useCallback(async () => setModelsInfo(await api.models()), [])

  const load = useCallback(async () => {
    setInitializing(true)
    setInitError(null)
    try {
      await Promise.all([
        refreshHealth(),
        refreshConversation(),
        refreshDocuments(),
        refreshModels(),
      ])
    } catch (e) {
      setInitError(errorMessage(e))
    } finally {
      setInitializing(false)
    }
  }, [refreshHealth, refreshConversation, refreshDocuments, refreshModels])

  useEffect(() => {
    load()
  }, [load])

  async function handleSend(message: string) {
    setPendingMessage(message)
    setThinking(true)
    setError(null)
    try {
      await api.chat(message)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setPendingMessage(null)
      setThinking(false)
      await Promise.allSettled([refreshConversation(), refreshHealth()])
    }
  }

  async function handleUpload(file: File) {
    setUploading(true)
    setError(null)
    try {
      await api.upload(file)
      await Promise.all([refreshDocuments(), refreshConversation()])
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setUploading(false)
    }
  }

  async function handleReset() {
    setError(null)
    try {
      await api.resetConversation()
      await refreshConversation()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function handleSelectModel(name: string) {
    setSwitchingModel(true)
    setError(null)
    try {
      await api.setModel(name)
      await Promise.all([refreshModels(), refreshHealth()])
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setSwitchingModel(false)
    }
  }

  if (initializing) {
    return (
      <div className="flex h-screen items-center justify-center text-neutral-400">
        Connecting…
      </div>
    )
  }

  if (initError) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-3 text-center">
        <p className="text-lg font-medium text-neutral-800">
          Can't reach the backend.
        </p>
        <p className="max-w-md text-sm text-neutral-500">{initError}</p>
        <button
          type="button"
          onClick={load}
          className="rounded-lg bg-neutral-900 px-4 py-2 text-sm font-medium text-white"
        >
          Retry
        </button>
      </div>
    )
  }

  const chatDisabled = thinking || !health?.healthy || !health?.model

  return (
    <div className="flex h-screen bg-neutral-100">
      <Sidebar
        open={sidebarOpen}
        health={health}
        documents={documents}
        uploading={uploading}
        onUpload={handleUpload}
        onReset={handleReset}
        onRecheckHealth={refreshHealth}
        models={modelsInfo.models}
        currentModel={modelsInfo.current}
        switchingModel={switchingModel}
        onSelectModel={handleSelectModel}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-3 border-b border-neutral-200 bg-white px-4 py-3 md:hidden">
          <button
            type="button"
            onClick={() => setSidebarOpen((v) => !v)}
            className="rounded-md border border-neutral-300 px-2 py-1 text-sm"
          >
            ☰
          </button>
          <span className="font-medium text-neutral-800">
            Local AI Assistant
          </span>
        </div>

        {error && (
          <div className="border-b border-red-200 bg-red-50 px-6 py-2 text-sm text-red-700">
            {error}
          </div>
        )}
        {!chatDisabled ? null : !health?.healthy ? (
          <div className="border-b border-amber-200 bg-amber-50 px-6 py-2 text-sm text-amber-700">
            Ollama isn't reachable. Start it, then check the status in the
            sidebar.
          </div>
        ) : !health?.model ? (
          <div className="border-b border-amber-200 bg-amber-50 px-6 py-2 text-sm text-amber-700">
            OLLAMA_MODEL isn't set on the backend.
          </div>
        ) : null}

        <Transcript
          messages={messages}
          pendingMessage={pendingMessage}
          thinking={thinking}
        />

        <Composer disabled={chatDisabled} onSend={handleSend} />
      </div>
    </div>
  )
}

export default App
