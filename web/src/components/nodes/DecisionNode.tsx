import { Handle, Position, type NodeProps } from '@xyflow/react'

interface DecisionNodeData {
  label: string
  instruction: string
  isEntry?: boolean
  [key: string]: unknown
}

export default function DecisionNode({ data }: NodeProps) {
  const d = data as unknown as DecisionNodeData
  const isEntry = d.isEntry ?? false
  const instruction = d.instruction ?? ''

  const preview =
    instruction.length > 100 ? instruction.slice(0, 100) + '…' : instruction

  return (
    <div
      className={`
        rounded-xl shadow-lg w-64 overflow-hidden
        ${isEntry
          ? 'ring-2 ring-indigo-500 ring-offset-2 ring-offset-gray-950'
          : 'ring-1 ring-gray-700'}
        bg-gray-900
      `}
    >
      {/* Header */}
      <div className="bg-yellow-900/60 px-4 py-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-0 h-0 border-l-[5px] border-l-transparent border-r-[5px] border-r-transparent border-b-[8px] border-b-yellow-400" />
          <span className="text-sm font-semibold text-yellow-100">
            {d.label}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {isEntry && (
            <span className="text-[10px] bg-indigo-600 text-white px-1.5 py-0.5 rounded font-medium uppercase tracking-wide">
              Entry
            </span>
          )}
          <span className="text-[10px] bg-yellow-800 text-yellow-300 px-1.5 py-0.5 rounded">
            Decision
          </span>
        </div>
      </div>

      {/* Body */}
      <div className="px-4 py-3">
        <p className="text-xs text-gray-300 leading-relaxed">{preview}</p>
        <p className="text-[11px] text-gray-500 mt-2 italic">No caller interaction</p>
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
        className="!w-3 !h-3 !bg-yellow-500 !border-2 !border-gray-800"
      />
    </div>
  )
}
