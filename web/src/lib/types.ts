/** Shared types matching the server workflow schema. */

export interface Position {
  x: number
  y: number
}

export interface WorkflowNode {
  id: string
  type: 'conversation' | 'decision' | 'action'
  data: Record<string, unknown>
  position: Position
}

export interface WorkflowEdge {
  id: string
  source: string
  target: string
  label: string
}

export interface WorkflowGraph {
  id: string
  name: string
  version: number
  entry_node_id: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
}

export interface WorkflowDetail {
  id: string
  name: string
  version: number
  graph_json: WorkflowGraph
  is_active: boolean
  phone_number: string | null
  created_at: string
  updated_at: string
}

export interface WorkflowListItem {
  id: string
  name: string
  version: number
  is_active: boolean
  phone_number: string | null
  updated_at: string
}
