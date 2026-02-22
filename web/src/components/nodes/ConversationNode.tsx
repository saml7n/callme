import { Handle, Position, type NodeProps } from '@xyflow/react'

interface ConversationNodeData {
  label: string
  instructions: string
  examples?: Array<{ role: string; content: string }>
  max_iterations?: number
  isEntry?: boolean
  [key: string]: unknown
}

export default function ConversationNode({ data }: NodeProps) {
  const d = data as unknown as ConversationNodeData
  const isEntry = d.isEntry ?? false
  const maxIter = d.max_iterations ?? 10
  const instructions = d.instructions ?? ''
  const examples = d.examples ?? []

  // Truncate instructions for preview
  const preview =
    instructions.length > 120 ? instructions.slice(0, 120) + '…' : instructions

  return (
    <div
      className={`
        rounded-xl shadow-lg w-72 overflow-hidden
        ${isEntry
          ? 'ring-2 ring-indigo-500 ring-offset-2 ring-offset-gray-950'
          : 'ring-1 ring-gray-700'}
        bg-gray-900
      `}
    >
      {/* Header */}
      <div className="bg-blue-900/60 px-4 py-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-2.5 h-2.5 rounded-full bg-blue-400" />
          <span className="text-sm font-semibold text-blue-100">
            {d.label}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {isEntry && (
            <span className="text-[10px] bg-indigo-600 text-white px-1.5 py-0.5 rounded font-medium uppercase tracking-wide">
              Entry
            </span>
          )}
          <span className="text-[10px] bg-blue-800 text-blue-300 px-1.5 py-0.5 rounded">
            Conversation
          </span>
        </div>
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-2">
        <p className="text-xs text-gray-300 leading-relaxed">{preview}</p>

        {/* Stats */}
        <div className="flex items-center gap-3 text-[11px] text-gray-500 pt-1 border-t border-gray-800">
          <span>{examples.length} example{examples.length !== 1 ? 's' : ''}</span>
          <span>·</span>
          <span>max {maxIter} turns</span>
        </div>
      </div>

      {/* Handles */}
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !bg-gray-600 !border-2 !border-gray-800"
      />
      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-3 !h-3 !bg-indigo-500 !border-2 !border-gray-800"
      />
    </div>
  )
}
