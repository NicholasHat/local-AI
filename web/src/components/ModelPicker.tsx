import type { ModelInfo } from '../types'

export function ModelPicker({
  models,
  current,
  switching,
  onSelect,
  compact = false,
}: {
  models: ModelInfo[]
  current: string | null
  switching: boolean
  onSelect: (name: string) => void
  compact?: boolean
}) {
  if (compact) {
    return (
      <select
        value={current ?? ''}
        disabled={switching || models.length === 0}
        onChange={(e) => onSelect(e.target.value)}
        aria-label="Model"
        className="rounded-full border border-neutral-300 bg-white px-3 py-1.5 text-xs font-medium text-neutral-700 outline-none disabled:opacity-50"
      >
        {current === null && <option value="">No model</option>}
        {models.map((m) => (
          <option key={m.name} value={m.name} disabled={!m.tool_capable}>
            {m.name}
            {m.tool_capable ? '' : ' (no tool support)'}
          </option>
        ))}
      </select>
    )
  }

  return (
    <div>
      <h2 className="mb-2 text-xs font-semibold tracking-wide text-neutral-500 uppercase">
        Model
      </h2>
      <select
        value={current ?? ''}
        disabled={switching || models.length === 0}
        onChange={(e) => onSelect(e.target.value)}
        className="w-full rounded-lg border border-neutral-300 bg-white px-2 py-2 text-sm text-neutral-800 disabled:opacity-50"
      >
        {current === null && <option value="">No model selected</option>}
        {models.map((m) => (
          <option key={m.name} value={m.name} disabled={!m.tool_capable}>
            {m.name}
            {m.tool_capable ? '' : ' (no tool support)'}
          </option>
        ))}
      </select>
    </div>
  )
}
