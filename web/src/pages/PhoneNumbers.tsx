/** Phone number management page — /settings/phone-numbers (Story 14) */

import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import type { PhoneNumberItem } from '@/lib/types'

export default function PhoneNumbers() {
  const [phones, setPhones] = useState<PhoneNumberItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  // Add form
  const [newNumber, setNewNumber] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const [adding, setAdding] = useState(false)

  const load = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await api.phoneNumbers.list()
      setPhones(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleAdd = useCallback(async () => {
    if (!newNumber.trim()) return
    try {
      setAdding(true)
      setError(null)
      const phone = await api.phoneNumbers.create(newNumber.trim(), newLabel.trim())
      setPhones((prev) => [phone, ...prev])
      setNewNumber('')
      setNewLabel('')
      setSuccessMsg('Phone number registered')
      setTimeout(() => setSuccessMsg(null), 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add')
    } finally {
      setAdding(false)
    }
  }, [newNumber, newLabel])

  const handleDelete = useCallback(async (id: string, number: string) => {
    if (!confirm(`Remove ${number}? This cannot be undone.`)) return
    try {
      setError(null)
      await api.phoneNumbers.delete(id)
      setPhones((prev) => prev.filter((p) => p.id !== id))
      setSuccessMsg('Phone number removed')
      setTimeout(() => setSuccessMsg(null), 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete')
    }
  }, [])

  return (
    <div className="min-h-screen bg-gray-950">
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/" className="text-white font-bold text-lg hover:text-indigo-400 transition">
            CallMe
          </Link>
          <span className="text-gray-600">›</span>
          <span className="text-gray-300">Settings</span>
          <span className="text-gray-600">›</span>
          <span className="text-gray-300">Phone Numbers</span>
        </div>
        <div className="flex items-center gap-2">
          <Link to="/workflows">
            <Button variant="outline" size="sm">Workflows</Button>
          </Link>
          <Link to="/calls">
            <Button variant="outline" size="sm">Calls</Button>
          </Link>
        </div>
      </header>

      <main className="max-w-3xl mx-auto py-8 px-4">
        <h2 className="text-xl font-semibold text-white mb-6">Phone Numbers</h2>

        {/* Add form */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 mb-6">
          <h3 className="text-sm font-medium text-gray-300 mb-3">Add Number</h3>
          <div className="flex items-end gap-3">
            <div className="flex-1">
              <Label className="text-gray-400 text-xs mb-1">Number (E.164)</Label>
              <Input
                value={newNumber}
                onChange={(e) => setNewNumber(e.target.value)}
                placeholder="+441234567890"
                className="bg-gray-800 border-gray-700 text-white"
              />
            </div>
            <div className="flex-1">
              <Label className="text-gray-400 text-xs mb-1">Label</Label>
              <Input
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
                placeholder="Main Office"
                className="bg-gray-800 border-gray-700 text-white"
              />
            </div>
            <Button
              className="bg-indigo-600 text-white hover:bg-indigo-500"
              onClick={handleAdd}
              disabled={adding || !newNumber.trim()}
            >
              {adding ? 'Adding…' : 'Add'}
            </Button>
          </div>
        </div>

        {/* Status messages */}
        {successMsg && <p className="text-green-400 text-sm mb-4">{successMsg}</p>}
        {error && <p className="text-red-400 text-sm mb-4">{error}</p>}

        {/* Phone number list */}
        {loading && <p className="text-gray-400">Loading…</p>}

        {!loading && phones.length === 0 && (
          <div className="text-center py-12">
            <p className="text-gray-500">No phone numbers registered yet.</p>
            <p className="text-gray-600 text-sm mt-1">Add a number above to get started.</p>
          </div>
        )}

        {phones.length > 0 && (
          <div className="space-y-2">
            {phones.map((phone) => (
              <div
                key={phone.id}
                className="bg-gray-900 border border-gray-800 rounded-lg px-5 py-4 flex items-center justify-between hover:border-gray-700 transition"
              >
                <div>
                  <div className="flex items-center gap-3">
                    <span className="text-white font-mono">{phone.number}</span>
                    {phone.label && (
                      <span className="text-gray-400 text-sm">{phone.label}</span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 mt-1">
                    {phone.workflow_id ? (
                      <>
                        <Badge className="bg-green-900 text-green-300 text-[10px]">
                          In use
                        </Badge>
                        <Link
                          to={`/workflows/${phone.workflow_id}/edit`}
                          className="text-xs text-indigo-400 hover:text-indigo-300"
                        >
                          {phone.workflow_name ?? 'Unknown workflow'}
                        </Link>
                      </>
                    ) : (
                      <Badge variant="outline" className="text-gray-500 text-[10px]">
                        Available
                      </Badge>
                    )}
                  </div>
                </div>

                <Button
                  size="sm"
                  variant="ghost"
                  className="text-red-400 hover:text-red-300"
                  onClick={() => handleDelete(phone.id, phone.number)}
                  disabled={!!phone.workflow_id}
                  title={phone.workflow_id ? 'Deactivate the workflow first' : 'Remove'}
                >
                  Remove
                </Button>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
