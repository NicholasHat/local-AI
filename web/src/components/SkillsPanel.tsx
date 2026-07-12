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

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-xs font-semibold tracking-wide text-neutral-500 uppercase">
          Skills
        </h2>
        {editingName === null && (
          <button
            type="button"
            onClick={startCreate}
            className="text-xs font-medium text-neutral-600 hover:text-neutral-900"
          >
            + New
          </button>
        )}
      </div>

      {editingName === null && (
        <ul className="flex flex-col gap-1">
          {skills.length === 0 && (
            <li className="text-sm text-neutral-400">No skills yet.</li>
          )}
          {skills.map((s) => (
            <li
              key={s.name}
              className="rounded-md px-2 py-1 text-sm text-neutral-700 hover:bg-neutral-100"
            >
              <div className="flex items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={() => startEdit(s)}
                  className="min-w-0 flex-1 truncate text-left"
                  title={s.description}
                >
                  {s.name}
                  <span className="ml-1 text-xs text-neutral-400">
                    ({s.kind})
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => onDelete(s.name)}
                  className="shrink-0 text-xs text-neutral-400 hover:text-red-600"
                  aria-label={`Delete ${s.name}`}
                >
                  ✕
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {editingName !== null && (
        <div className="flex flex-col gap-2 rounded-lg border border-neutral-200 bg-white p-3">
          <input
            value={form.name}
            disabled={editingName !== 'new'}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="slug-name"
            className="rounded-md border border-neutral-300 px-2 py-1 text-sm disabled:opacity-50"
          />
          <input
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="Description"
            className="rounded-md border border-neutral-300 px-2 py-1 text-sm"
          />
          <select
            value={form.kind}
            onChange={(e) =>
              setForm({ ...form, kind: e.target.value as 'instruction' | 'code' })
            }
            className="rounded-md border border-neutral-300 px-2 py-1 text-sm"
          >
            <option value="instruction">Instruction (prompt.md)</option>
            <option value="code">Code (run.py)</option>
          </select>
          <textarea
            value={form.parametersText}
            onChange={(e) => setForm({ ...form, parametersText: e.target.value })}
            placeholder='Parameters JSON, e.g. {"text": {"type": "string"}}'
            rows={3}
            className="rounded-md border border-neutral-300 px-2 py-1 font-mono text-xs"
          />
          <input
            value={form.requiredText}
            onChange={(e) => setForm({ ...form, requiredText: e.target.value })}
            placeholder="Required args, comma-separated"
            className="rounded-md border border-neutral-300 px-2 py-1 text-sm"
          />
          <textarea
            value={form.body}
            onChange={(e) => setForm({ ...form, body: e.target.value })}
            placeholder={
              form.kind === 'instruction'
                ? 'Instruction template, use {arg_name} placeholders'
                : 'def run(**args) -> str: ...'
            }
            rows={6}
            className="rounded-md border border-neutral-300 px-2 py-1 font-mono text-xs"
          />

          {formError && <p className="text-xs text-red-600">{formError}</p>}

          <div className="flex gap-2">
            <button
              type="button"
              onClick={submit}
              disabled={busy}
              className="flex-1 rounded-md bg-neutral-900 px-2 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            >
              Save
            </button>
            <button
              type="button"
              onClick={cancel}
              className="rounded-md border border-neutral-300 px-2 py-1.5 text-sm"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
