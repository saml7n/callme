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
// Integration types
// ---------------------------------------------------------------------------

export type IntegrationType = 'google_calendar' | 'webhook'

export interface IntegrationItem {
  id: string
  type: IntegrationType
  name: string
  config_redacted: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface IntegrationTestResult {
  success: boolean
  detail: string
}

export interface GoogleOAuthStatus {
  configured: boolean
}

export interface CalendarEntry {
  id: string
  summary: string
  primary: boolean
}

/** Actions available per integration type. */
export const INTEGRATION_ACTIONS: Record<IntegrationType, { value: string; label: string }[]> = {
  google_calendar: [
    { value: 'check_availability', label: 'Check Availability' },
    { value: 'book_appointment', label: 'Book Appointment' },
  ],
  webhook: [
    { value: 'call_webhook', label: 'Call Webhook' },
  ],
}

export const INTEGRATION_TYPE_LABELS: Record<IntegrationType, string> = {
  google_calendar: 'Google Calendar',
  webhook: 'Webhook',
}

// ---------------------------------------------------------------------------
// Phone number types
// ---------------------------------------------------------------------------

export interface PhoneNumberItem {
  id: string
  number: string
  label: string
  workflow_id: string | null
  workflow_name: string | null
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

// ---------------------------------------------------------------------------
// Settings types (Story 17)
// ---------------------------------------------------------------------------

export interface SettingsResponse {
  settings: Record<string, string>
  configured: boolean
}

export interface ValidateResults {
  results: Record<string, string>
}

export interface TemplateItem {
  id: string
  name: string
  description: string
  icon: string
  graph: WorkflowGraph
}

// ---------------------------------------------------------------------------
// Live call types (Story 18)
// ---------------------------------------------------------------------------

export interface LiveCallEvent {
  type: 'call_started' | 'transcript' | 'node_transition' | 'call_ended' | 'transfer_started' | 'snapshot'
  call_id?: string
  caller_number?: string
  workflow_name?: string
  role?: 'caller' | 'ai'
  text?: string
  from_node?: string
  to_node?: string
  duration?: number
  target_number?: string
  timestamp?: number
  calls?: ActiveCall[]
}

export interface ActiveCall {
  call_id: string
  call_sid: string
  caller_number: string
  workflow_name: string
  started_at: number
}

export interface TranscriptMessage {
  role: 'caller' | 'ai'
  text: string
  timestamp: number
}

export interface TransferResult {
  ok: boolean
  call_id: string
  transferred_to: string
}
