/** Live calls dashboard — real-time view of active calls with transcript and transfer. */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { api } from '@/lib/api'
import { getToken } from '@/lib/auth'
import type { ActiveCall, LiveCallEvent, TranscriptMessage } from '@/lib/types'

interface CallState {
  call: ActiveCall
  transcript: TranscriptMessage[]
  transferred: boolean
  ended: boolean
}

function formatElapsed(startedAt: number): string {
  const seconds = Math.floor(Date.now() / 1000 - startedAt)
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

function maskPhone(number: string): string {
  if (!number || number.length <= 6) return number || 'Unknown'
  return number.slice(0, 3) + '•'.repeat(number.length - 6) + number.slice(-3)
}

export default function LiveCalls() {
  const [calls, setCalls] = useState<Record<string, CallState>>({})
  const [connected, setConnected] = useState(false)
  const [transferring, setTransferring] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const unmountedRef = useRef(false)

  // Timer tick for elapsed time
  const [, setTick] = useState(0)
  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 1000)
    return () => clearInterval(interval)
  }, [])

  const connectWs = useCallback(() => {
    // Close any existing connection first to avoid duplicates
    if (wsRef.current) {
      wsRef.current.onclose = null
      wsRef.current.close()
      wsRef.current = null
    }

    const token = getToken()
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = import.meta.env.VITE_API_URL
      ? new URL(import.meta.env.VITE_API_URL).host
      : window.location.host
    const url = `${protocol}//${host}/ws/calls/live${token ? `?token=${token}` : ''}`

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)
    ws.onclose = () => {
      setConnected(false)
      // Don't reconnect if we've been unmounted
      if (!unmountedRef.current) {
        reconnectRef.current = setTimeout(connectWs, 3000)
      }
    }
    ws.onerror = () => ws.close()

    ws.onmessage = (ev) => {
      try {
        const event: LiveCallEvent = JSON.parse(ev.data)
        handleEvent(event)
      } catch {
        // ignore malformed messages
      }
    }
  }, [])

  const handleEvent = useCallback((event: LiveCallEvent) => {
    setCalls((prev) => {
      const next = { ...prev }

      switch (event.type) {
        case 'snapshot': {
          // Initial state — hydrate active calls with their transcripts
          for (const c of event.calls ?? []) {
            const existingTranscript = (c as Record<string, unknown>).transcript as
              | { role: string; text: string; timestamp: number }[]
              | undefined
            next[c.call_id] = {
              call: c,
              transcript: existingTranscript?.map((t) => ({
                role: t.role as 'caller' | 'ai',
                text: t.text,
                timestamp: t.timestamp,
              })) ?? [],
              transferred: false,
              ended: false,
            }
          }
          break
        }
        case 'call_started': {
          const callId = event.call_id!
          next[callId] = {
            call: {
              call_id: callId,
              call_sid: '',
              caller_number: event.caller_number ?? '',
              workflow_name: event.workflow_name ?? '',
              started_at: event.timestamp ?? Date.now() / 1000,
            },
            transcript: [],
            transferred: false,
            ended: false,
          }
          // Request browser notification
          if ('Notification' in window && Notification.permission === 'granted') {
            new Notification('Incoming call', {
              body: `From ${maskPhone(event.caller_number ?? '')} on ${event.workflow_name ?? 'Unknown'}`,
            })
          }
          break
        }
        case 'transcript': {
          const callId = event.call_id!
          const state = next[callId]
          if (state) {
            next[callId] = {
              ...state,
              transcript: [
                ...state.transcript,
                { role: event.role!, text: event.text!, timestamp: event.timestamp ?? Date.now() / 1000 },
              ],
            }
          }
          break
        }
        case 'call_ended': {
          const callId = event.call_id!
          const state = next[callId]
          if (state) {
            next[callId] = { ...state, ended: true }
          }
          break
        }
        case 'transfer_started': {
          const callId = event.call_id!
          const state = next[callId]
          if (state) {
            next[callId] = { ...state, transferred: true }
          }
          break
        }
      }

      return next
    })
  }, [])

  useEffect(() => {
    unmountedRef.current = false
    connectWs()
    // Request notification permission
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
    return () => {
      unmountedRef.current = true
      if (reconnectRef.current) clearTimeout(reconnectRef.current)
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [connectWs])

  const handleTransfer = async (callId: string) => {
    setTransferring(callId)
    try {
      await api.calls.transfer(callId)
    } catch (err) {
      console.error('Transfer failed:', err)
    } finally {
      setTransferring(null)
    }
  }

  const activeCalls = Object.values(calls).filter((c) => !c.ended)
  const endedCalls = Object.values(calls).filter((c) => c.ended)

  return (
    <div className="min-h-screen bg-gray-950">
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/" className="text-white font-bold text-lg hover:text-indigo-400 transition">
            Pronto
          </Link>
          <span className="text-gray-600">›</span>
          <span className="text-gray-300">Live Calls</span>
          {connected ? (
            <Badge className="bg-green-900 text-green-300 text-[10px]">Connected</Badge>
          ) : (
            <Badge className="bg-red-900 text-red-300 text-[10px]">Disconnected</Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Link to="/calls">
            <Button variant="outline" size="sm">Call Log</Button>
          </Link>
          <Link to="/workflows">
            <Button variant="outline" size="sm">Workflows</Button>
          </Link>
        </div>
      </header>

      <main className="max-w-5xl mx-auto py-8 px-4">
        {activeCalls.length === 0 && endedCalls.length === 0 && (
          <div className="text-center py-16" data-testid="empty-state">
            <div className="inline-block w-3 h-3 bg-gray-600 rounded-full animate-pulse mb-4" />
            <p className="text-gray-500 mb-2">No active calls</p>
            <p className="text-gray-600 text-sm">Waiting for incoming calls…</p>
          </div>
        )}

        {activeCalls.length > 0 && (
          <div className="space-y-4 mb-8">
            <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide">
              Active ({activeCalls.length})
            </h2>
            {activeCalls.map((cs) => (
              <CallCard
                key={cs.call.call_id}
                state={cs}
                onTransfer={handleTransfer}
                transferring={transferring === cs.call.call_id}
              />
            ))}
          </div>
        )}

        {endedCalls.length > 0 && (
          <div className="space-y-4">
            <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide">
              Recently Ended
            </h2>
            {endedCalls.map((cs) => (
              <div
                key={cs.call.call_id}
                className="border border-gray-800 rounded-lg p-4 opacity-50"
                data-testid="ended-call"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="text-gray-500 font-mono text-sm">
                      {maskPhone(cs.call.caller_number)}
                    </span>
                    <span className="text-gray-600">{cs.call.workflow_name}</span>
                  </div>
                  <Link
                    to={`/calls/${cs.call.call_id}`}
                    className="text-indigo-400 text-sm hover:underline"
                  >
                    View call log
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}

/** Individual call card with live transcript and transfer button. */
function CallCard({
  state,
  onTransfer,
  transferring,
}: {
  state: CallState
  onTransfer: (callId: string) => void
  transferring: boolean
}) {
  const { call, transcript, transferred } = state
  const transcriptEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll transcript
  useEffect(() => {
    if (typeof transcriptEndRef.current?.scrollIntoView === 'function') {
      transcriptEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [transcript.length])

  return (
    <div className="border border-gray-800 rounded-lg overflow-hidden" data-testid="live-call-card">
      {/* Card header */}
      <div className="bg-gray-900 px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
          <span className="text-gray-300 font-mono text-sm" data-testid="caller-number">
            {maskPhone(call.caller_number)}
          </span>
          <span className="text-gray-600">•</span>
          <span className="text-gray-400 text-sm">{call.workflow_name || 'No workflow'}</span>
          <span className="text-gray-600">•</span>
          <span className="text-gray-500 text-sm tabular-nums">
            {formatElapsed(call.started_at)}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {transferred ? (
            <Badge className="bg-blue-900 text-blue-300 text-[10px]">Transferred</Badge>
          ) : (
            <Badge className="bg-indigo-900 text-indigo-300 text-[10px]">AI Active</Badge>
          )}
          {!transferred && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => onTransfer(call.call_id)}
              disabled={transferring}
              data-testid="transfer-btn"
              className="text-xs"
            >
              {transferring ? 'Transferring…' : '📞 Transfer to me'}
            </Button>
          )}
        </div>
      </div>

      {/* Transcript */}
      <div className="p-4 max-h-64 overflow-y-auto space-y-2 bg-gray-950">
        {transcript.length === 0 && (
          <p className="text-gray-600 text-sm italic">Waiting for conversation…</p>
        )}
        {transcript.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === 'caller' ? 'justify-start' : 'justify-end'}`}
          >
            <div
              className={`max-w-[80%] px-3 py-1.5 rounded-lg text-sm ${
                msg.role === 'caller'
                  ? 'bg-gray-800 text-gray-300'
                  : 'bg-indigo-900/50 text-indigo-200'
              }`}
              data-testid={`msg-${msg.role}`}
            >
              {msg.text}
            </div>
          </div>
        ))}
        <div ref={transcriptEndRef} />
      </div>
    </div>
  )
}
