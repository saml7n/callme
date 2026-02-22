import { Handle, Position, type NodeProps } from '@xyflow/react'

export interface ActionNodeData {
  label: string
  action_type: string
  message?: string
  announcement?: string
  target_number?: string
  isEntry?: boolean
  [key: string]: unknown
}

const ACTION_LABELS: Record<string, string> = {
  end_call: 'End Call',
  transfer: 'Transfer',
}

const ACTION_ICONS: Record<string, string> = {
  end_call: '📞',
  transfer: '↗️',
}

export default function ActionNode({ data, selected }: NodeProps) {
  const d = data as unknown as ActionNodeData
  const isEntry = d.isEntry ?? false
  const actionType = d.action_type ?? 'end_call'
  const actionLabel = ACTION_LABELS[actionType] ?? actionType
  const icon = ACTION_ICONS[actionType] ?? '⚡'

  const previewText =
    actionType === 'transfer'
      ? d.announcement ?? ''
      : d.message ?? ''

  const preview =
    previewText.length > 100 ? previewText.slice(0, 100) + '…' : previewText

  return (
    <div
      className={`
        rounded-xl shadow-lg w-64 overflow-hidden bg-gray-900
        ${selected
          ? 'ring-2 ring-red-400 ring-offset-2 ring-offset-gray-950'
          : isEntry
            ? 'ring-2 ring-indigo-500 ring-offset-2 ring-offset-gray-950'
            : 'ring-1 ring-gray-700'}
      `}
    >
      {/* Header */}
      <div className="bg-red-900/60 px-4 py-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm">{icon}</span>
          <span className="text-sm font-semibold text-red-100">
            {d.label}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {isEntry && (
            <span className="text-[10px] bg-indigo-600 text-white px-1.5 py-0.5 rounded font-medium uppercase tracking-wide">
              Start
            </span>
          )}
          <span className="text-[10px] bg-red-800 text-red-300 px-1.5 py-0.5 rounded">
            {actionLabel}
          </span>
        </div>
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-2">
        <p className="text-xs text-gray-300 leading-relaxed">
          {preview || <span className="italic text-gray-500">No message set</span>}
        </p>

        {actionType === 'transfer' && d.target_number && (
          <div className="flex items-center gap-1 text-[11px] text-gray-500 pt-1 border-t border-gray-800">
            <span>📱</span>
            <span className="font-mono">{d.target_number}</span>
          </div>
        )}

        {actionType === 'end_call' && (
          <p className="text-[11px] text-gray-500 italic pt-1 border-t border-gray-800">
            Terminates the call
          </p>
        )}
      </div>

      {/* Handles — action nodes only have a target (no source, they're terminal) */}
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !bg-gray-600 !border-2 !border-gray-800"
      />
    </div>
  )
}
