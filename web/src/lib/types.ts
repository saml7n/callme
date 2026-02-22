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

// ---------------------------------------------------------------------------
// Call types
// ---------------------------------------------------------------------------

export type CallStatus = 'completed' | 'transferred' | 'error' | 'in_progress'

export interface CallListItem {
  id: string
  call_sid: string
  from_number: string
  to_number: string
  workflow_id: string | null
  workflow_name: string | null
  started_at: string
  ended_at: string | null
  duration_seconds: number | null
  status: CallStatus
}

export interface CallEventItem {
  id: string
  timestamp: string
  event_type: 'transcript' | 'llm_response' | 'node_transition' | 'summary_generated' | 'action_executed' | 'error'
  data_json: Record<string, unknown>
}

export interface CallDetail {
  id: string
  call_sid: string
  from_number: string
  to_number: string
  workflow_id: string | null
  workflow_name: string | null
  started_at: string
  ended_at: string | null
  duration_seconds: number | null
  status: CallStatus
  events: CallEventItem[]
}
