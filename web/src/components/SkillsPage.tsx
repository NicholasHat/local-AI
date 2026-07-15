import type { SkillInfo, SkillWriteRequest } from '../types'
import { SkillsPanel } from './SkillsPanel'

export function SkillsPage({
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
  return (
    <div className="flex-1 overflow-y-auto px-6 py-8">
      <div className="mx-auto flex max-w-4xl flex-col gap-1">
        <h1 className="text-xl font-semibold text-neutral-900">Skills</h1>
        <p className="mb-4 text-sm text-neutral-500">
          Reusable capabilities the model can call. Instruction skills are a prompt
          template; code skills run a Python function.
        </p>
        <SkillsPanel
          skills={skills}
          busy={busy}
          onCreate={onCreate}
          onUpdate={onUpdate}
          onDelete={onDelete}
        />
      </div>
    </div>
  )
}
