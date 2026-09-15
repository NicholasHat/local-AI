import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import type {
  ModelInfo,
  ProviderInfo,
  ProviderRole,
  ProviderWriteRequest,
  ProvidersResponse,
} from '../types'

// Roles that drive a tool-calling agent loop — routing one of these to a
// model without tool support means the loop can't call tools at all.
const AGENTIC_ROLES: ProviderRole[] = ['chat', 'coding', 'research']

const ROLE_HINTS: Record<ProviderRole, string> = {
  chat: 'The assistant in the Chat page',
  coding: 'The sandboxed coding agent',
  research: 'Research workflow steps',
  judge: 'Critique / synthesis steps and arena verdicts',
  fast: 'Quick, low-stakes steps',
  embedding: 'Document search embeddings',
}

const NAME_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

type FormState = {
  name: string
  description: string
  routes: Partial<Record<ProviderRole, string>>
}

const EMPTY_FORM: FormState = { name: '', description: '', routes: {} }

function toFormState(provider: ProviderInfo): FormState {
  return {
    name: provider.name,
    description: provider.description,
    routes: { ...provider.routes },
  }
}

function Chip({ children, tone }: { children: React.ReactNode; tone: 'denim' | 'neutral' | 'amber' }) {
  const classes =
    tone === 'denim'
      ? 'bg-denim-100 text-denim-700'
      : tone === 'amber'
        ? 'bg-amber-100 text-amber-700'
        : 'bg-neutral-200 text-neutral-600'
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${classes}`}>
      {children}
    </span>
  )
}

const BUTTON = 'rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:opacity-50'
const PRIMARY = `${BUTTON} bg-denim-600 text-white hover:bg-denim-700`
const SECONDARY = `${BUTTON} border border-neutral-300 bg-white text-neutral-700 hover:bg-neutral-100`
const DANGER = `${BUTTON} text-red-600 hover:bg-red-50`
const INPUT =
  'w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm text-neutral-800 focus:border-denim-400 focus:outline-none'

export function ProvidersPanel({
  models,
  onChanged,
}: {
  models: ModelInfo[]
  onChanged: () => Promise<void>
}) {
  const [data, setData] = useState<ProvidersResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  // null = editor closed, 'new' = creating, otherwise the name being edited.
  const [editing, setEditing] = useState<string | null>(null)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [formError, setFormError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setData(await api.providers())
  }, [])

  useEffect(() => {
    refresh().catch((e) => setError(errorMessage(e)))
  }, [refresh])

  async function withBusy(key: string, action: () => Promise<void>) {
    setBusy(key)
    setError(null)
    try {
      await action()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(null)
    }
  }

  function startCreate() {
    setForm(EMPTY_FORM)
    setFormError(null)
    setEditing('new')
  }

  function startEdit(provider: ProviderInfo) {
    setForm(toFormState(provider))
    setFormError(null)
    setEditing(provider.name)
  }

  function cancel() {
    setEditing(null)
    setFormError(null)
  }

  function setRoute(role: ProviderRole, model: string) {
    setForm((f) => {
      const routes = { ...f.routes }
      if (model) routes[role] = model
      else delete routes[role]
      return { ...f, routes }
    })
  }

  async function submit() {
    const name = form.name.trim()
    if (!NAME_PATTERN.test(name)) {
      setFormError('Name must be lowercase letters, digits, and hyphens (e.g. strongest-local).')
      return
    }
    if (name === 'default') {
      setFormError('"default" is built in — pick another name.')
      return
    }
    const payload: ProviderWriteRequest = {
      name,
      description: form.description.trim(),
      routes: form.routes,
    }
    setFormError(null)
    await withBusy('save', async () => {
      const next =
        editing === 'new' || editing !== name
          ? await api.createProvider(payload)
          : await api.updateProvider(name, payload)
      setData(next)
      setEditing(null)
      await onChanged()
    })
  }

  async function activate(name: string) {
    await withBusy(`activate:${name}`, async () => {
      setData(await api.activateProvider(name))
      await onChanged()
    })
  }

  async function remove(name: string) {
    await withBusy(`delete:${name}`, async () => {
      setData(await api.deleteProvider(name))
      if (editing === name) setEditing(null)
      await onChanged()
    })
  }

  async function recommend() {
    await withBusy('recommend', async () => {
      const recommended = await api.recommendProvider(false)
      setForm({
        name: 'recommended',
        description: recommended.description,
        routes: { ...recommended.routes },
      })
      setFormError(null)
      setEditing('new')
    })
  }

  const roles: ProviderRole[] = data?.roles ?? []
  const modelByName = new Map(models.map((m) => [m.name, m]))
  const toolless = AGENTIC_ROLES.filter((role) => {
    const chosen = form.routes[role]
    return chosen && modelByName.get(chosen)?.tool_capable === false
  })

  return (
    <div className="flex flex-col gap-6">
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Effective routing */}
      <section className="rounded-lg border border-neutral-200 bg-white p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-sm font-semibold text-neutral-900">
            Effective routing
            {data && (
              <span className="ml-2 font-normal text-neutral-500">
                via <span className="font-medium text-denim-700">{data.active}</span>
              </span>
            )}
          </h3>
          <span className="text-xs text-neutral-400">
            Resolution: explicit choice → composer override → provider route → env default
          </span>
        </div>
        {!data ? (
          <p className="mt-3 text-sm text-neutral-400">Loading…</p>
        ) : (
          <table className="mt-3 w-full text-sm">
            <tbody>
              {roles.map((role) => (
                <tr key={role} className="border-t border-neutral-100">
                  <td className="py-1.5 pr-4 font-medium text-neutral-700">{role}</td>
                  <td className="py-1.5 pr-4 text-neutral-400">{ROLE_HINTS[role]}</td>
                  <td className="py-1.5 text-right font-mono text-xs text-neutral-800">
                    {data.resolved[role] ?? (
                      <span className="text-amber-600">not configured</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Provider list */}
      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-neutral-900">Providers</h3>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={recommend}
              disabled={busy !== null}
              className={SECONDARY}
              title="Compose the strongest provider from the benchmark leaderboard"
            >
              {busy === 'recommend' ? 'Composing…' : '✨ Recommend from benchmarks'}
            </button>
            <button type="button" onClick={startCreate} disabled={busy !== null} className={PRIMARY}>
              + New provider
            </button>
          </div>
        </div>
        <p className="text-xs text-neutral-500">
          A provider says which installed model plays each role. Activate one and the whole
          app — chat, coding runs, workflows, arena judging — routes through it.
        </p>

        {data?.providers.map((provider) => {
          const isActive = provider.name === data.active
          const routeEntries = roles
            .map((role) => [role, provider.routes[role]] as const)
            .filter(([, model]) => model)
          return (
            <div
              key={provider.name}
              className={`rounded-lg border bg-white p-4 ${
                isActive ? 'border-denim-300 ring-1 ring-denim-200' : 'border-neutral-200'
              }`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-neutral-900">{provider.name}</span>
                {provider.builtin && <Chip tone="neutral">built-in</Chip>}
                {isActive && <Chip tone="denim">Active</Chip>}
                <div className="ml-auto flex gap-1">
                  {!isActive && (
                    <button
                      type="button"
                      onClick={() => activate(provider.name)}
                      disabled={busy !== null}
                      className={SECONDARY}
                    >
                      {busy === `activate:${provider.name}` ? 'Activating…' : 'Activate'}
                    </button>
                  )}
                  {!provider.builtin && (
                    <>
                      <button
                        type="button"
                        onClick={() => startEdit(provider)}
                        disabled={busy !== null}
                        className={SECONDARY}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => remove(provider.name)}
                        disabled={busy !== null}
                        className={DANGER}
                      >
                        {busy === `delete:${provider.name}` ? 'Deleting…' : 'Delete'}
                      </button>
                    </>
                  )}
                </div>
              </div>
              {provider.description && (
                <p className="mt-1 text-sm text-neutral-600">{provider.description}</p>
              )}
              <div className="mt-2 flex flex-wrap gap-1.5">
                {routeEntries.length === 0 ? (
                  <span className="text-xs text-neutral-400">
                    No routes — every role falls through to the env defaults.
                  </span>
                ) : (
                  routeEntries.map(([role, model]) => (
                    <span
                      key={role}
                      className="rounded-full border border-neutral-200 bg-neutral-50 px-2 py-0.5 text-xs text-neutral-700"
                    >
                      <span className="font-medium">{role}</span>
                      <span className="text-neutral-400">: </span>
                      <span className="font-mono">{model}</span>
                    </span>
                  ))
                )}
              </div>
            </div>
          )
        })}
      </section>

      {/* Editor */}
      {editing !== null && (
        <section className="rounded-lg border border-denim-200 bg-denim-50 p-4">
          <h3 className="text-sm font-semibold text-neutral-900">
            {editing === 'new' ? 'New provider' : `Edit ${editing}`}
          </h3>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-xs font-medium text-neutral-600">
              Name
              <input
                className={INPUT}
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="strongest-local"
                disabled={editing !== 'new'}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-neutral-600">
              Description
              <input
                className={INPUT}
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="What this routing is for"
              />
            </label>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {roles.map((role) => (
              <label key={role} className="flex flex-col gap-1 text-xs font-medium text-neutral-600">
                <span>
                  {role}
                  <span className="ml-1 font-normal text-neutral-400">— {ROLE_HINTS[role]}</span>
                </span>
                <select
                  className={INPUT}
                  value={form.routes[role] ?? ''}
                  onChange={(e) => setRoute(role, e.target.value)}
                >
                  <option value="">(fall through to default)</option>
                  {models.map((m) => (
                    <option key={m.name} value={m.name}>
                      {m.name}
                      {m.tool_capable ? '' : ' (no tools)'}
                    </option>
                  ))}
                  {form.routes[role] && !modelByName.has(form.routes[role]!) && (
                    <option value={form.routes[role]}>{form.routes[role]} (not installed)</option>
                  )}
                </select>
              </label>
            ))}
          </div>

          {toolless.length > 0 && (
            <p className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              {toolless.join(', ')} routed to a model without tool support — that role's agent
              loop won't be able to call any tools.
            </p>
          )}
          {formError && <p className="mt-3 text-sm text-red-600">{formError}</p>}

          <div className="mt-4 flex gap-2">
            <button type="button" onClick={submit} disabled={busy !== null} className={PRIMARY}>
              {busy === 'save' ? 'Saving…' : 'Save'}
            </button>
            <button type="button" onClick={cancel} disabled={busy !== null} className={SECONDARY}>
              Cancel
            </button>
          </div>
        </section>
      )}
    </div>
  )
}
