import { useCallback, useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { api } from '../api'
import { formatBytes, formatRelativeTime } from '../format'
import type {
  CatalogModel,
  CatalogResponse,
  InstalledModel,
  ModelInfo,
  PullProgress,
  TrendingResponse,
  UpdatesResponse,
  VaultResponse,
  VaultTransfer,
} from '../types'
import { ProvidersPanel } from './ProvidersPanel'

// The Models page (Phase 25): everything about which models are on this
// machine, which are worth having, whether they're current, and how to keep
// them safe. Each tab fetches lazily on first open and owns its own state —
// the page never asks App for anything beyond the installed list (for the
// providers tab) and a refresh callback after any change to the installed set.

type Tab = 'installed' | 'catalog' | 'updates' | 'vault' | 'build' | 'providers'

const TABS: { id: Tab; label: string }[] = [
  { id: 'installed', label: 'Installed' },
  { id: 'catalog', label: 'Catalog' },
  { id: 'updates', label: 'Updates & trending' },
  { id: 'vault', label: 'Vault' },
  { id: 'build', label: 'Build' },
  { id: 'providers', label: 'Providers' },
]

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

function formatContext(length: number | null): string {
  if (!length) return '—'
  if (length >= 1024) return `${Math.round(length / 1024)}k`
  return String(length)
}

function formatCount(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

const CHIP_TONES = {
  denim: 'bg-denim-100 text-denim-700',
  neutral: 'bg-neutral-200 text-neutral-600',
  green: 'bg-green-100 text-green-700',
  amber: 'bg-amber-100 text-amber-700',
  red: 'bg-red-100 text-red-700',
} as const

function Chip({
  children,
  tone = 'neutral',
}: {
  children: ReactNode
  tone?: keyof typeof CHIP_TONES
}) {
  return (
    <span
      className={`inline-block shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${CHIP_TONES[tone]}`}
    >
      {children}
    </span>
  )
}

const BUTTON = {
  primary:
    'rounded-md bg-denim-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-denim-700 disabled:opacity-50',
  secondary:
    'rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-sm font-medium text-neutral-700 hover:bg-neutral-100 disabled:opacity-50',
  danger:
    'rounded-md border border-red-300 bg-white px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50',
  link: 'text-xs font-medium text-denim-700 hover:underline disabled:opacity-50',
}

const INPUT =
  'rounded-md border border-neutral-300 bg-white px-2.5 py-1.5 text-sm text-neutral-800 focus:border-denim-400 focus:outline-none'

function SectionHeader({
  title,
  children,
}: {
  title: string
  children?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="text-base font-semibold text-neutral-900">{title}</h2>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  )
}

function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
      {message}
    </div>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-lg border border-dashed border-neutral-300 px-4 py-6 text-center text-sm text-neutral-400">
      {children}
    </p>
  )
}

// Ollama streams the same `status` string for many events while only the
// completed/total byte counts advance, so the bar is driven by the byte
// counts (when a layer is downloading) and the status line carries the phase.
function PullProgressPanel({
  name,
  progress,
}: {
  name: string
  progress: PullProgress | null
}) {
  const total = progress?.total
  const completed = progress?.completed ?? 0
  const pct = total ? Math.min(100, Math.round((completed / total) * 100)) : null

  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-denim-100 bg-denim-50 p-3">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="truncate font-medium text-denim-700">Pulling {name}</span>
        <span className="shrink-0 text-denim-600">
          {progress?.status ?? 'starting…'}
          {pct !== null ? ` · ${pct}%` : ''}
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-denim-100">
        <div
          className={`h-full bg-denim-500 transition-all duration-300 ${
            pct === null ? 'w-1/3 animate-pulse' : ''
          }`}
          style={pct === null ? undefined : { width: `${pct}%` }}
        />
      </div>
      {total ? (
        <span className="text-xs text-neutral-400">
          {formatBytes(completed)} / {formatBytes(total)}
        </span>
      ) : null}
    </div>
  )
}

// Pull state is shared across the Catalog and Updates tabs so a pull started
// on one tab keeps its progress panel if the user switches to the other.
function usePull(onChanged: () => Promise<void>) {
  const [pulling, setPulling] = useState<string | null>(null)
  const [progress, setProgress] = useState<PullProgress | null>(null)
  const [error, setError] = useState<string | null>(null)

  const pull = useCallback(
    async (name: string) => {
      setError(null)
      setPulling(name)
      setProgress(null)
      try {
        await api.pullModel(name, setProgress)
        await onChanged()
      } catch (e) {
        setError(errorMessage(e))
      } finally {
        setPulling(null)
        setProgress(null)
      }
    },
    [onChanged],
  )

  return { pulling, progress, error, pull }
}

// --- Installed ---------------------------------------------------------------

function InstalledTab({
  onChanged,
  onUseAsBase,
  refreshKey,
}: {
  onChanged: () => Promise<void>
  onUseAsBase: (name: string) => void
  refreshKey: number
}) {
  const [models, setModels] = useState<InstalledModel[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [exportResult, setExportResult] = useState<VaultTransfer | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      setModels(await api.installedModels())
    } catch (e) {
      setError(errorMessage(e))
    }
  }, [])

  useEffect(() => {
    load()
  }, [load, refreshKey])

  async function remove(name: string) {
    setBusy(name)
    setError(null)
    try {
      await api.deleteModel(name)
      setConfirmDelete(null)
      await Promise.all([load(), onChanged()])
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(null)
    }
  }

  async function exportToVault(name: string) {
    setBusy(name)
    setError(null)
    setExportResult(null)
    try {
      setExportResult(await api.vaultExport(name))
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(null)
    }
  }

  const totalSize = (models ?? []).reduce((sum, m) => sum + m.size, 0)

  return (
    <div className="flex flex-col gap-4">
      <SectionHeader title="Installed models">
        <button type="button" onClick={load} className={BUTTON.secondary}>
          Refresh
        </button>
      </SectionHeader>
      <ErrorBanner message={error} />
      {models === null ? (
        <p className="text-sm text-neutral-400">Loading…</p>
      ) : models.length === 0 ? (
        <Empty>No models installed yet — pull one from the Catalog tab.</Empty>
      ) : (
        <>
          <p className="text-sm text-neutral-500">
            {models.length} {models.length === 1 ? 'model' : 'models'} ·{' '}
            {formatBytes(totalSize)} on disk
          </p>
          {exportResult && (
            <div className="rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800">
              Exported <span className="font-medium">{exportResult.name}</span> to the vault:{' '}
              {exportResult.blobs} blobs, {formatBytes(exportResult.size)} (
              {exportResult.copied_blobs} copied, the rest were already there).
            </div>
          )}
          <ul className="flex flex-col gap-2">
            {models.map((m) => {
              const open = expanded === m.name
              return (
                <li
                  key={m.name}
                  className="rounded-lg border border-neutral-200 bg-white"
                >
                  <button
                    type="button"
                    onClick={() => setExpanded(open ? null : m.name)}
                    className="flex w-full flex-col gap-1.5 px-4 py-3 text-left"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-neutral-900">{m.name}</span>
                      {m.tool_capable && <Chip tone="denim">tools</Chip>}
                      {m.running && <Chip tone="green">loaded</Chip>}
                      {m.capabilities.includes('vision') && <Chip>vision</Chip>}
                      {m.capabilities.includes('embedding') && <Chip>embedding</Chip>}
                      <span className="ml-auto text-xs text-neutral-400">
                        {m.modified_at ? formatRelativeTime(m.modified_at) : ''}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-500">
                      <span>{m.parameter_size || '—'} params</span>
                      <span>{m.quantization_level || '—'}</span>
                      <span>{formatContext(m.context_length)} context</span>
                      <span>{formatBytes(m.size)}</span>
                      {m.family && <span>{m.family}</span>}
                      {m.license && <span className="truncate">{m.license}</span>}
                    </div>
                  </button>

                  {open && (
                    <div className="flex flex-col gap-3 border-t border-neutral-100 px-4 py-3 text-sm">
                      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
                        <Detail label="Capabilities" value={m.capabilities.join(', ') || '—'} />
                        <Detail label="Architecture" value={m.architecture || '—'} />
                        <Detail label="Families" value={m.families.join(', ') || '—'} />
                        <Detail label="Base model" value={m.base_model || '—'} />
                        <Detail
                          label="Parameter count"
                          value={m.parameter_count ? formatCount(m.parameter_count) : '—'}
                        />
                        <Detail label="Format" value={m.format || '—'} />
                        <Detail
                          label="License"
                          value={
                            m.license_link ? (
                              <a
                                href={m.license_link}
                                target="_blank"
                                rel="noreferrer"
                                className="text-denim-700 hover:underline"
                              >
                                {m.license || m.license_link}
                              </a>
                            ) : (
                              m.license || '—'
                            )
                          }
                        />
                        <Detail label="Digest" value={m.digest ? m.digest.slice(0, 16) : '—'} />
                      </dl>
                      {m.system && <PreBlock label="System prompt" text={m.system} />}
                      {m.parameters && <PreBlock label="Parameters" text={m.parameters} />}
                      {m.template && <PreBlock label="Template" text={m.template} />}

                      <div className="flex flex-wrap items-center gap-2 pt-1">
                        <button
                          type="button"
                          onClick={() => exportToVault(m.name)}
                          disabled={busy !== null}
                          className={BUTTON.secondary}
                        >
                          {busy === m.name ? 'Working…' : 'Export to vault'}
                        </button>
                        <button
                          type="button"
                          onClick={() => onUseAsBase(m.name)}
                          className={BUTTON.secondary}
                        >
                          Use as base
                        </button>
                        {confirmDelete === m.name ? (
                          <span className="flex items-center gap-2 text-xs text-neutral-600">
                            Delete {m.name} from Ollama?
                            <button
                              type="button"
                              onClick={() => remove(m.name)}
                              disabled={busy !== null}
                              className={BUTTON.danger}
                            >
                              {busy === m.name ? 'Deleting…' : 'Confirm'}
                            </button>
                            <button
                              type="button"
                              onClick={() => setConfirmDelete(null)}
                              className={BUTTON.link}
                            >
                              Cancel
                            </button>
                          </span>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setConfirmDelete(m.name)}
                            disabled={busy !== null}
                            className={BUTTON.danger}
                          >
                            Delete
                          </button>
                        )}
                      </div>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        </>
      )}
    </div>
  )
}

function Detail({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex gap-2">
      <dt className="w-28 shrink-0 text-neutral-400">{label}</dt>
      <dd className="min-w-0 break-words text-neutral-700">{value}</dd>
    </div>
  )
}

function PreBlock({ label, text }: { label: string; text: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
        {label}
      </span>
      <pre className="max-h-48 overflow-auto rounded-md border border-neutral-200 bg-neutral-50 p-2 font-mono text-xs whitespace-pre-wrap text-neutral-700">
        {text}
      </pre>
    </div>
  )
}

// --- Catalog -----------------------------------------------------------------

const CATEGORY_ORDER = ['general', 'coding', 'reasoning', 'vision', 'embedding', 'small']

function CatalogTab({
  pull,
  pulling,
  progress,
  pullError,
  refreshKey,
}: {
  pull: (name: string) => Promise<void>
  pulling: string | null
  progress: PullProgress | null
  pullError: string | null
  refreshKey: number
}) {
  const [catalog, setCatalog] = useState<CatalogResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [category, setCategory] = useState<string>('all')
  const [customTag, setCustomTag] = useState('')

  const load = useCallback(async () => {
    setError(null)
    try {
      setCatalog(await api.catalog())
    } catch (e) {
      setError(errorMessage(e))
    }
  }, [])

  useEffect(() => {
    load()
  }, [load, refreshKey])

  const categories = catalog
    ? Array.from(new Set(catalog.models.map((m) => m.category))).sort(
        (a, b) => CATEGORY_ORDER.indexOf(a) - CATEGORY_ORDER.indexOf(b),
      )
    : []
  const visible = (catalog?.models ?? []).filter(
    (m) => category === 'all' || m.category === category,
  )

  return (
    <div className="flex flex-col gap-4">
      <SectionHeader title="Catalog">
        <button type="button" onClick={load} className={BUTTON.secondary}>
          Refresh
        </button>
      </SectionHeader>
      {catalog && (
        <p className="text-sm text-neutral-500">
          Seed updated {catalog.updated}. {catalog.note}
        </p>
      )}
      <ErrorBanner message={error ?? pullError} />
      {catalog?.errors.length ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          {catalog.errors.length} catalog entries were skipped: {catalog.errors.join('; ')}
        </div>
      ) : null}

      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          if (customTag.trim()) {
            pull(customTag.trim())
            setCustomTag('')
          }
        }}
        className="flex flex-wrap items-center gap-2 rounded-lg border border-neutral-200 bg-white p-3"
      >
        <label className="text-sm font-medium text-neutral-700">Pull any tag</label>
        <input
          value={customTag}
          onChange={(e) => setCustomTag(e.target.value)}
          placeholder="qwen3:8b or hf.co/<org>/<repo>:Q4_K_M"
          className={`${INPUT} min-w-0 flex-1 font-mono`}
        />
        <button
          type="submit"
          disabled={pulling !== null || !customTag.trim()}
          className={BUTTON.primary}
        >
          Pull
        </button>
      </form>

      {pulling && <PullProgressPanel name={pulling} progress={progress} />}

      {catalog === null ? (
        <p className="text-sm text-neutral-400">Loading…</p>
      ) : (
        <>
          <div className="flex flex-wrap gap-1.5">
            {['all', ...categories].map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setCategory(c)}
                className={`rounded-full px-3 py-1 text-xs font-medium capitalize transition ${
                  category === c
                    ? 'bg-denim-600 text-white'
                    : 'border border-neutral-300 bg-white text-neutral-600 hover:bg-neutral-100'
                }`}
              >
                {c}
              </button>
            ))}
          </div>
          {visible.length === 0 ? (
            <Empty>Nothing in this category.</Empty>
          ) : (
            <ul className="flex flex-col gap-3">
              {visible.map((m) => (
                <CatalogCard key={m.name} model={m} pull={pull} pulling={pulling} />
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}

function CatalogCard({
  model,
  pull,
  pulling,
}: {
  model: CatalogModel
  pull: (name: string) => Promise<void>
  pulling: string | null
}) {
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-neutral-200 bg-white px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-neutral-900">
          {model.recommended && (
            <span aria-label="recommended" className="mr-1 text-amber-500">
              ★
            </span>
          )}
          {model.name}
        </span>
        <span className="text-xs text-neutral-400">{model.org}</span>
        <Chip>{model.category}</Chip>
        {model.capabilities.map((c) => (
          <Chip key={c} tone="denim">
            {c}
          </Chip>
        ))}
        {model.installed_any && <Chip tone="green">installed</Chip>}
      </div>
      <p className="text-sm text-neutral-600">{model.description}</p>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-500">
        <span>License: {model.license}</span>
        {model.hf_repo && (
          <a
            href={`https://huggingface.co/${model.hf_repo}`}
            target="_blank"
            rel="noreferrer"
            className="text-denim-700 hover:underline"
          >
            {model.hf_repo}
          </a>
        )}
      </div>
      {model.notes && <p className="text-xs text-neutral-500">{model.notes}</p>}
      <div className="flex flex-wrap gap-1.5 pt-1">
        {model.ollama_tags.map((t) =>
          t.installed ? (
            <span
              key={t.tag}
              className="rounded-full border border-green-200 bg-green-50 px-2.5 py-1 font-mono text-xs text-green-700"
            >
              ✓ {t.tag} <span className="text-green-600/70">{t.size}</span>
            </span>
          ) : (
            <button
              key={t.tag}
              type="button"
              onClick={() => pull(t.tag)}
              disabled={pulling !== null}
              className="rounded-full border border-neutral-300 bg-white px-2.5 py-1 font-mono text-xs text-neutral-700 hover:border-denim-400 hover:bg-denim-50 disabled:opacity-50"
            >
              {pulling === t.tag ? 'pulling…' : 'Pull'} {t.tag}{' '}
              <span className="text-neutral-400">{t.size}</span>
            </button>
          ),
        )}
      </div>
    </li>
  )
}

// --- Updates & trending --------------------------------------------------------

const UPDATE_TONES: Record<string, keyof typeof CHIP_TONES> = {
  up_to_date: 'green',
  update_available: 'amber',
  unknown: 'neutral',
  skipped: 'neutral',
}

function OfflineNote({ error }: { error: string | null }) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2 text-sm text-neutral-600">
      Offline — couldn't reach the network{error ? `: ${error}` : ''}. Everything
      installed keeps working; try again when you're connected.
    </div>
  )
}

function UpdatesTab({
  pull,
  pulling,
  progress,
  pullError,
}: {
  pull: (name: string) => Promise<void>
  pulling: string | null
  progress: PullProgress | null
  pullError: string | null
}) {
  const [updates, setUpdates] = useState<UpdatesResponse | null>(null)
  const [trending, setTrending] = useState<TrendingResponse | null>(null)
  const [checking, setChecking] = useState(false)
  const [loadingTrending, setLoadingTrending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const check = useCallback(async (refresh: boolean) => {
    setChecking(true)
    setError(null)
    try {
      setUpdates(await api.modelUpdates(refresh))
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setChecking(false)
    }
  }, [])

  const loadTrending = useCallback(async (refresh: boolean) => {
    setLoadingTrending(true)
    setError(null)
    try {
      setTrending(await api.trending(20, refresh))
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setLoadingTrending(false)
    }
  }, [])

  useEffect(() => {
    check(false)
    loadTrending(false)
  }, [check, loadTrending])

  return (
    <div className="flex flex-col gap-6">
      <ErrorBanner message={error ?? pullError} />
      {pulling && <PullProgressPanel name={pulling} progress={progress} />}

      <section className="flex flex-col gap-3">
        <SectionHeader title="Updates for installed models">
          {updates?.checked_at && (
            <span className="text-xs text-neutral-400">
              checked {formatRelativeTime(updates.checked_at)}
            </span>
          )}
          <button
            type="button"
            onClick={() => check(true)}
            disabled={checking}
            className={BUTTON.primary}
          >
            {checking ? 'Checking…' : 'Check for updates'}
          </button>
        </SectionHeader>
        {updates === null ? (
          <p className="text-sm text-neutral-400">{checking ? 'Checking…' : ''}</p>
        ) : updates.offline || updates.error ? (
          <OfflineNote error={updates.error} />
        ) : updates.models.length === 0 ? (
          <Empty>No installed models to check.</Empty>
        ) : (
          <ul className="divide-y divide-neutral-100 rounded-lg border border-neutral-200 bg-white">
            {updates.models.map((u) => (
              <li
                key={u.name}
                className="flex flex-wrap items-center gap-2 px-4 py-2.5 text-sm"
              >
                <span className="font-medium text-neutral-900">{u.name}</span>
                <Chip tone={UPDATE_TONES[u.status] ?? 'neutral'}>
                  {u.status.replace(/_/g, ' ')}
                </Chip>
                {u.reason && <span className="text-xs text-neutral-400">{u.reason}</span>}
                {u.status === 'update_available' && (
                  <button
                    type="button"
                    onClick={() => pull(u.name)}
                    disabled={pulling !== null}
                    className={`${BUTTON.secondary} ml-auto`}
                  >
                    {pulling === u.name ? 'Pulling…' : 'Pull update'}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <SectionHeader title="Trending on Hugging Face (GGUF)">
          {trending?.fetched_at && (
            <span className="text-xs text-neutral-400">
              fetched {formatRelativeTime(trending.fetched_at)}
            </span>
          )}
          <button
            type="button"
            onClick={() => loadTrending(true)}
            disabled={loadingTrending}
            className={BUTTON.secondary}
          >
            {loadingTrending ? 'Loading…' : 'Refresh'}
          </button>
        </SectionHeader>
        <p className="text-xs text-neutral-500">
          Any GGUF repo pulls straight into Ollama as{' '}
          <code className="rounded bg-neutral-100 px-1">hf.co/&lt;org&gt;/&lt;repo&gt;</code> —
          nothing is limited to Ollama's own library.
        </p>
        {trending === null ? (
          <p className="text-sm text-neutral-400">{loadingTrending ? 'Loading…' : ''}</p>
        ) : trending.offline || trending.error ? (
          <OfflineNote error={trending.error} />
        ) : trending.entries.length === 0 ? (
          <Empty>No trending entries returned.</Empty>
        ) : (
          <ul className="divide-y divide-neutral-100 rounded-lg border border-neutral-200 bg-white">
            {trending.entries.map((t) => (
              <li key={t.repo} className="flex flex-wrap items-center gap-2 px-4 py-2.5 text-sm">
                <a
                  href={`https://huggingface.co/${t.repo}`}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium text-neutral-900 hover:text-denim-700 hover:underline"
                >
                  {t.repo}
                </a>
                {t.pipeline && <Chip>{t.pipeline}</Chip>}
                {t.license && <Chip>{t.license}</Chip>}
                <span className="text-xs text-neutral-400">
                  ♥ {formatCount(t.likes)} · ⤓ {formatCount(t.downloads)}
                </span>
                <button
                  type="button"
                  onClick={() => pull(t.pull_tag)}
                  disabled={pulling !== null}
                  className={`${BUTTON.secondary} ml-auto`}
                  title={t.pull_tag}
                >
                  {pulling === t.pull_tag ? 'Pulling…' : 'Pull'}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

// --- Vault -------------------------------------------------------------------

function VaultTab({
  models,
  onChanged,
  refreshKey,
}: {
  models: ModelInfo[]
  onChanged: () => Promise<void>
  refreshKey: number
}) {
  const [vault, setVault] = useState<VaultResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [exportName, setExportName] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      setVault(await api.vault())
    } catch (e) {
      setError(errorMessage(e))
    }
  }, [])

  useEffect(() => {
    load()
  }, [load, refreshKey])

  async function run(name: string, action: () => Promise<VaultTransfer | VaultResponse>, verb: string) {
    setBusy(name)
    setError(null)
    setNotice(null)
    try {
      const result = await action()
      if ('blobs' in result && typeof result.blobs === 'number' && 'copied_blobs' in result) {
        setNotice(
          `${verb} ${result.name}: ${result.blobs} blobs, ${formatBytes(result.size)} (${result.copied_blobs} copied).`,
        )
      }
      setConfirmDelete(null)
      await Promise.all([load(), onChanged()])
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <SectionHeader title="Vault">
        <button type="button" onClick={load} className={BUTTON.secondary}>
          Refresh
        </button>
      </SectionHeader>
      <p className="text-sm text-neutral-600">
        The vault is a plain directory of manifests + blobs — copy it to an external
        drive; a vaulted model survives its upstream being pulled or paywalled.
      </p>
      {vault && (
        <p className="text-xs text-neutral-500">
          Location: <code className="rounded bg-neutral-100 px-1 font-mono">{vault.vault_dir}</code>{' '}
          (set <code className="rounded bg-neutral-100 px-1 font-mono">MODEL_VAULT_DIR</code> to
          change it)
        </p>
      )}
      <ErrorBanner message={error} />
      {notice && (
        <div className="rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800">
          {notice}
        </div>
      )}

      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          if (exportName) run(exportName, () => api.vaultExport(exportName), 'Exported')
        }}
        className="flex flex-wrap items-center gap-2 rounded-lg border border-neutral-200 bg-white p-3"
      >
        <label className="text-sm font-medium text-neutral-700">Export an installed model</label>
        <select
          value={exportName}
          onChange={(e) => setExportName(e.target.value)}
          className={`${INPUT} min-w-0 flex-1`}
        >
          <option value="">Choose a model…</option>
          {models.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name} ({formatBytes(m.size)})
            </option>
          ))}
        </select>
        <button
          type="submit"
          disabled={!exportName || busy !== null}
          className={BUTTON.primary}
        >
          {busy === exportName && exportName ? 'Exporting…' : 'Export'}
        </button>
      </form>

      {vault === null ? (
        <p className="text-sm text-neutral-400">Loading…</p>
      ) : vault.entries.length === 0 ? (
        <Empty>The vault is empty — export a model above to archive it.</Empty>
      ) : (
        <ul className="flex flex-col gap-2">
          {vault.entries.map((entry) => (
            <li
              key={entry.safe_name}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-neutral-200 bg-white px-4 py-3 text-sm"
            >
              <span className="font-medium text-neutral-900">{entry.name}</span>
              {entry.installed ? (
                <Chip tone="green">installed</Chip>
              ) : (
                <Chip tone="amber">vault only</Chip>
              )}
              {entry.error ? (
                <span className="text-xs text-red-600">{entry.error}</span>
              ) : (
                <span className="text-xs text-neutral-400">
                  {entry.exported_at ? `exported ${formatRelativeTime(entry.exported_at)}` : ''}
                  {entry.size !== null ? ` · ${formatBytes(entry.size)}` : ''}
                  {entry.blobs !== null ? ` · ${entry.blobs} blobs` : ''}
                </span>
              )}
              <span className="ml-auto flex items-center gap-2">
                {!entry.installed && !entry.error && (
                  <button
                    type="button"
                    onClick={() => run(entry.name, () => api.vaultImport(entry.name), 'Imported')}
                    disabled={busy !== null}
                    className={BUTTON.secondary}
                  >
                    {busy === entry.name ? 'Importing…' : 'Import'}
                  </button>
                )}
                {confirmDelete === entry.name ? (
                  <>
                    <span className="text-xs text-neutral-600">Remove from vault?</span>
                    <button
                      type="button"
                      onClick={() => run(entry.name, () => api.vaultDelete(entry.name), 'Deleted')}
                      disabled={busy !== null}
                      className={BUTTON.danger}
                    >
                      {busy === entry.name ? 'Deleting…' : 'Confirm'}
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmDelete(null)}
                      className={BUTTON.link}
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={() => setConfirmDelete(entry.name)}
                    disabled={busy !== null}
                    className={BUTTON.link}
                  >
                    Delete from vault
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// --- Build -------------------------------------------------------------------

function BuildTab({
  models,
  initialBase,
  onCreated,
}: {
  models: ModelInfo[]
  initialBase: string
  onCreated: () => Promise<void>
}) {
  const [name, setName] = useState('')
  const [base, setBase] = useState(initialBase)
  const [system, setSystem] = useState('')
  const [temperature, setTemperature] = useState('')
  const [numCtx, setNumCtx] = useState('')
  const [template, setTemplate] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (initialBase) setBase(initialBase)
  }, [initialBase])

  const nameValid = /^[a-z0-9][a-z0-9._-]*(:[a-z0-9._-]+)?$/i.test(name.trim())

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!nameValid || !base) return
    setBusy(true)
    setError(null)
    const parameters: Record<string, unknown> = {}
    if (temperature.trim()) parameters.temperature = Number(temperature)
    if (numCtx.trim()) parameters.num_ctx = Number(numCtx)
    try {
      await api.createModel({
        name: name.trim(),
        from_model: base,
        system: system.trim() || undefined,
        parameters: Object.keys(parameters).length ? parameters : undefined,
        template: template.trim() || undefined,
      })
      setName('')
      setSystem('')
      setTemperature('')
      setNumCtx('')
      setTemplate('')
      await onCreated()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <SectionHeader title="Build a custom model" />
      <p className="text-sm text-neutral-600">
        Create a new local tag from an installed base with its own system prompt and
        parameters (an <code className="rounded bg-neutral-100 px-1 font-mono">ollama create</code>).
        Custom builds export to the vault like any other model.
      </p>
      <ErrorBanner message={error} />
      <div className="grid grid-cols-1 gap-4 rounded-lg border border-neutral-200 bg-white p-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-neutral-700">Name</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="my-assistant:v1"
            className={`${INPUT} font-mono`}
          />
          {name && !nameValid && (
            <span className="text-xs text-amber-600">
              Use letters, digits, dots, dashes; an optional :tag.
            </span>
          )}
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-neutral-700">Base model</span>
          <select value={base} onChange={(e) => setBase(e.target.value)} className={INPUT}>
            <option value="">Choose an installed model…</option>
            {models.map((m) => (
              <option key={m.name} value={m.name}>
                {m.name}
                {m.tool_capable ? '' : ' (no tools)'}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm sm:col-span-2">
          <span className="font-medium text-neutral-700">System prompt</span>
          <textarea
            value={system}
            onChange={(e) => setSystem(e.target.value)}
            rows={5}
            placeholder="You are…"
            className={`${INPUT} resize-y`}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-neutral-700">Temperature</span>
          <input
            type="number"
            step="0.05"
            min="0"
            max="2"
            value={temperature}
            onChange={(e) => setTemperature(e.target.value)}
            placeholder="base default"
            className={INPUT}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-neutral-700">Context window (num_ctx)</span>
          <input
            type="number"
            step="1024"
            min="512"
            value={numCtx}
            onChange={(e) => setNumCtx(e.target.value)}
            placeholder="base default"
            className={INPUT}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm sm:col-span-2">
          <span className="font-medium text-neutral-700">
            Template <span className="font-normal text-neutral-400">(optional, advanced)</span>
          </span>
          <textarea
            value={template}
            onChange={(e) => setTemplate(e.target.value)}
            rows={3}
            placeholder="Leave empty to inherit the base model's chat template."
            className={`${INPUT} resize-y font-mono`}
          />
        </label>
      </div>
      <div>
        <button
          type="submit"
          disabled={busy || !nameValid || !base}
          className={BUTTON.primary}
        >
          {busy ? 'Creating…' : 'Create model'}
        </button>
      </div>
    </form>
  )
}

// --- Page --------------------------------------------------------------------

export function ModelsPage({
  models,
  onChanged,
}: {
  models: ModelInfo[]
  onChanged: () => Promise<void>
}) {
  const [tab, setTab] = useState<Tab>('installed')
  const [buildBase, setBuildBase] = useState('')
  // Bumped after any change to the installed set so tabs that were already
  // opened (and therefore already fetched) reload the next time they render.
  const [refreshKey, setRefreshKey] = useState(0)

  const changed = useCallback(async () => {
    await onChanged()
    setRefreshKey((k) => k + 1)
  }, [onChanged])

  const { pulling, progress, error: pullError, pull } = usePull(changed)

  return (
    <div className="flex-1 overflow-y-auto px-6 py-8">
      <div className="mx-auto flex max-w-4xl flex-col gap-6">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900">Models</h1>
          <p className="mt-1 text-sm text-neutral-500">
            What's installed, what's worth having, whether it's current, and how to keep
            it safe — all local.
          </p>
        </div>

        <div className="flex flex-wrap gap-1 border-b border-neutral-200">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition ${
                tab === t.id
                  ? 'border-denim-600 text-denim-800'
                  : 'border-transparent text-neutral-500 hover:text-neutral-800'
              }`}
            >
              {t.label}
              {t.id === 'catalog' && pulling && (
                <span className="ml-1.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-denim-500 align-middle" />
              )}
            </button>
          ))}
        </div>

        {tab === 'installed' && (
          <InstalledTab
            onChanged={changed}
            refreshKey={refreshKey}
            onUseAsBase={(name) => {
              setBuildBase(name)
              setTab('build')
            }}
          />
        )}
        {tab === 'catalog' && (
          <CatalogTab
            pull={pull}
            pulling={pulling}
            progress={progress}
            pullError={pullError}
            refreshKey={refreshKey}
          />
        )}
        {tab === 'updates' && (
          <UpdatesTab pull={pull} pulling={pulling} progress={progress} pullError={pullError} />
        )}
        {tab === 'vault' && (
          <VaultTab models={models} onChanged={changed} refreshKey={refreshKey} />
        )}
        {tab === 'build' && (
          <BuildTab
            models={models}
            initialBase={buildBase}
            onCreated={async () => {
              await changed()
              setTab('installed')
            }}
          />
        )}
        {tab === 'providers' && <ProvidersPanel models={models} onChanged={onChanged} />}
      </div>
    </div>
  )
}
