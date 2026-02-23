/** Call detail page — full call metadata, chat-style transcript, and event timeline. */

import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { api } from '@/lib/api'
import type { CallDetail as CallDetailType, CallEventItem } from '@/lib/types'
import { formatDuration, formatDateTime } from '@/lib/phone'

const statusStyles: Record<string, string> = {
  completed: 'bg-green-900 text-green-300',
  transferred: 'bg-blue-900 text-blue-300',
  error: 'bg-red-900 text-red-300',
  in_progress: 'bg-yellow-900 text-yellow-300',
}

/** Format just the time portion for event timestamps. */
function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

// ---------------------------------------------------------------------------
// Event rendering
// ---------------------------------------------------------------------------

function TranscriptBubble({ event, side }: { event: CallEventItem; side: 'caller' | 'ai' }) {
  const data = event.data_json ?? {}
  const text = (data.text as string)
    ?? (data.transcript as string)
    ?? (data.response as string)
    ?? JSON.stringify(data)
  const isAi = side === 'ai'
  return (
    <div className={`flex ${isAi ? 'justify-end' : 'justify-start'} mb-2`}>
      <div
        className={`max-w-[75%] rounded-lg px-4 py-2 text-sm ${
          isAi
            ? 'bg-indigo-900/50 text-indigo-100'
            : 'bg-gray-800 text-gray-200'
        }`}
      >
        <p>{text}</p>
        <span className="block text-[10px] mt-1 opacity-50">{formatTime(event.timestamp)}</span>
      </div>
    </div>
  )
}

function NodeTransitionMarker({ event }: { event: CallEventItem }) {
  const nodeId = (event.data_json?.node_id as string) ?? 'unknown'
  return (
    <div className="flex justify-center my-3">
      <span className="text-[10px] text-gray-500 bg-gray-900 border border-gray-800 rounded-full px-3 py-1">
        → Node: <span className="text-gray-400 font-mono">{nodeId}</span>
        <span className="ml-2 opacity-50">{formatTime(event.timestamp)}</span>
      </span>
    </div>
  )
}

function ActionEvent({ event }: { event: CallEventItem }) {
  const actionType = (event.data_json?.action_type as string) ?? 'action'
  return (
    <div className="flex justify-center my-3">
      <span className="text-[10px] text-blue-400 bg-blue-950 border border-blue-900 rounded-full px-3 py-1">
        ⚡ {actionType}
        <span className="ml-2 opacity-50">{formatTime(event.timestamp)}</span>
      </span>
    </div>
  )
}

function ErrorEvent({ event }: { event: CallEventItem }) {
  const message = (event.data_json?.message as string) ?? JSON.stringify(event.data_json)
  return (
    <div className="flex justify-center my-3">
      <span className="text-xs text-red-400 bg-red-950 border border-red-900 rounded px-3 py-1">
        ❌ {message}
        <span className="ml-2 opacity-50">{formatTime(event.timestamp)}</span>
      </span>
    </div>
  )
}

function SummaryEvent({ event }: { event: CallEventItem }) {
  const summary = (event.data_json?.summary as string) ?? JSON.stringify(event.data_json)
  return (
    <div className="my-4 bg-gray-900 border border-gray-800 rounded-lg p-4">
      <h4 className="text-xs font-semibold text-gray-400 mb-2 uppercase tracking-wide">
        Call Summary
      </h4>
      <p className="text-sm text-gray-300 whitespace-pre-wrap">{summary}</p>
      <span className="block text-[10px] mt-2 text-gray-600">{formatTime(event.timestamp)}</span>
    </div>
  )
}

function EventRenderer({ event }: { event: CallEventItem }) {
  switch (event.event_type) {
    case 'transcript':
      return <TranscriptBubble event={event} side="caller" />
    case 'llm_response':
      return <TranscriptBubble event={event} side="ai" />
    case 'node_transition':
      return <NodeTransitionMarker event={event} />
    case 'action_executed':
      return <ActionEvent event={event} />
    case 'error':
      return <ErrorEvent event={event} />
    case 'summary_generated':
      return <SummaryEvent event={event} />
    default:
      return (
        <div className="text-xs text-gray-600 my-1">
          {event.event_type}: {JSON.stringify(event.data_json)}
        </div>
      )
  }
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function CallDetail() {
  const { id } = useParams<{ id: string }>()
  const [call, setCall] = useState<CallDetailType | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!id) return
    try {
      setLoading(true)
      setError(null)
      const data = await api.calls.get(id)
      setCall(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="flex-1">
      <div className="bg-gray-900/50 border-b border-gray-800 px-6 py-3 flex items-center gap-2">
        <Link to="/calls" className="text-gray-400 hover:text-gray-200 text-sm transition">
          Calls
        </Link>
        <span className="text-gray-600 text-sm">›</span>
        <span className="text-gray-300 text-sm">Detail</span>
      </div>

      <main className="max-w-3xl mx-auto py-8 px-4">
        {loading && <p className="text-gray-400">Loading…</p>}
        {error && <p className="text-red-400">{error}</p>}

        {call && (
          <>
            {/* Metadata header */}
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 mb-6">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-white font-semibold text-lg">
                  Call from {call.from_number}
                </h2>
                <Badge className={`text-xs ${statusStyles[call.status] ?? 'bg-gray-800 text-gray-400'}`}>
                  {call.status.replace('_', ' ')}
                </Badge>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
                <div>
                  <span className="text-gray-500 block">To</span>
                  <span className="text-gray-300 font-mono text-xs">{call.to_number}</span>
                </div>
                <div>
                  <span className="text-gray-500 block">Started</span>
                  <span className="text-gray-300">{formatDateTime(call.started_at)}</span>
                </div>
                <div>
                  <span className="text-gray-500 block">Duration</span>
                  <span className="text-gray-300">{formatDuration(call.duration_seconds)}</span>
                </div>
                <div>
                  <span className="text-gray-500 block">Workflow</span>
                  <span className="text-gray-300">{call.workflow_name ?? '—'}</span>
                </div>
              </div>
            </div>

            {/* Transcript / events */}
            <h3 className="text-gray-400 font-medium text-sm mb-4 uppercase tracking-wide">
              Transcript & Events ({call.events.length})
            </h3>
            {call.events.length === 0 ? (
              <p className="text-gray-600 text-sm">No events recorded for this call.</p>
            ) : (
              <div className="space-y-1">
                {call.events.map((event) => (
                  <EventRenderer key={event.id} event={event} />
                ))}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
