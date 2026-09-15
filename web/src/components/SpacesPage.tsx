import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import { api } from '../api'
import { formatRelativeTime } from '../format'
import type { SpaceDetail, SpacePost, SpaceSummary } from '../types'

const POLL_MS = 2000

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

// Same markdown treatment as assistant chat bubbles (MessageBubble.tsx) so a
// step's report reads the same whether it arrives via chat or a space.
const markdownComponents: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-2 list-disc pl-5 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 list-decimal pl-5 last:mb-0">{children}</ol>,
  h1: ({ children }) => <h3 className="mb-1 font-semibold">{children}</h3>,
  h2: ({ children }) => <h3 className="mb-1 font-semibold">{children}</h3>,
  h3: ({ children }) => <h4 className="mb-1 font-semibold">{children}</h4>,
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

// A stable chip color per author: "critic @ llama3.1:latest" hashes to the
// same palette slot every render and every visit, so a reader learns to
// recognize a voice by color. The human ("user") gets the accent color.
const AUTHOR_PALETTE = [
  'bg-amber-100 text-amber-800',
  'bg-emerald-100 text-emerald-800',
  'bg-violet-100 text-violet-800',
  'bg-rose-100 text-rose-800',
  'bg-sky-100 text-sky-800',
  'bg-lime-100 text-lime-800',
  'bg-orange-100 text-orange-800',
  'bg-teal-100 text-teal-800',
]

function authorChipClass(author: string): string {
  if (author === 'user') return 'bg-denim-600 text-white'
  let hash = 0
  for (let i = 0; i < author.length; i++) {
    hash = (hash * 31 + author.charCodeAt(i)) | 0
  }
  return AUTHOR_PALETTE[Math.abs(hash) % AUTHOR_PALETTE.length]
}

function PostCard({ post }: { post: SpacePost }) {
  const isUser = post.author === 'user'
  return (
    <div
      className={`flex flex-col gap-1.5 rounded-lg border px-3 py-2.5 text-sm ${
        isUser ? 'border-denim-200 bg-denim-50' : 'border-neutral-200 bg-white'
      }`}
    >
      <div className="flex items-center gap-2">
        <span
          className={`max-w-[70%] truncate rounded-full px-2 py-0.5 text-xs font-medium ${authorChipClass(
            post.author,
          )}`}
          title={post.author}
        >
          {post.author}
        </span>
        <span className="ml-auto shrink-0 text-xs text-neutral-400">
          {formatRelativeTime(post.ts)}
        </span>
      </div>
      <div className="leading-relaxed text-neutral-800">
        <ReactMarkdown components={markdownComponents}>{post.content}</ReactMarkdown>
      </div>
    </div>
  )
}

function SpaceComposer({
  disabled,
  onSend,
}: {
  disabled: boolean
  onSend: (content: string) => Promise<void>
}) {
  const [value, setValue] = useState('')
  const [sending, setSending] = useState(false)

  async function submit() {
    const trimmed = value.trim()
    if (!trimmed || disabled || sending) return
    setSending(true)
    try {
      await onSend(trimmed)
      setValue('')
    } finally {
      setSending(false)
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void submit()
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-neutral-300 bg-neutral-50 px-3 py-2 focus-within:border-denim-400">
      <textarea
        rows={2}
        value={value}
        disabled={disabled || sending}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Post into this space as yourself… (Enter to send, Shift+Enter for a new line)"
        className="w-full resize-none bg-transparent px-1 py-1 text-sm text-neutral-900 outline-none placeholder:text-neutral-400 disabled:opacity-50"
      />
      <div className="flex items-center justify-between">
        <span className="text-xs text-neutral-400">Posts as “user”</span>
        <button
          type="button"
          onClick={() => void submit()}
          disabled={disabled || sending || !value.trim()}
          className="rounded-lg bg-denim-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-denim-700 disabled:opacity-50"
        >
          {sending ? 'Posting…' : 'Post'}
        </button>
      </div>
    </div>
  )
}

export function SpacesPage({ initialSpaceId }: { initialSpaceId?: string | null }) {
  const [spaces, setSpaces] = useState<SpaceSummary[]>([])
  const [listLoaded, setListLoaded] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(initialSpaceId ?? null)
  const [detail, setDetail] = useState<SpaceDetail | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [newName, setNewName] = useState('')
  const [newPurpose, setNewPurpose] = useState('')
  const [creating, setCreating] = useState(false)

  const boardEndRef = useRef<HTMLDivElement>(null)
  const lastPostCountRef = useRef(0)

  const refreshList = useCallback(async () => {
    try {
      setSpaces(await api.spaces())
      setError(null)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setListLoaded(true)
    }
  }, [])

  useEffect(() => {
    void refreshList()
  }, [refreshList])

  // Live board: poll the open space so posts from running agents show up
  // without a refresh. The interval is torn down when the selection
  // changes or the page unmounts.
  useEffect(() => {
    if (!selectedId) {
      setDetail(null)
      setDetailError(null)
      return
    }
    let cancelled = false
    lastPostCountRef.current = 0

    async function fetchDetail() {
      try {
        const next = await api.space(selectedId as string)
        if (cancelled) return
        setDetail(next)
        setDetailError(null)
      } catch (e) {
        if (cancelled) return
        setDetailError(errorMessage(e))
      }
    }

    void fetchDetail()
    const timer = setInterval(() => void fetchDetail(), POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [selectedId])

  // Scroll to the newest post only when the count grows, so reading an
  // older post isn't yanked to the bottom on every poll.
  useEffect(() => {
    const count = detail?.posts.length ?? 0
    if (count > lastPostCountRef.current) {
      boardEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
    lastPostCountRef.current = count
  }, [detail])

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    const name = newName.trim()
    if (!name) return
    setCreating(true)
    setError(null)
    try {
      const created = await api.createSpace(name, newPurpose.trim())
      setNewName('')
      setNewPurpose('')
      await refreshList()
      setSelectedId(created.id)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setCreating(false)
    }
  }

  async function handleDelete(id: string) {
    setError(null)
    try {
      await api.deleteSpace(id)
      if (selectedId === id) setSelectedId(null)
      await refreshList()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function handlePost(content: string) {
    if (!selectedId) return
    setError(null)
    try {
      const post = await api.postToSpace(selectedId, content)
      // Show it immediately rather than waiting for the next poll.
      setDetail((current) =>
        current && current.id === selectedId
          ? { ...current, posts: [...current.posts, post], updated_at: post.ts }
          : current,
      )
      void refreshList()
    } catch (err) {
      setError(errorMessage(err))
      throw err
    }
  }

  return (
    <div className="flex-1 overflow-y-auto px-6 py-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-1">
        <h1 className="text-xl font-semibold text-neutral-900">Spaces</h1>
        <p className="mb-4 text-sm text-neutral-500">
          Shared boards where models talk to each other — and to you. Every
          workflow run gets one; you can also start a space by hand and let
          agents read and post to it by id.
        </p>

        {error && (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="flex flex-col gap-6 md:flex-row">
          {/* Left: list + new-space form */}
          <div className="flex w-full flex-col gap-4 md:w-72 md:shrink-0">
            <form
              onSubmit={handleCreate}
              className="flex flex-col gap-2 rounded-lg border border-neutral-200 bg-white p-3"
            >
              <h2 className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
                New space
              </h2>
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Name"
                className="rounded-md border border-neutral-300 px-2.5 py-1.5 text-sm outline-none focus:border-denim-400"
              />
              <input
                value={newPurpose}
                onChange={(e) => setNewPurpose(e.target.value)}
                placeholder="Purpose (optional)"
                className="rounded-md border border-neutral-300 px-2.5 py-1.5 text-sm outline-none focus:border-denim-400"
              />
              <button
                type="submit"
                disabled={creating || !newName.trim()}
                className="rounded-lg bg-denim-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-denim-700 disabled:opacity-50"
              >
                {creating ? 'Creating…' : 'Create space'}
              </button>
            </form>

            <div>
              <h2 className="mb-2 text-xs font-semibold tracking-wide text-neutral-500 uppercase">
                Spaces
              </h2>
              {listLoaded && spaces.length === 0 ? (
                <p className="rounded-lg border border-dashed border-neutral-300 px-3 py-4 text-sm text-neutral-400">
                  No spaces yet — a workflow run creates one automatically, or
                  start one here.
                </p>
              ) : (
                <ul className="flex flex-col gap-0.5">
                  {spaces.map((s) => (
                    <li
                      key={s.id}
                      className={`group flex items-start justify-between gap-2 rounded-md px-2 py-1.5 text-sm ${
                        s.id === selectedId
                          ? 'bg-denim-100 text-denim-800'
                          : 'text-neutral-700 hover:bg-neutral-100'
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => setSelectedId(s.id)}
                        className="min-w-0 flex-1 text-left"
                        title={s.purpose || s.name}
                      >
                        <span className="block truncate font-medium">{s.name}</span>
                        {s.purpose && (
                          <span className="block truncate text-xs text-neutral-500">
                            {s.purpose}
                          </span>
                        )}
                        <span className="block text-xs text-neutral-400">
                          {s.post_count} {s.post_count === 1 ? 'post' : 'posts'} ·{' '}
                          {formatRelativeTime(s.updated_at)}
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleDelete(s.id)}
                        className="shrink-0 pt-0.5 text-xs text-neutral-400 opacity-0 group-hover:opacity-100 hover:text-red-600"
                        aria-label={`Delete space ${s.name}`}
                      >
                        ✕
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          {/* Right: the board */}
          <div className="flex min-w-0 flex-1 flex-col gap-3">
            {!selectedId ? (
              <div className="flex flex-1 items-center justify-center rounded-lg border border-dashed border-neutral-300 px-6 py-16 text-center text-sm text-neutral-400">
                Select a space to read its board, or create one to start a
                conversation between models.
              </div>
            ) : detailError ? (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {detailError}
              </div>
            ) : !detail ? (
              <p className="text-sm text-neutral-400">Loading…</p>
            ) : (
              <>
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <h2 className="text-lg font-semibold text-neutral-900">{detail.name}</h2>
                  {detail.purpose && (
                    <span className="text-sm text-neutral-500">{detail.purpose}</span>
                  )}
                  <span className="ml-auto flex items-center gap-1.5 text-xs text-neutral-400">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-denim-500" />
                    live · {detail.posts.length}{' '}
                    {detail.posts.length === 1 ? 'post' : 'posts'}
                  </span>
                </div>
                <p className="font-mono text-xs text-neutral-400" title="Space id">
                  id: {detail.id}
                </p>

                <div className="flex max-h-[60vh] min-h-48 flex-col gap-2 overflow-y-auto rounded-lg border border-neutral-200 bg-neutral-50 p-3">
                  {detail.posts.length === 0 ? (
                    <p className="py-8 text-center text-sm text-neutral-400">
                      Nothing posted yet. Agents post here as they work; you can
                      start the thread below.
                    </p>
                  ) : (
                    detail.posts.map((p) => <PostCard key={p.id} post={p} />)
                  )}
                  <div ref={boardEndRef} />
                </div>

                <SpaceComposer disabled={false} onSend={handlePost} />
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
