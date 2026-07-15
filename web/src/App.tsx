import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { ActivityLog } from './components/ActivityLog'
import { Composer } from './components/Composer'
import { ModelManager } from './components/ModelManager'
import { Sidebar } from './components/Sidebar'
import type { View } from './components/Sidebar'
import { SkillsPage } from './components/SkillsPage'
import { Transcript } from './components/Transcript'
import type {
  ConversationMessage,
  ConversationMeta,
  DocumentInfo,
  HealthResponse,
  ModelLibraryEntry,
  ModelsResponse,
  SkillInfo,
  SkillWriteRequest,
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
  const [modelLibrary, setModelLibrary] = useState<ModelLibraryEntry[]>([])
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [conversations, setConversations] = useState<ConversationMeta[]>([])
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null)

  const [pendingMessage, setPendingMessage] = useState<string | null>(null)
  const [thinking, setThinking] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [switchingModel, setSwitchingModel] = useState(false)
  const [skillsBusy, setSkillsBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [view, setView] = useState<View>('chat')
  const [activityLogOpen, setActivityLogOpen] = useState(false)
  const [modelManagerOpen, setModelManagerOpen] = useState(false)

  const refreshHealth = useCallback(async () => setHealth(await api.health()), [])
  const refreshConversation = useCallback(
    async () => setMessages(await api.getConversation()),
    [],
  )
  const refreshConversationList = useCallback(
    async () => setConversations(await api.conversations()),
    [],
  )
  const refreshActiveConversationId = useCallback(async () => {
    const meta = await api.activeConversation()
    setActiveConversationId(meta.id)
  }, [])
  const refreshDocuments = useCallback(
    async () => setDocuments(await api.documents()),
    [],
  )
  const refreshModels = useCallback(async () => setModelsInfo(await api.models()), [])
  const refreshModelLibrary = useCallback(
    async () => setModelLibrary(await api.modelLibrary()),
    [],
  )
  const refreshSkills = useCallback(async () => setSkills(await api.skills()), [])

  const load = useCallback(async () => {
    setInitializing(true)
    setInitError(null)
    try {
      await Promise.all([
        refreshHealth(),
        refreshConversation(),
        refreshDocuments(),
        refreshModels(),
        refreshModelLibrary(),
        refreshSkills(),
      ])
      // Sequential: the active conversation is only guaranteed to exist
      // once refreshConversation() above has hit the backend at least once.
      await refreshConversationList()
      await refreshActiveConversationId()
    } catch (e) {
      setInitError(errorMessage(e))
    } finally {
      setInitializing(false)
    }
  }, [
    refreshHealth,
    refreshConversation,
    refreshDocuments,
    refreshModels,
    refreshModelLibrary,
    refreshSkills,
    refreshConversationList,
    refreshActiveConversationId,
  ])

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
      await Promise.allSettled([
        refreshConversation(),
        refreshHealth(),
        refreshSkills(),
        refreshConversationList(),
      ])
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

  async function handleDeleteDocument(filename: string) {
    setError(null)
    try {
      await api.deleteDocument(filename)
      await refreshDocuments()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function handleNewChat() {
    setError(null)
    try {
      const meta = await api.newConversation()
      setActiveConversationId(meta.id)
      await Promise.all([refreshConversation(), refreshConversationList()])
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function handleSelectConversation(id: string) {
    setError(null)
    try {
      await api.activateConversation(id)
      setActiveConversationId(id)
      await refreshConversation()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function handleDeleteConversation(id: string) {
    setError(null)
    try {
      await api.deleteConversation(id)
      await Promise.all([
        refreshConversationList(),
        refreshActiveConversationId(),
        refreshConversation(),
      ])
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

  async function handleCreateSkill(payload: SkillWriteRequest) {
    setSkillsBusy(true)
    try {
      await api.createSkill(payload)
      await refreshSkills()
    } finally {
      setSkillsBusy(false)
    }
  }

  async function handleUpdateSkill(name: string, payload: SkillWriteRequest) {
    setSkillsBusy(true)
    try {
      await api.updateSkill(name, payload)
      await refreshSkills()
    } finally {
      setSkillsBusy(false)
    }
  }

  async function handleDeleteSkill(name: string) {
    setSkillsBusy(true)
    setError(null)
    try {
      await api.deleteSkill(name)
      await refreshSkills()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setSkillsBusy(false)
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
          className="rounded-lg bg-denim-600 px-4 py-2 text-sm font-medium text-white"
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
        view={view}
        onChangeView={(v) => {
          setView(v)
          setSidebarOpen(false)
        }}
        health={health}
        documents={documents}
        uploading={uploading}
        onUpload={handleUpload}
        onDeleteDocument={handleDeleteDocument}
        onNewChat={handleNewChat}
        onRecheckHealth={refreshHealth}
        conversations={conversations}
        activeConversationId={activeConversationId}
        onSelectConversation={handleSelectConversation}
        onDeleteConversation={handleDeleteConversation}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-3 border-b border-neutral-200 bg-white px-4 py-3">
          <button
            type="button"
            onClick={() => setSidebarOpen((v) => !v)}
            className="rounded-md border border-neutral-300 px-2 py-1 text-sm md:hidden"
          >
            ☰
          </button>
          <span className="font-medium text-neutral-800 md:hidden">
            Local AI Assistant
          </span>
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={() => setModelManagerOpen((v) => !v)}
              className="flex items-center gap-1.5 rounded-full border border-neutral-300 px-3 py-1.5 text-sm font-medium text-neutral-600 hover:border-denim-400 hover:text-denim-700"
            >
              <span aria-hidden>🧠</span> Models
            </button>
            <button
              type="button"
              onClick={() => setActivityLogOpen(true)}
              className="flex items-center gap-1.5 rounded-full border border-neutral-300 px-3 py-1.5 text-sm font-medium text-neutral-600 hover:border-denim-400 hover:text-denim-700"
            >
              <span aria-hidden>🗒️</span> Activity log
            </button>
          </div>
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

        {view === 'chat' ? (
          <>
            <Transcript
              messages={messages}
              pendingMessage={pendingMessage}
              thinking={thinking}
            />
            <Composer
              disabled={chatDisabled}
              onSend={handleSend}
              models={modelsInfo.models}
              currentModel={modelsInfo.current}
              switchingModel={switchingModel}
              onSelectModel={handleSelectModel}
            />
          </>
        ) : (
          <SkillsPage
            skills={skills}
            busy={skillsBusy}
            onCreate={handleCreateSkill}
            onUpdate={handleUpdateSkill}
            onDelete={handleDeleteSkill}
          />
        )}
      </div>

      <ActivityLog
        open={activityLogOpen}
        onClose={() => setActivityLogOpen(false)}
        messages={messages}
        thinking={thinking}
      />

      <ModelManager
        open={modelManagerOpen}
        onClose={() => setModelManagerOpen(false)}
        installed={modelsInfo.models}
        library={modelLibrary}
        onChanged={async () => {
          await Promise.all([refreshModels(), refreshHealth()])
        }}
      />
    </div>
  )
}

export default App
