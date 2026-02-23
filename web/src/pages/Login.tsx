/** Login page — email + password with API key fallback. */

import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { setToken } from '@/lib/auth'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [useApiKey, setUseApiKey] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()

    try {
      setLoading(true)
      setError(null)

      if (useApiKey) {
        if (!apiKey.trim()) return
        const res = await api.auth.loginWithKey(apiKey.trim())
        setToken(res.token)
      } else {
        if (!email.trim() || !password) return
        const res = await api.auth.login(email.trim(), password)
        setToken(res.token)
      }

      navigate('/')
    } catch {
      setError(useApiKey ? 'Invalid API key' : 'Invalid email or password')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-white font-bold text-2xl mb-2">Pronto</h1>
          <p className="text-gray-500 text-sm">Sign in to your account</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4" data-testid="login-form">
          {useApiKey ? (
            <div>
              <label htmlFor="api-key" className="block text-sm text-gray-400 mb-1">
                API Key
              </label>
              <input
                id="api-key"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="Enter your CALLME_API_KEY"
                className="w-full bg-gray-900 border border-gray-800 rounded-lg px-4 py-2.5 text-white placeholder-gray-600 focus:outline-none focus:border-indigo-500 transition"
                autoFocus
                autoComplete="current-password"
                data-testid="login-api-key"
              />
            </div>
          ) : (
            <>
              <div>
                <label htmlFor="email" className="block text-sm text-gray-400 mb-1">
                  Email
                </label>
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  className="w-full bg-gray-900 border border-gray-800 rounded-lg px-4 py-2.5 text-white placeholder-gray-600 focus:outline-none focus:border-indigo-500 transition"
                  autoFocus
                  autoComplete="email"
                  data-testid="login-email"
                />
              </div>
              <div>
                <label htmlFor="password" className="block text-sm text-gray-400 mb-1">
                  Password
                </label>
                <input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Your password"
                  className="w-full bg-gray-900 border border-gray-800 rounded-lg px-4 py-2.5 text-white placeholder-gray-600 focus:outline-none focus:border-indigo-500 transition"
                  autoComplete="current-password"
                  data-testid="login-password"
                />
              </div>
            </>
          )}

          {error && <p className="text-red-400 text-sm" data-testid="login-error">{error}</p>}

          <Button
            type="submit"
            disabled={loading || (useApiKey ? !apiKey.trim() : !email.trim() || !password)}
            className="w-full bg-indigo-600 text-white hover:bg-indigo-500"
            data-testid="login-submit"
          >
            {loading ? 'Signing in…' : 'Sign In'}
          </Button>
        </form>

        <div className="mt-4 text-center">
          <button
            type="button"
            onClick={() => {
              setUseApiKey(!useApiKey)
              setError(null)
            }}
            className="text-gray-600 hover:text-gray-400 text-xs transition"
            data-testid="login-toggle-mode"
          >
            {useApiKey ? 'Use email & password' : 'Use API key instead'}
          </button>
        </div>

        <p className="text-gray-500 text-sm text-center mt-6">
          Don&apos;t have an account?{' '}
          <Link to="/register" className="text-indigo-400 hover:text-indigo-300 transition">
            Sign up
          </Link>
        </p>
      </div>
    </div>
  )
}
