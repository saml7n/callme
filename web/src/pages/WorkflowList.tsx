/** Workflow list page — shows all workflows with links to edit/create. */

import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { api } from '@/lib/api'
import type { WorkflowListItem } from '@/lib/types'

export default function WorkflowList() {
  const [workflows, setWorkflows] = useState<WorkflowListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()

  const load = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await api.workflows.list()
      setWorkflows(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleDelete = useCallback(
    async (id: string, name: string) => {
      if (!confirm(`Delete "${name}"? This cannot be undone.`)) return
      try {
        await api.workflows.delete(id)
        setWorkflows((prev) => prev.filter((w) => w.id !== id))
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to delete')
      }
    },
    [],
  )

  return (
    <div className="min-h-screen bg-gray-950">
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/" className="text-white font-bold text-lg hover:text-indigo-400 transition">
            CallMe
          </Link>
          <span className="text-gray-600">›</span>
          <span className="text-gray-300">Workflows</span>
        </div>
        <Button
          className="bg-indigo-600 text-white hover:bg-indigo-500"
          onClick={() => navigate('/workflows/new')}
        >
          + New Workflow
        </Button>
      </header>

      <main className="max-w-4xl mx-auto py-8 px-4">
        {loading && <p className="text-gray-400">Loading…</p>}
        {error && <p className="text-red-400">{error}</p>}

        {!loading && workflows.length === 0 && (
          <div className="text-center py-16">
            <p className="text-gray-500 mb-4">No workflows yet</p>
            <Button onClick={() => navigate('/workflows/new')}>
              Create your first workflow
            </Button>
          </div>
        )}

        {workflows.length > 0 && (
          <div className="space-y-2">
            {workflows.map((wf) => (
              <div
                key={wf.id}
                className="bg-gray-900 border border-gray-800 rounded-lg px-5 py-4 flex items-center justify-between hover:border-gray-700 transition"
              >
                <div className="flex items-center gap-3">
                  <div>
                    <Link
                      to={`/workflows/${wf.id}/edit`}
                      className="text-white font-medium hover:text-indigo-400 transition"
                    >
                      {wf.name}
                    </Link>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-xs text-gray-500">v{wf.version}</span>
                      {wf.is_active && (
                        <Badge className="bg-green-900 text-green-300 text-[10px]">
                          Active
                        </Badge>
                      )}
                      {wf.phone_number && (
                        <span className="text-xs text-gray-500 font-mono">
                          {wf.phone_number}
                        </span>
                      )}
                      <span className="text-xs text-gray-600">
                        {new Date(wf.updated_at).toLocaleDateString()}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => navigate(`/workflows/${wf.id}/edit`)}
                  >
                    Edit
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-red-400 hover:text-red-300"
                    onClick={() => handleDelete(wf.id, wf.name)}
                  >
                    Delete
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
