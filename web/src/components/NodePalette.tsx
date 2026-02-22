/** Left sidebar palette — drag node types onto the canvas. */

import type { DragEvent } from 'react'

const NODE_TYPES = [
  {
    type: 'conversation',
    label: 'Conversation',
    icon: '💬',
    color: 'bg-blue-900/60 border-blue-700',
    description: 'Talk to the caller',
  },
  {
    type: 'decision',
    label: 'Decision',
    icon: '🔀',
    color: 'bg-yellow-900/60 border-yellow-700',
    description: 'Route based on context',
  },
  {
    type: 'action',
    label: 'Action',
    icon: '⚡',
    color: 'bg-red-900/60 border-red-700',
    description: 'End call or transfer',
  },
] as const

function onDragStart(event: DragEvent, nodeType: string) {
  event.dataTransfer.setData('application/callme-node-type', nodeType)
  event.dataTransfer.effectAllowed = 'move'
}

export default function NodePalette() {
  return (
    <div className="w-56 bg-gray-900 border-r border-gray-800 p-4 flex flex-col gap-2">
      <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
        Node Types
      </h2>
      {NODE_TYPES.map((nt) => (
        <div
          key={nt.type}
          draggable
          onDragStart={(e) => onDragStart(e, nt.type)}
          className={`
            flex items-center gap-3 px-3 py-2.5 rounded-lg border cursor-grab
            active:cursor-grabbing hover:brightness-125 transition
            ${nt.color}
          `}
        >
          <span className="text-lg">{nt.icon}</span>
          <div>
            <div className="text-sm font-medium text-gray-100">{nt.label}</div>
            <div className="text-[11px] text-gray-400">{nt.description}</div>
          </div>
        </div>
      ))}
    </div>
  )
}
