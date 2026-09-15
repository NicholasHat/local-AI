import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import { api } from '../api'
import { formatRelativeTime } from '../format'
import type {
  DocumentInfo,
  ProjectDetail,
  ProjectLink,
  ProjectLinkKind,
  ProjectSummary,
} from '../types'

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

const markdownComponents: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-2 list-disc pl-5 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 list-decimal pl-5 last:mb-0">{children}</ol>,
  h1: ({ children }) => <h1 className="mb-2 text-lg font-semibold">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-2 text-base font-semibold">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-1 text-sm font-semibold">{children}</h3>,
  code: ({ children }) => (
    <code className="rounded bg-neutral-100 px-1 py-0.5 font-mono text-[13px]">
      {children}
    </code>
  ),
  pre: ({ children }) => (
    <pre className="mb-2 overflow-x-auto rounded-lg bg-neutral-900 p-3 font-mono text-[13px] text-neutral-100 last:mb-0">
      {children}
    </pre>
  ),
}

const LINK_KIND_STYLES: Record<ProjectLinkKind, string> = {
  workflow: 'bg-denim-100 text-denim-700',
  arena: 'bg-amber-100 text-amber-700',
  bench: 'bg-green-100 text-green-700',
}

function SectionTitle({ children }: { children: string }) {
  return (
    <h3 className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
      {children}
    </h3>
  )
}

function LinkRow({ link, onOpen }: { link: ProjectLink; onOpen: () => void }) {
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-neutral-700 hover:bg-neutral-100"
      >
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${LINK_KIND_STYLES[link.kind]}`}
        >
          {link.kind}
        </span>
        <span className="min-w-0 flex-1 truncate">{link.title || link.id}</span>
        <span className="shrink-0 text-xs text-neutral-400">
          {formatRelativeTime(link.ts)}
        </span>
      </button>
    </li>
  )
}

export function ProjectsPage({
  documents,
  onActiveChanged,
  onOpenSpace,
  onOpenJob,
}: {
  documents: DocumentInfo[]
  onActiveChanged: () => Promise<void>
  onOpenSpace: (spaceId: string) => void
  onOpenJob: (kind: ProjectLinkKind, id: string) => void
}) {
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<ProjectDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [newName, setNewName] = useState('')
  const [newGoal, setNewGoal] = useState('')

  // Editable copies of the selected project's fields. `detail` is what the
  // backend last said; these are what the human is typing. Reset whenever a
  // different project's detail lands.
  const [nameDraft, setNameDraft] = useState('')
  const [goalDraft, setGoalDraft] = useState('')
  const [notesDraft, setNotesDraft] = useState('')
  const [notesPreview, setNotesPreview] = useState(false)
  const [attachChoice, setAttachChoice] = useState('')

  const refreshList = useCallback(async () => {
    const response = await api.projects()
    setProjects(response.projects)
    setActiveId(response.active)
    return response
  }, [])

  const refreshDetail = useCallback(async (id: string) => {
    const project = await api.project(id)
    setDetail(project)
    return project
  }, [])

  useEffect(() => {
    refreshList()
      .then((response) => {
        setSelectedId((current) => current ?? response.active ?? response.projects[0]?.id ?? null)
      })
      .catch((e) => setError(errorMessage(e)))
  }, [refreshList])

  useEffect(() => {
    if (!selectedId) {
      setDetail(null)
      return
    }
    let cancelled = false
    api
      .project(selectedId)
      .then((project) => {
        if (cancelled) return
        setDetail(project)
        setNameDraft(project.name)
        setGoalDraft(project.goal)
        setNotesDraft(project.notes)
        setNotesPreview(false)
        setAttachChoice('')
      })
      .catch((e) => {
        if (!cancelled) setError(errorMessage(e))
      })
    return () => {
      cancelled = true
    }
  }, [selectedId])

  // Run a mutation, then re-fetch — the backend is the source of truth.
  async function mutate(action: () => Promise<unknown>, options?: { refreshDrafts?: boolean }) {
    setBusy(true)
    setError(null)
    try {
      await action()
      await refreshList()
      if (selectedId) {
        const project = await refreshDetail(selectedId)
        if (options?.refreshDrafts) {
          setNameDraft(project.name)
          setGoalDraft(project.goal)
          setNotesDraft(project.notes)
        }
      }
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    if (!newName.trim() || busy) return
    setBusy(true)
    setError(null)
    try {
      const created = await api.createProject(newName.trim(), newGoal.trim())
      setNewName('')
      setNewGoal('')
      await refreshList()
      setSelectedId(created.id)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete(id: string) {
    setBusy(true)
    setError(null)
    try {
      await api.deleteProject(id)
      const response = await refreshList()
      if (selectedId === id) {
        setSelectedId(response.projects[0]?.id ?? null)
      }
      if (activeId === id) await onActiveChanged()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  async function handleToggleActive() {
    if (!detail) return
    const isActive = detail.id === activeId
    await mutate(() => (isActive ? api.deactivateProject() : api.activateProject(detail.id)))
    await onActiveChanged()
  }

  function saveNameIfChanged() {
    if (!detail) return
    const name = nameDraft.trim()
    if (!name) {
      setNameDraft(detail.name)
      return
    }
    if (name !== detail.name) mutate(() => api.updateProject(detail.id, { name }))
  }

  function saveGoalIfChanged() {
    if (!detail) return
    const goal = goalDraft.trim()
    if (goal !== detail.goal) mutate(() => api.updateProject(detail.id, { goal }))
  }

  const notesDirty = detail !== null && notesDraft !== detail.notes

  function saveNotes() {
    if (!detail || !notesDirty) return
    mutate(() => api.updateProject(detail.id, { notes: notesDraft }))
  }

  const attachable = detail
    ? documents.filter((d) => !detail.documents.includes(d.filename))
    : []

  function attach() {
    if (!detail || !attachChoice) return
    const filename = attachChoice
    setAttachChoice('')
    mutate(() => api.attachProjectDocument(detail.id, filename))
  }

  const isActive = detail !== null && detail.id === activeId

  return (
    <div className="flex-1 overflow-y-auto px-6 py-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-1">
        <h1 className="text-xl font-semibold text-neutral-900">Projects</h1>
        <p className="mb-4 text-sm text-neutral-500">
          A goal, notes, attached documents, and links to the chats and runs that
          served it. Activate a project to focus the assistant on it.
        </p>

        {error && (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="flex flex-col gap-6 md:flex-row">
          {/* Left: list + create */}
          <div className="flex w-full shrink-0 flex-col gap-4 md:w-72">
            <form
              onSubmit={handleCreate}
              className="flex flex-col gap-2 rounded-lg border border-neutral-200 bg-white p-3"
            >
              <SectionTitle>New project</SectionTitle>
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Name"
                className="rounded-md border border-neutral-300 px-2.5 py-1.5 text-sm focus:border-denim-400 focus:outline-none"
              />
              <textarea
                value={newGoal}
                onChange={(e) => setNewGoal(e.target.value)}
                placeholder="Goal (optional)"
                rows={2}
                className="resize-none rounded-md border border-neutral-300 px-2.5 py-1.5 text-sm focus:border-denim-400 focus:outline-none"
              />
              <button
                type="submit"
                disabled={!newName.trim() || busy}
                className="rounded-md bg-denim-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-denim-700 disabled:opacity-50"
              >
                Create
              </button>
            </form>

            <div className="flex flex-col gap-1">
              <SectionTitle>Projects</SectionTitle>
              {projects.length === 0 && (
                <p className="rounded-lg border border-dashed border-neutral-300 px-3 py-4 text-sm text-neutral-400">
                  No projects yet. Create one to group documents, notes, and runs
                  around a goal.
                </p>
              )}
              <ul className="flex flex-col gap-0.5">
                {projects.map((p) => {
                  const selected = p.id === selectedId
                  return (
                    <li
                      key={p.id}
                      className={`group flex items-start gap-2 rounded-md px-2 py-1.5 text-sm ${
                        selected
                          ? 'bg-denim-100 text-denim-800'
                          : 'text-neutral-700 hover:bg-neutral-100'
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => setSelectedId(p.id)}
                        className="min-w-0 flex-1 text-left"
                      >
                        <span className="flex items-center gap-1.5">
                          <span className="truncate font-medium">{p.name}</span>
                          {p.id === activeId && (
                            <span className="shrink-0 rounded-full bg-green-100 px-1.5 py-0.5 text-[11px] font-medium text-green-700">
                              Active
                            </span>
                          )}
                        </span>
                        {p.goal && (
                          <span className="block truncate text-xs text-neutral-500">
                            {p.goal}
                          </span>
                        )}
                        <span className="block text-xs text-neutral-400">
                          {p.document_count} doc{p.document_count === 1 ? '' : 's'} ·{' '}
                          {formatRelativeTime(p.updated_at)}
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(p.id)}
                        disabled={busy}
                        className="shrink-0 pt-0.5 text-xs text-neutral-400 opacity-0 group-hover:opacity-100 hover:text-red-600"
                        aria-label={`Delete project ${p.name}`}
                      >
                        ✕
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>
          </div>

          {/* Right: detail */}
          <div className="min-w-0 flex-1">
            {!detail ? (
              <div className="rounded-lg border border-dashed border-neutral-300 bg-white px-6 py-12 text-center text-sm text-neutral-400">
                {projects.length === 0
                  ? 'Your first project will appear here.'
                  : 'Select a project to see its goal, notes, and documents.'}
              </div>
            ) : (
              <div className="flex flex-col gap-6">
                <div className="flex flex-col gap-3 rounded-lg border border-neutral-200 bg-white p-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <input
                      value={nameDraft}
                      onChange={(e) => setNameDraft(e.target.value)}
                      onBlur={saveNameIfChanged}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
                      }}
                      aria-label="Project name"
                      className="min-w-0 flex-1 rounded-md border border-transparent px-1 py-0.5 text-lg font-semibold text-neutral-900 hover:border-neutral-300 focus:border-denim-400 focus:outline-none"
                    />
                    {isActive && (
                      <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                        Active
                      </span>
                    )}
                    <button
                      type="button"
                      onClick={handleToggleActive}
                      disabled={busy}
                      className={`rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50 ${
                        isActive
                          ? 'border border-neutral-300 bg-white text-neutral-700 hover:bg-neutral-100'
                          : 'bg-denim-600 text-white hover:bg-denim-700'
                      }`}
                    >
                      {isActive ? 'Deactivate' : 'Activate'}
                    </button>
                  </div>
                  <p className="text-xs text-neutral-500">
                    When active, chat searches only this project's documents and sees
                    its goal and notes.
                  </p>
                  <div className="flex flex-col gap-1">
                    <SectionTitle>Goal</SectionTitle>
                    <textarea
                      value={goalDraft}
                      onChange={(e) => setGoalDraft(e.target.value)}
                      onBlur={saveGoalIfChanged}
                      placeholder="What is this project trying to achieve?"
                      rows={2}
                      className="resize-y rounded-md border border-neutral-200 px-2.5 py-1.5 text-sm text-neutral-800 focus:border-denim-400 focus:outline-none"
                    />
                  </div>
                </div>

                <div className="flex flex-col gap-2 rounded-lg border border-neutral-200 bg-white p-4">
                  <div className="flex items-center gap-2">
                    <SectionTitle>Notes</SectionTitle>
                    <span className="text-xs text-neutral-400">markdown</span>
                    <div className="ml-auto flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => setNotesPreview((v) => !v)}
                        className="rounded-md border border-neutral-300 px-2.5 py-1 text-xs font-medium text-neutral-600 hover:bg-neutral-100"
                      >
                        {notesPreview ? 'Edit' : 'Preview'}
                      </button>
                      <button
                        type="button"
                        onClick={saveNotes}
                        disabled={!notesDirty || busy}
                        className="rounded-md bg-denim-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-denim-700 disabled:opacity-50"
                      >
                        {notesDirty ? 'Save' : 'Saved'}
                      </button>
                    </div>
                  </div>
                  {notesPreview ? (
                    <div className="min-h-[8rem] rounded-md border border-neutral-100 bg-neutral-50 px-3 py-2 text-sm leading-relaxed text-neutral-800">
                      {notesDraft.trim() ? (
                        <ReactMarkdown components={markdownComponents}>
                          {notesDraft}
                        </ReactMarkdown>
                      ) : (
                        <span className="text-neutral-400">Nothing to preview.</span>
                      )}
                    </div>
                  ) : (
                    <textarea
                      value={notesDraft}
                      onChange={(e) => setNotesDraft(e.target.value)}
                      placeholder="Findings, decisions, references… Workflow outputs can be saved here too."
                      rows={8}
                      className="resize-y rounded-md border border-neutral-200 px-3 py-2 font-mono text-[13px] leading-relaxed text-neutral-800 focus:border-denim-400 focus:outline-none"
                    />
                  )}
                </div>

                <div className="grid gap-6 md:grid-cols-2">
                  <div className="flex flex-col gap-2 rounded-lg border border-neutral-200 bg-white p-4">
                    <SectionTitle>Documents</SectionTitle>
                    {detail.documents.length === 0 ? (
                      <p className="text-sm text-neutral-400">
                        No documents attached — chat will search all uploads until you
                        attach some.
                      </p>
                    ) : (
                      <ul className="flex flex-col gap-0.5">
                        {detail.documents.map((filename) => (
                          <li
                            key={filename}
                            className="group flex items-center justify-between rounded-md px-2 py-1 text-sm text-neutral-700"
                            title={filename}
                          >
                            <span className="truncate">📄 {filename}</span>
                            <button
                              type="button"
                              onClick={() =>
                                mutate(() => api.detachProjectDocument(detail.id, filename))
                              }
                              disabled={busy}
                              className="shrink-0 text-xs text-neutral-400 opacity-0 group-hover:opacity-100 hover:text-red-600"
                              aria-label={`Detach ${filename}`}
                            >
                              ✕
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                    <div className="mt-1 flex gap-2">
                      <select
                        value={attachChoice}
                        onChange={(e) => setAttachChoice(e.target.value)}
                        disabled={attachable.length === 0 || busy}
                        className="min-w-0 flex-1 rounded-md border border-neutral-300 bg-white px-2 py-1.5 text-sm disabled:opacity-50"
                      >
                        <option value="">
                          {attachable.length === 0
                            ? documents.length === 0
                              ? 'Upload a PDF in the sidebar first'
                              : 'All uploads attached'
                            : 'Choose an upload…'}
                        </option>
                        {attachable.map((d) => (
                          <option key={d.filename} value={d.filename}>
                            {d.filename}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        onClick={attach}
                        disabled={!attachChoice || busy}
                        className="rounded-md border border-neutral-300 px-3 py-1.5 text-sm font-medium text-neutral-700 hover:bg-neutral-100 disabled:opacity-50"
                      >
                        Attach
                      </button>
                    </div>
                  </div>

                  <div className="flex flex-col gap-2 rounded-lg border border-neutral-200 bg-white p-4">
                    <div className="flex items-center gap-2">
                      <SectionTitle>Links</SectionTitle>
                      <button
                        type="button"
                        onClick={() => onOpenSpace(detail.space_id)}
                        className="ml-auto rounded-md border border-neutral-300 px-2.5 py-1 text-xs font-medium text-neutral-600 hover:bg-neutral-100"
                      >
                        Open project space
                      </button>
                    </div>
                    {detail.links.length === 0 ? (
                      <p className="text-sm text-neutral-400">
                        No runs linked yet. Workflow, arena, and benchmark runs started
                        from this project will show up here.
                      </p>
                    ) : (
                      <ul className="flex flex-col gap-0.5">
                        {[...detail.links]
                          .sort((a, b) => b.ts.localeCompare(a.ts))
                          .map((link) => (
                            <LinkRow
                              key={`${link.kind}:${link.id}`}
                              link={link}
                              onOpen={() => onOpenJob(link.kind, link.id)}
                            />
                          ))}
                      </ul>
                    )}
                    <p className="mt-1 text-xs text-neutral-400">
                      {detail.conversation_ids.length} chat
                      {detail.conversation_ids.length === 1 ? '' : 's'} held while
                      this project was active.
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
