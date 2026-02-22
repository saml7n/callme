/** Login page — single API key field. */

import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { setToken } from '@/lib/auth'

export default function Login() {
  const [key, setKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!key.trim()) return

    try {
      setLoading(true)
      setError(null)
      const res = await api.auth.login(key.trim())
      setToken(res.token)
      navigate('/')
    } catch {
      setError('Invalid API key')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-white font-bold text-2xl mb-2">CallMe</h1>
          <p className="text-gray-500 text-sm">Enter your API key to continue</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="api-key" className="block text-sm text-gray-400 mb-1">
              API Key
            </label>
            <input
              id="api-key"
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="Enter your CALLME_API_KEY"
              className="w-full bg-gray-900 border border-gray-800 rounded-lg px-4 py-2.5 text-white placeholder-gray-600 focus:outline-none focus:border-indigo-500 transition"
              autoFocus
              autoComplete="current-password"
            />
          </div>

          {error && <p className="text-red-400 text-sm">{error}</p>}

          <Button
            type="submit"
            disabled={loading || !key.trim()}
            className="w-full bg-indigo-600 text-white hover:bg-indigo-500"
          >
            {loading ? 'Verifying…' : 'Sign In'}
          </Button>
        </form>

        <p className="text-gray-600 text-xs text-center mt-6">
          Set <code className="text-gray-500">CALLME_API_KEY</code> in your{' '}
          <code className="text-gray-500">.env</code> file
        </p>
      </div>
    </div>
  )
}
