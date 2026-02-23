import { useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from './lib/api'

function App() {
  const navigate = useNavigate()

  useEffect(() => {
    // Auto-redirect to setup wizard if not yet configured
    api.settings.get()
      .then((res) => {
        if (!res.configured) navigate('/setup')
      })
      .catch(() => {})
  }, [navigate])

  return (
    <div className="flex-1 flex items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-bold text-white mb-2">
          Pronto
        </h1>
        <p className="text-lg text-gray-400 mb-8">
          AI Receptionist
        </p>
        <div className="flex gap-3 justify-center flex-wrap">
          <Link
            to="/workflows"
            className="px-5 py-2.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 transition font-medium"
          >
            Workflows
          </Link>
          <Link
            to="/calls/live"
            className="px-5 py-2.5 bg-green-800 text-green-200 rounded-lg hover:bg-green-700 transition font-medium"
          >
            Live Calls
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
            to="/settings/phone-numbers"
            className="px-5 py-2.5 bg-gray-800 text-gray-300 rounded-lg hover:bg-gray-700 transition font-medium"
          >
            Phone Numbers
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
