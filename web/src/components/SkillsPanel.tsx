import { useState } from 'react'
import type { SkillInfo, SkillWriteRequest } from '../types'

type FormState = {
  name: string
  description: string
  kind: 'instruction' | 'code'
  parametersText: string
  requiredText: string
  body: string
}

const EMPTY_FORM: FormState = {
  name: '',
  description: '',
  kind: 'instruction',
  parametersText: '{}',
  requiredText: '',
  body: '',
}

function toFormState(skill: SkillInfo): FormState {
  return {
    name: skill.name,
    description: skill.description,
    kind: skill.kind,
    parametersText: JSON.stringify(skill.parameters, null, 2),
    requiredText: skill.required.join(', '),
    body: skill.body,
  }
}

export function SkillsPanel({
  skills,
  busy,
  onCreate,
  onUpdate,
  onDelete,
}: {
  skills: SkillInfo[]
  busy: boolean
  onCreate: (payload: SkillWriteRequest) => Promise<void>
  onUpdate: (name: string, payload: SkillWriteRequest) => Promise<void>
  onDelete: (name: string) => void
}) {
  const [editingName, setEditingName] = useState<string | null | 'new'>(null)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [formError, setFormError] = useState<string | null>(null)

  function startCreate() {
    setForm(EMPTY_FORM)
    setFormError(null)
    setEditingName('new')
  }

  function startEdit(skill: SkillInfo) {
    setForm(toFormState(skill))
    setFormError(null)
    setEditingName(skill.name)
  }

  function cancel() {
    setEditingName(null)
    setFormError(null)
  }

  async function submit() {
    let parameters: Record<string, unknown>
    try {
      parameters = form.parametersText.trim() ? JSON.parse(form.parametersText) : {}
    } catch {
      setFormError('Parameters must be valid JSON.')
      return
    }

    const required = form.requiredText
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)

    const payload: SkillWriteRequest = {
      name: form.name.trim(),
      description: form.description.trim(),
      parameters,
      required,
      ...(form.kind === 'instruction' ? { prompt: form.body } : { code: form.body }),
    }

    if (!payload.name || !payload.description || !form.body.trim()) {
      setFormError('Name, description, and the prompt/code body are all required.')
      return
    }

    setFormError(null)
    try {
      if (editingName === 'new') {
        await onCreate(payload)
      } else if (editingName) {
        await onUpdate(editingName, payload)
      }
      setEditingName(null)
    } catch (e) {
      setFormError(e instanceof Error ? e.message : String(e))
    }
  }

  if (editingName !== null) {
    return (
      <div className="flex flex-col gap-3 rounded-xl border border-neutral-200 bg-white p-5">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <input
            value={form.name}
            disabled={editingName !== 'new'}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="slug-name"
            className="rounded-md border border-neutral-300 px-3 py-2 text-sm disabled:opacity-50"
          />
          <select
            value={form.kind}
            onChange={(e) =>
              setForm({ ...form, kind: e.target.value as 'instruction' | 'code' })
            }
            className="rounded-md border border-neutral-300 px-3 py-2 text-sm"
          >
            <option value="instruction">Instruction (prompt.md)</option>
            <option value="code">Code (run.py)</option>
          </select>
        </div>
        <input
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
          placeholder="Description"
          className="rounded-md border border-neutral-300 px-3 py-2 text-sm"
        />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <textarea
            value={form.parametersText}
            onChange={(e) => setForm({ ...form, parametersText: e.target.value })}
            placeholder='Parameters JSON, e.g. {"text": {"type": "string"}}'
            rows={3}
            className="rounded-md border border-neutral-300 px-3 py-2 font-mono text-xs"
          />
          <input
            value={form.requiredText}
            onChange={(e) => setForm({ ...form, requiredText: e.target.value })}
            placeholder="Required args, comma-separated"
            className="h-fit rounded-md border border-neutral-300 px-3 py-2 text-sm"
          />
        </div>
        <textarea
          value={form.body}
          onChange={(e) => setForm({ ...form, body: e.target.value })}
          placeholder={
            form.kind === 'instruction'
              ? 'Instruction template, use {arg_name} placeholders'
              : 'def run(**args) -> str: ...'
          }
          rows={10}
          className="rounded-md border border-neutral-300 px-3 py-2 font-mono text-xs"
        />

        {formError && <p className="text-xs text-red-600">{formError}</p>}

        <div className="flex gap-2">
          <button
            type="button"
            onClick={submit}
            disabled={busy}
            className="rounded-md bg-denim-600 px-4 py-2 text-sm font-medium text-white hover:bg-denim-700 disabled:opacity-50"
          >
            Save
          </button>
          <button
            type="button"
            onClick={cancel}
            className="rounded-md border border-neutral-300 px-4 py-2 text-sm hover:bg-neutral-50"
          >
            Cancel
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-end">
        <button
          type="button"
          onClick={startCreate}
          className="rounded-full bg-denim-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-denim-700"
        >
          + New skill
        </button>
      </div>

      {skills.length === 0 && (
        <p className="text-sm text-neutral-400">No skills yet — create one to get started.</p>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {skills.map((s) => (
          <div
            key={s.name}
            className="flex flex-col gap-2 rounded-xl border border-neutral-200 bg-white p-4"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate font-medium text-neutral-900">{s.name}</p>
                <span className="inline-block rounded-full bg-denim-50 px-2 py-0.5 text-xs font-medium text-denim-700">
                  {s.kind}
                </span>
              </div>
              <button
                type="button"
                onClick={() => onDelete(s.name)}
                className="shrink-0 text-xs text-neutral-400 hover:text-red-600"
                aria-label={`Delete ${s.name}`}
              >
                ✕
              </button>
            </div>
            <p className="line-clamp-2 text-sm text-neutral-600">{s.description}</p>
            <button
              type="button"
              onClick={() => startEdit(s)}
              className="mt-auto self-start text-sm font-medium text-denim-600 hover:text-denim-800"
            >
              Edit
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
