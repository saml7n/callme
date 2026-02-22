/** Call log list page — shows recent calls with masking, status badges, and pagination. */

import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { api } from '@/lib/api'
import type { CallListItem } from '@/lib/types'
import { maskPhone, formatDuration, formatDateTime } from '@/lib/phone'

const PAGE_SIZE = 50

const statusStyles: Record<string, string> = {
  completed: 'bg-green-900 text-green-300',
  transferred: 'bg-blue-900 text-blue-300',
  error: 'bg-red-900 text-red-300',
  in_progress: 'bg-yellow-900 text-yellow-300',
}

export default function CallList() {
  const [calls, setCalls] = useState<CallListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const navigate = useNavigate()

  const load = useCallback(async (off: number) => {
    try {
      setLoading(true)
      setError(null)
      const data = await api.calls.list(PAGE_SIZE, off)
      setCalls(data)
      setHasMore(data.length === PAGE_SIZE)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(offset)
  }, [load, offset])

  return (
    <div className="min-h-screen bg-gray-950">
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/" className="text-white font-bold text-lg hover:text-indigo-400 transition">
            CallMe
          </Link>
          <span className="text-gray-600">›</span>
          <span className="text-gray-300">Calls</span>
        </div>
        <Link to="/workflows">
          <Button variant="outline" size="sm">Workflows</Button>
        </Link>
      </header>

      <main className="max-w-5xl mx-auto py-8 px-4">
        {loading && <p className="text-gray-400">Loading…</p>}
        {error && <p className="text-red-400">{error}</p>}

        {!loading && calls.length === 0 && (
          <div className="text-center py-16">
            <p className="text-gray-500 mb-4">No calls yet</p>
            <p className="text-gray-600 text-sm">
              Calls will appear here once your first phone call is received.
            </p>
          </div>
        )}

        {calls.length > 0 && (
          <>
            {/* Table */}
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="text-gray-500 border-b border-gray-800">
                    <th className="py-3 px-3 font-medium">Date / Time</th>
                    <th className="py-3 px-3 font-medium">Caller</th>
                    <th className="py-3 px-3 font-medium">Duration</th>
                    <th className="py-3 px-3 font-medium">Workflow</th>
                    <th className="py-3 px-3 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {calls.map((call) => (
                    <tr
                      key={call.id}
                      className="border-b border-gray-800/50 hover:bg-gray-900 cursor-pointer transition"
                      onClick={() => navigate(`/calls/${call.id}`)}
                      data-testid="call-row"
                    >
                      <td className="py-3 px-3 text-gray-300">
                        {formatDateTime(call.started_at)}
                      </td>
                      <td className="py-3 px-3 text-gray-300 font-mono text-xs">
                        {maskPhone(call.from_number)}
                      </td>
                      <td className="py-3 px-3 text-gray-400">
                        {formatDuration(call.duration_seconds)}
                      </td>
                      <td className="py-3 px-3 text-gray-400">
                        {call.workflow_name ?? '—'}
                      </td>
                      <td className="py-3 px-3">
                        <Badge className={`text-[10px] ${statusStyles[call.status] ?? 'bg-gray-800 text-gray-400'}`}>
                          {call.status.replace('_', ' ')}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div className="flex items-center justify-between mt-4">
              <Button
                variant="outline"
                size="sm"
                disabled={offset === 0}
                onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
              >
                ← Previous
              </Button>
              <span className="text-gray-500 text-sm">
                Showing {offset + 1}–{offset + calls.length}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={!hasMore}
                onClick={() => setOffset((o) => o + PAGE_SIZE)}
              >
                Next →
              </Button>
            </div>
          </>
        )}
      </main>
    </div>
  )
}
