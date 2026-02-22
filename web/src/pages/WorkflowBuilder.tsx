/** Workflow builder page — drag-and-drop visual editor with React Flow. */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type Connection,
  type ReactFlowInstance,
  MarkerType,
  Panel,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import ConversationNode from '@/components/nodes/ConversationNode'
import DecisionNode from '@/components/nodes/DecisionNode'
import ActionNode from '@/components/nodes/ActionNode'
import NodePalette from '@/components/NodePalette'
import ConfigPanel from '@/components/ConfigPanel'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import type { WorkflowGraph, WorkflowDetail, PhoneNumberItem } from '@/lib/types'

/* ------------------------------------------------------------------ */
/* Constants                                                           */
/* ------------------------------------------------------------------ */

const nodeTypes = {
  conversation: ConversationNode,
  decision: DecisionNode,
  action: ActionNode,
}

const DEFAULT_EDGE_STYLE = {
  type: 'smoothstep' as const,
  animated: true,
  markerEnd: { type: MarkerType.ArrowClosed },
  style: { stroke: '#6366f1', strokeWidth: 2 },
  labelStyle: { fill: '#d1d5db', fontSize: 12, fontWeight: 500 },
  labelBgStyle: { fill: '#1e1b4b', fillOpacity: 0.9 },
  labelBgPadding: [6, 4] as [number, number],
  labelBgBorderRadius: 4,
}

/** Default data for each node type when dropped from the palette. */
const DEFAULT_NODE_DATA: Record<string, Record<string, unknown>> = {
  conversation: { instructions: '', examples: [], max_iterations: 10 },
  decision: { instruction: '' },
  action: { action_type: 'end_call', message: '' },
}

let nodeIdCounter = 0
function nextNodeId(type: string) {
  nodeIdCounter += 1
  return `${type}_${nodeIdCounter}`
}

let edgeIdCounter = 0
function nextEdgeId() {
  edgeIdCounter += 1
  return `e_${edgeIdCounter}`
}

/* ------------------------------------------------------------------ */
/* Validation                                                          */
/* ------------------------------------------------------------------ */

interface ValidationWarning {
  type: 'error' | 'warning'
  message: string
}

function validateGraph(
  nodes: Node[],
  edges: Edge[],
  entryNodeId: string,
): ValidationWarning[] {
  const warnings: ValidationWarning[] = []

  if (!entryNodeId) {
    warnings.push({ type: 'error', message: 'No entry node set' })
  } else if (!nodes.find((n) => n.id === entryNodeId)) {
    warnings.push({ type: 'error', message: 'Entry node does not exist on canvas' })
  }

  // Orphan nodes: no edges in or out
  const connectedIds = new Set<string>()
  for (const e of edges) {
    connectedIds.add(e.source)
    connectedIds.add(e.target)
  }
  for (const n of nodes) {
    if (!connectedIds.has(n.id) && nodes.length > 1) {
      warnings.push({ type: 'warning', message: `Node "${(n.data as Record<string, unknown>).label ?? n.id}" has no connections` })
    }
  }

  // Duplicate IDs
  const ids = nodes.map((n) => (n.data as Record<string, unknown>).label ?? n.id)
  const seen = new Set<unknown>()
  for (const id of ids) {
    if (seen.has(id)) {
      warnings.push({ type: 'error', message: `Duplicate node ID: "${id}"` })
    }
    seen.add(id)
  }

  return warnings
}

/* ------------------------------------------------------------------ */
/* Serialisation                                                       */
/* ------------------------------------------------------------------ */

function flowToWorkflowGraph(
  nodes: Node[],
  edges: Edge[],
  entryNodeId: string,
  workflowId: string,
  workflowName: string,
  version: number,
): WorkflowGraph {
  return {
    id: workflowId,
    name: workflowName,
    version,
    entry_node_id: entryNodeId,
    nodes: nodes.map((n) => {
      const { label: _label, isEntry: _isEntry, ...rest } = n.data as Record<string, unknown>
      return {
        id: (n.data as Record<string, unknown>).label as string ?? n.id,
        type: n.type as 'conversation' | 'decision' | 'action',
        data: rest,
        position: n.position,
      }
    }),
    edges: edges.map((e) => ({
      id: e.id,
      source: (nodes.find((n) => n.id === e.source)?.data as Record<string, unknown>)?.label as string ?? e.source,
      target: (nodes.find((n) => n.id === e.target)?.data as Record<string, unknown>)?.label as string ?? e.target,
      label: (e.label as string) ?? '',
    })),
  }
}

function workflowGraphToFlow(
  graph: WorkflowGraph,
): { nodes: Node[]; edges: Edge[]; entryNodeId: string } {
  // Reset counters
  nodeIdCounter = graph.nodes.length
  edgeIdCounter = graph.edges.length

  const nodes: Node[] = graph.nodes.map((n) => ({
    id: n.id, // Use the workflow node ID as the React Flow ID
    type: n.type,
    position: n.position,
    data: {
      ...n.data,
      label: n.id,
      isEntry: n.id === graph.entry_node_id,
    },
  }))

  const edges: Edge[] = graph.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.label,
    ...DEFAULT_EDGE_STYLE,
  }))

  return { nodes, edges, entryNodeId: graph.entry_node_id }
}

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

export default function WorkflowBuilder() {
  const { id: workflowId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const isNew = !workflowId

  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [entryNodeId, setEntryNodeId] = useState('')
  const [workflowName, setWorkflowName] = useState('Untitled Workflow')
  const [version, setVersion] = useState(1)
  const [savedId, setSavedId] = useState<string | null>(workflowId ?? null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  const [publishOpen, setPublishOpen] = useState(false)
  const [publishPhoneId, setPublishPhoneId] = useState('')
  const [phoneNumbers, setPhoneNumbers] = useState<PhoneNumberItem[]>([])
  const [confirmDeactivate, setConfirmDeactivate] = useState<string | null>(null)
  const reactFlowWrapper = useRef<HTMLDivElement>(null)
  const [rfInstance, setRfInstance] = useState<ReactFlowInstance | null>(null)

  // Selected node for config panel
  const selectedNode = useMemo(
    () => nodes.find((n) => n.selected) ?? null,
    [nodes],
  )

  // Validation warnings
  const warnings = useMemo(
    () => validateGraph(nodes, edges, entryNodeId),
    [nodes, edges, entryNodeId],
  )

  /* ---- Load existing workflow ---- */
  useEffect(() => {
    if (!workflowId) return
    setLoading(true)
    api.workflows
      .get(workflowId)
      .then((wf: WorkflowDetail) => {
        const { nodes: flowNodes, edges: flowEdges, entryNodeId: entry } =
          workflowGraphToFlow(wf.graph_json)
        setNodes(flowNodes)
        setEdges(flowEdges)
        setEntryNodeId(entry)
        setWorkflowName(wf.name)
        setVersion(wf.version)
        setSavedId(wf.id)
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [workflowId, setNodes, setEdges])

  /* ---- Edge connection ---- */
  const onConnect = useCallback(
    (connection: Connection) => {
      const edge: Edge = {
        ...connection,
        id: nextEdgeId(),
        label: 'condition',
        ...DEFAULT_EDGE_STYLE,
      } as Edge
      setEdges((eds) => addEdge(edge, eds))
    },
    [setEdges],
  )

  /* ---- Drop node from palette ---- */
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
  }, [])

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault()
      const nodeType = event.dataTransfer.getData('application/callme-node-type')
      if (!nodeType || !rfInstance) return

      const position = rfInstance.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      })

      const id = nextNodeId(nodeType)
      const newNode: Node = {
        id,
        type: nodeType,
        position,
        data: {
          ...DEFAULT_NODE_DATA[nodeType],
          label: id,
          isEntry: nodes.length === 0,
        },
      }

      setNodes((nds) => [...nds, newNode])

      // Auto-set entry if this is the first node
      if (nodes.length === 0) {
        setEntryNodeId(id)
      }
    },
    [rfInstance, nodes.length, setNodes],
  )

  /* ---- Node data update (from config panel) ---- */
  const onUpdateNode = useCallback(
    (nodeId: string, newData: Record<string, unknown>) => {
      setNodes((nds) =>
        nds.map((n) =>
          n.id === nodeId ? { ...n, data: { ...newData, isEntry: n.id === entryNodeId } } : n,
        ),
      )
    },
    [setNodes, entryNodeId],
  )

  /* ---- Set entry node ---- */
  const onSetEntry = useCallback(
    (nodeId: string) => {
      setEntryNodeId(nodeId)
      setNodes((nds) =>
        nds.map((n) => ({
          ...n,
          data: { ...(n.data as Record<string, unknown>), isEntry: n.id === nodeId },
        })),
      )
    },
    [setNodes],
  )

  /* ---- Delete node ---- */
  const onDeleteNode = useCallback(
    (nodeId: string) => {
      setNodes((nds) => nds.filter((n) => n.id !== nodeId))
      setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId))
      if (entryNodeId === nodeId) setEntryNodeId('')
    },
    [setNodes, setEdges, entryNodeId],
  )

  /* ---- Edge label editing (double-click) ---- */
  const onEdgeDoubleClick = useCallback(
    (_event: React.MouseEvent, edge: Edge) => {
      const newLabel = prompt('Edge label (condition):', (edge.label as string) ?? '')
      if (newLabel === null) return
      setEdges((eds) =>
        eds.map((e) => (e.id === edge.id ? { ...e, label: newLabel } : e)),
      )
    },
    [setEdges],
  )

  /* ---- Save ---- */
  const handleSave = useCallback(async () => {
    const graph = flowToWorkflowGraph(
      nodes,
      edges,
      entryNodeId,
      savedId ?? `wf_${Date.now()}`,
      workflowName,
      version,
    )

    setSaving(true)
    setError(null)
    setSuccessMsg(null)

    try {
      if (savedId) {
        const updated = await api.workflows.update(savedId, {
          name: workflowName,
          graph_json: graph,
        })
        setVersion(updated.version)
        setSuccessMsg('Saved!')
      } else {
        const created = await api.workflows.create(workflowName, graph)
        setSavedId(created.id)
        setVersion(created.version)
        navigate(`/workflows/${created.id}/edit`, { replace: true })
        setSuccessMsg('Created!')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save')
    } finally {
      setSaving(false)
      setTimeout(() => setSuccessMsg(null), 2000)
    }
  }, [nodes, edges, entryNodeId, savedId, workflowName, version, navigate])

  /* ---- Publish ---- */
  const handlePublishOpen = useCallback(async () => {
    try {
      const nums = await api.phoneNumbers.list()
      setPhoneNumbers(nums)
    } catch {
      // If we can't load numbers, still open the dialog (will show empty state)
      setPhoneNumbers([])
    }
    setPublishOpen(true)
  }, [])

  const handlePublish = useCallback(async () => {
    if (!savedId || !publishPhoneId) return

    // Check if selected number is assigned to a different workflow
    const selected = phoneNumbers.find((p) => p.id === publishPhoneId)
    if (
      selected?.workflow_id &&
      selected.workflow_id !== savedId &&
      !confirmDeactivate
    ) {
      setConfirmDeactivate(selected.workflow_name ?? 'another workflow')
      return
    }

    setSaving(true)
    setError(null)
    setConfirmDeactivate(null)
    try {
      // Save first
      const graph = flowToWorkflowGraph(
        nodes,
        edges,
        entryNodeId,
        savedId,
        workflowName,
        version,
      )
      await api.workflows.update(savedId, { name: workflowName, graph_json: graph })
      await api.workflows.publish(savedId, publishPhoneId, version)
      setSuccessMsg('Published!')
      setPublishOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to publish')
    } finally {
      setSaving(false)
      setTimeout(() => setSuccessMsg(null), 2000)
    }
  }, [savedId, nodes, edges, entryNodeId, workflowName, version, publishPhoneId, phoneNumbers, confirmDeactivate])

  /* ---- Render ---- */

  if (loading) {
    return (
      <div className="h-screen bg-gray-950 flex items-center justify-center">
        <p className="text-gray-400 text-lg">Loading workflow…</p>
      </div>
    )
  }

  return (
    <div className="h-screen bg-gray-950 flex flex-col">
      {/* Header */}
      <header className="bg-gray-900 border-b border-gray-800 px-4 py-2 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <Link to="/" className="text-white font-bold text-lg hover:text-indigo-400 transition">
            CallMe
          </Link>
          <span className="text-gray-600">›</span>
          <Input
            value={workflowName}
            onChange={(e) => setWorkflowName(e.target.value)}
            className="bg-transparent border-none text-gray-200 text-sm font-medium w-56 px-1 focus-visible:ring-1 focus-visible:ring-indigo-500"
          />
          {savedId && (
            <Badge variant="outline" className="text-gray-500 text-[10px]">
              v{version}
            </Badge>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* Warnings */}
          {warnings.length > 0 && (
            <Badge variant="destructive" className="text-[10px]">
              {warnings.length} issue{warnings.length !== 1 ? 's' : ''}
            </Badge>
          )}

          {successMsg && (
            <span className="text-green-400 text-xs">{successMsg}</span>
          )}
          {error && (
            <span className="text-red-400 text-xs max-w-48 truncate">{error}</span>
          )}

          <Button
            size="sm"
            variant="secondary"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? 'Saving…' : 'Save'}
          </Button>
          <Button
            size="sm"
            className="bg-indigo-600 text-white hover:bg-indigo-500 disabled:bg-indigo-600/30 disabled:text-indigo-300/50"
            onClick={handlePublishOpen}
            disabled={!savedId || saving}
          >
            Publish
          </Button>
        </div>
      </header>

      {/* Body: palette + canvas + config */}
      <div className="flex-1 flex overflow-hidden">
        <NodePalette />

        {/* Canvas */}
        <div className="flex-1" ref={reactFlowWrapper}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onInit={setRfInstance}
            onDrop={onDrop}
            onDragOver={onDragOver}
            onEdgeDoubleClick={onEdgeDoubleClick}
            nodeTypes={nodeTypes}
            fitView={!!workflowId}
            fitViewOptions={{ padding: 0.3 }}
            proOptions={{ hideAttribution: true }}
            colorMode="dark"
            deleteKeyCode={['Backspace', 'Delete']}
            selectionKeyCode={null}
          >
            <Background gap={20} size={1} color="#1e293b" />
            <Controls
              showInteractive={false}
              style={{
                background: '#1e1b4b',
                borderColor: '#312e81',
                borderRadius: 8,
              }}
            />
            <MiniMap
              nodeColor={(n) =>
                n.data?.isEntry
                  ? '#6366f1'
                  : n.type === 'conversation'
                    ? '#1e3a5f'
                    : n.type === 'decision'
                      ? '#5c4813'
                      : '#5c1313'
              }
              style={{ background: '#111827', borderColor: '#1f2937' }}
            />
            {/* Validation warnings panel */}
            {warnings.length > 0 && (
              <Panel position="bottom-left">
                <div className="bg-gray-900/95 border border-gray-700 rounded-lg p-3 max-w-xs space-y-1">
                  {warnings.map((w, i) => (
                    <div
                      key={i}
                      className={`text-xs ${w.type === 'error' ? 'text-red-400' : 'text-yellow-400'}`}
                    >
                      {w.type === 'error' ? '⛔' : '⚠️'} {w.message}
                    </div>
                  ))}
                </div>
              </Panel>
            )}
          </ReactFlow>
        </div>

        {/* Config panel */}
        {selectedNode && (
          <ConfigPanel
            node={selectedNode}
            entryNodeId={entryNodeId}
            onUpdateNode={onUpdateNode}
            onSetEntry={onSetEntry}
            onDeleteNode={onDeleteNode}
          />
        )}
      </div>

      {/* Publish dialog */}
      <Dialog open={publishOpen} onOpenChange={(open) => { setPublishOpen(open); setConfirmDeactivate(null) }}>
        <DialogContent className="bg-gray-900 border-gray-700">
          <DialogHeader>
            <DialogTitle className="text-white">Publish Workflow</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <Label className="text-gray-400">Select a phone number</Label>
            {phoneNumbers.length === 0 ? (
              <div className="text-sm text-gray-500">
                No phone numbers registered.{' '}
                <Link to="/settings/phone-numbers" className="text-indigo-400 hover:text-indigo-300">
                  Add one in Settings
                </Link>
              </div>
            ) : (
              <select
                value={publishPhoneId}
                onChange={(e) => { setPublishPhoneId(e.target.value); setConfirmDeactivate(null) }}
                className="w-full rounded-md bg-gray-800 border border-gray-700 text-white px-3 py-2 text-sm focus:ring-1 focus:ring-indigo-500 focus:outline-none"
              >
                <option value="">Choose a number…</option>
                {phoneNumbers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.number}{p.label ? ` — ${p.label}` : ''}
                    {p.workflow_id && p.workflow_id !== savedId ? ` (in use: ${p.workflow_name ?? 'Unknown'})` : ''}
                    {p.workflow_id && p.workflow_id === savedId ? ' (current)' : ''}
                  </option>
                ))}
              </select>
            )}
            {confirmDeactivate && (
              <p className="text-yellow-400 text-sm">
                This will deactivate <strong>{confirmDeactivate}</strong>. Click Publish again to confirm.
              </p>
            )}
            {!confirmDeactivate && (
              <p className="text-xs text-gray-500">
                The selected number will be assigned to this workflow.
              </p>
            )}
            <Link
              to="/settings/phone-numbers"
              className="text-xs text-indigo-400 hover:text-indigo-300 inline-block"
            >
              Manage phone numbers →
            </Link>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => { setPublishOpen(false); setConfirmDeactivate(null) }}>
              Cancel
            </Button>
            <Button
              className="bg-indigo-600 text-white hover:bg-indigo-500"
              onClick={handlePublish}
              disabled={saving || !publishPhoneId}
            >
              {saving ? 'Publishing…' : confirmDeactivate ? 'Confirm & Publish' : 'Publish'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
