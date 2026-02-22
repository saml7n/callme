/** Right sidebar — edit the selected node's configuration. */

import { useCallback } from 'react'
import type { Node } from '@xyflow/react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'

interface ConfigPanelProps {
  node: Node
  entryNodeId: string
  onUpdateNode: (id: string, data: Record<string, unknown>) => void
  onSetEntry: (id: string) => void
  onDeleteNode: (id: string) => void
}

export default function ConfigPanel({
  node,
  entryNodeId,
  onUpdateNode,
  onSetEntry,
  onDeleteNode,
}: ConfigPanelProps) {
  const data = node.data as Record<string, unknown>
  const isEntry = node.id === entryNodeId

  const update = useCallback(
    (key: string, value: unknown) => {
      onUpdateNode(node.id, { ...data, [key]: value })
    },
    [node.id, data, onUpdateNode],
  )

  return (
    <div className="w-80 bg-gray-900 border-l border-gray-800 p-4 overflow-y-auto flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-white">Configure Node</h2>
        <span className="text-[11px] text-gray-500">{node.type}</span>
      </div>

      <Separator className="bg-gray-800" />

      {/* Node ID */}
      <div className="space-y-1.5">
        <Label className="text-gray-400">Node ID</Label>
        <Input
          value={(data.label as string) ?? node.id}
          onChange={(e) => update('label', e.target.value)}
          className="bg-gray-800 border-gray-700 text-white"
        />
      </div>

      {/* Entry node */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-400">
          {isEntry ? 'This is the entry node' : 'Not the entry node'}
        </span>
        {!isEntry && (
          <Button
            size="sm"
            variant="outline"
            className="text-xs"
            onClick={() => onSetEntry(node.id)}
          >
            Set as Entry
          </Button>
        )}
      </div>

      <Separator className="bg-gray-800" />

      {/* Type-specific config */}
      {node.type === 'conversation' && (
        <ConversationConfig data={data} update={update} />
      )}
      {node.type === 'decision' && (
        <DecisionConfig data={data} update={update} />
      )}
      {node.type === 'action' && (
        <ActionConfig data={data} update={update} />
      )}

      <Separator className="bg-gray-800" />

      {/* Delete */}
      <Button
        variant="destructive"
        size="sm"
        onClick={() => onDeleteNode(node.id)}
      >
        Delete Node
      </Button>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Per-type config forms                                               */
/* ------------------------------------------------------------------ */

function ConversationConfig({
  data,
  update,
}: {
  data: Record<string, unknown>
  update: (key: string, value: unknown) => void
}) {
  const instructions = (data.instructions as string) ?? ''
  const maxIterations = (data.max_iterations as number) ?? 10
  const examples = (data.examples as Array<{ role: string; content: string }>) ?? []

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label className="text-gray-400">Instructions</Label>
        <Textarea
          value={instructions}
          onChange={(e) => update('instructions', e.target.value)}
          className="bg-gray-800 border-gray-700 text-white min-h-[120px] text-xs"
          placeholder="System prompt for this conversation node..."
        />
      </div>

      <div className="space-y-1.5">
        <Label className="text-gray-400">Max iterations</Label>
        <Input
          type="number"
          min={1}
          value={maxIterations}
          onChange={(e) => update('max_iterations', parseInt(e.target.value) || 1)}
          className="bg-gray-800 border-gray-700 text-white w-24"
        />
      </div>

      {/* Examples */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label className="text-gray-400">Examples</Label>
          <Button
            size="sm"
            variant="outline"
            className="text-xs h-7"
            onClick={() =>
              update('examples', [
                ...examples,
                { role: 'user', content: '' },
                { role: 'assistant', content: '' },
              ])
            }
          >
            + Add pair
          </Button>
        </div>
        {examples.map((ex, i) => (
          <div key={i} className="flex gap-2 items-start">
            <span className="text-[10px] text-gray-500 w-12 pt-2 shrink-0">
              {ex.role === 'user' ? 'User' : 'AI'}
            </span>
            <Input
              value={ex.content}
              onChange={(e) => {
                const updated = [...examples]
                updated[i] = { ...ex, content: e.target.value }
                update('examples', updated)
              }}
              className="bg-gray-800 border-gray-700 text-white text-xs"
              placeholder={ex.role === 'user' ? 'Caller says...' : 'AI responds...'}
            />
            <Button
              size="sm"
              variant="ghost"
              className="text-gray-500 hover:text-red-400 h-8 w-8 p-0"
              onClick={() => {
                const updated = examples.filter((_, j) => j !== i)
                update('examples', updated)
              }}
            >
              ×
            </Button>
          </div>
        ))}
      </div>
    </div>
  )
}

function DecisionConfig({
  data,
  update,
}: {
  data: Record<string, unknown>
  update: (key: string, value: unknown) => void
}) {
  const instruction = (data.instruction as string) ?? ''

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label className="text-gray-400">Instruction</Label>
        <Textarea
          value={instruction}
          onChange={(e) => update('instruction', e.target.value)}
          className="bg-gray-800 border-gray-700 text-white min-h-[100px] text-xs"
          placeholder="Guide the router LLM on how to evaluate..."
        />
      </div>
      <p className="text-[11px] text-gray-500">
        Edge labels define the routing options. Edit them by clicking on each edge.
      </p>
    </div>
  )
}

function ActionConfig({
  data,
  update,
}: {
  data: Record<string, unknown>
  update: (key: string, value: unknown) => void
}) {
  const actionType = (data.action_type as string) ?? 'end_call'

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label className="text-gray-400">Action Type</Label>
        <Select value={actionType} onValueChange={(v) => update('action_type', v)}>
          <SelectTrigger className="bg-gray-800 border-gray-700 text-white">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="end_call">End Call</SelectItem>
            <SelectItem value="transfer">Transfer</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {actionType === 'end_call' && (
        <div className="space-y-1.5">
          <Label className="text-gray-400">Closing Message</Label>
          <Textarea
            value={(data.message as string) ?? ''}
            onChange={(e) => update('message', e.target.value)}
            className="bg-gray-800 border-gray-700 text-white min-h-[80px] text-xs"
            placeholder="Message to say before ending the call..."
          />
        </div>
      )}

      {actionType === 'transfer' && (
        <>
          <div className="space-y-1.5">
            <Label className="text-gray-400">Target Number</Label>
            <Input
              value={(data.target_number as string) ?? ''}
              onChange={(e) => update('target_number', e.target.value)}
              className="bg-gray-800 border-gray-700 text-white"
              placeholder="+44..."
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-gray-400">Announcement</Label>
            <Textarea
              value={(data.announcement as string) ?? ''}
              onChange={(e) => update('announcement', e.target.value)}
              className="bg-gray-800 border-gray-700 text-white min-h-[80px] text-xs"
              placeholder="Message to say before transferring..."
            />
          </div>
        </>
      )}
    </div>
  )
}
