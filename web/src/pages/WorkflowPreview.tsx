import { useCallback, useEffect, useState } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  MarkerType,
  Panel,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import ConversationNode from '../components/nodes/ConversationNode'
import DecisionNode from '../components/nodes/DecisionNode'
import ActionNode from '../components/nodes/ActionNode'

const API_BASE = 'http://localhost:3000'

const nodeTypes = {
  conversation: ConversationNode,
  decision: DecisionNode,
  action: ActionNode,
}

interface WorkflowData {
  id: string
  name: string
  version: number
  entry_node_id: string
  nodes: Array<{
    id: string
    type: string
    data: Record<string, unknown>
    position: { x: number; y: number }
  }>
  edges: Array<{
    id: string
    source: string
    target: string
    label: string
  }>
}

function workflowToFlow(wf: WorkflowData): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = wf.nodes.map((n) => ({
    id: n.id,
    type: n.type,
    position: n.position,
    data: {
      ...n.data,
      label: n.id,
      isEntry: n.id === wf.entry_node_id,
    },
    draggable: false,
    selectable: true,
    connectable: false,
  }))

  const edges: Edge[] = wf.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.label,
    type: 'smoothstep',
    animated: true,
    markerEnd: { type: MarkerType.ArrowClosed },
    style: { stroke: '#6366f1', strokeWidth: 2 },
    labelStyle: { fill: '#d1d5db', fontSize: 12, fontWeight: 500 },
    labelBgStyle: { fill: '#1e1b4b', fillOpacity: 0.9 },
    labelBgPadding: [6, 4] as [number, number],
    labelBgBorderRadius: 4,
  }))

  return { nodes, edges }
}

export default function WorkflowPreview() {
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [workflow, setWorkflow] = useState<WorkflowData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchWorkflow = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await fetch(`${API_BASE}/api/workflows/active`)
      if (!res.ok) {
        throw new Error(
          res.status === 404
            ? 'No active workflow found'
            : `Server error: ${res.status}`
        )
      }
      const data: WorkflowData = await res.json()
      setWorkflow(data)
      const { nodes: flowNodes, edges: flowEdges } = workflowToFlow(data)
      setNodes(flowNodes)
      setEdges(flowEdges)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load workflow')
    } finally {
      setLoading(false)
    }
  }, [setNodes, setEdges])

  useEffect(() => {
    fetchWorkflow()
  }, [fetchWorkflow])

  if (loading) {
    return (
      <div className="h-screen bg-gray-950 flex items-center justify-center">
        <p className="text-gray-400 text-lg">Loading workflow…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="h-screen bg-gray-950 flex items-center justify-center flex-col gap-4">
        <p className="text-red-400 text-lg">{error}</p>
        <button
          onClick={fetchWorkflow}
          className="px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-500 transition"
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="h-screen bg-gray-950 flex flex-col">
      {/* Header */}
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-white font-bold text-lg">CallMe</h1>
          <span className="text-gray-500">›</span>
          <span className="text-gray-300">{workflow?.name ?? 'Workflow'}</span>
          <span className="text-xs bg-gray-800 text-gray-400 px-2 py-0.5 rounded">
            v{workflow?.version}
          </span>
          <span className="text-xs bg-indigo-900 text-indigo-300 px-2 py-0.5 rounded">
            Read-only preview
          </span>
        </div>
        <div className="flex items-center gap-3 text-sm text-gray-400">
          <span>
            {workflow?.nodes.length} node{workflow?.nodes.length !== 1 ? 's' : ''}
          </span>
          <span>·</span>
          <span>
            {workflow?.edges.length} edge{workflow?.edges.length !== 1 ? 's' : ''}
          </span>
          <span>·</span>
          <span>Entry: <code className="text-indigo-400">{workflow?.entry_node_id}</code></span>
        </div>
      </header>

      {/* Canvas */}
      <div className="flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.3 }}
          proOptions={{ hideAttribution: true }}
          colorMode="dark"
        >
          <Background gap={20} size={1} color="#1e293b" />
          <Controls
            showInteractive={false}
            style={{ background: '#1e1b4b', borderColor: '#312e81', borderRadius: 8 }}
          />
          <MiniMap
            nodeColor={(n) => (n.data?.isEntry ? '#6366f1' : '#374151')}
            style={{ background: '#111827', borderColor: '#1f2937' }}
          />
          <Panel position="bottom-center">
            <p className="text-xs text-gray-600 mb-2">
              Workflow ID: {workflow?.id}
            </p>
          </Panel>
        </ReactFlow>
      </div>
    </div>
  )
}
