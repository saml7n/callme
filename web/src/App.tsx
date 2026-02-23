import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { clearToken } from './lib/auth'
import { api } from './lib/api'

function App() {
  const navigate = useNavigate()
  const [warnings, setWarnings] = useState<string[]>([])

  useEffect(() => {
    api.auth.configWarnings()
      .then((res) => setWarnings(res.warnings))
      .catch(() => {})

    // Auto-redirect to setup wizard if not yet configured
    api.settings.get()
      .then((res) => {
        if (!res.configured) navigate('/setup')
      })
      .catch(() => {})
  }, [navigate])

  const handleLogout = () => {
    clearToken()
    navigate('/login')
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center relative">
      <button
        onClick={handleLogout}
        className="absolute top-4 right-4 text-gray-500 hover:text-gray-300 text-sm transition"
      >
        Sign Out
      </button>

      {warnings.length > 0 && (
        <div className="absolute top-4 left-4 right-24 space-y-2">
          {warnings.map((w, i) => (
            <div
              key={i}
              className="bg-yellow-900/40 border border-yellow-700/50 text-yellow-300 text-xs px-3 py-2 rounded-lg"
            >
              ⚠ {w}
            </div>
          ))}
        </div>
      )}
      <div className="text-center">
        <h1 className="text-4xl font-bold text-white mb-2">
          CallMe
        </h1>
        <p className="text-lg text-gray-400 mb-8">
          AI Receptionist
        </p>
        <div className="flex gap-3 justify-center">
          <Link
            to="/workflows"
            className="px-5 py-2.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 transition font-medium"
          >
            Workflows
          </Link>
          <Link
            to="/calls"
            className="px-5 py-2.5 bg-gray-800 text-gray-300 rounded-lg hover:bg-gray-700 transition font-medium"
          >
            Calls
          </Link>
          <Link
            to="/workflows/new"
            className="px-5 py-2.5 bg-gray-800 text-gray-300 rounded-lg hover:bg-gray-700 transition font-medium"
          >
            New Workflow
          </Link>
          <Link
            to="/settings/integrations"
            className="px-5 py-2.5 bg-gray-800 text-gray-300 rounded-lg hover:bg-gray-700 transition font-medium"
          >
            Integrations
          </Link>
          <Link
            to="/setup"
            className="px-5 py-2.5 bg-gray-800 text-gray-300 rounded-lg hover:bg-gray-700 transition font-medium"
          >
            Setup
          </Link>
        </div>
      </div>
    </div>
  )
}

export default App
