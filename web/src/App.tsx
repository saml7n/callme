import { Link } from 'react-router-dom'

function App() {
  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
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
            to="/workflows/new"
            className="px-5 py-2.5 bg-gray-800 text-gray-300 rounded-lg hover:bg-gray-700 transition font-medium"
          >
            New Workflow
          </Link>
        </div>
      </div>
    </div>
  )
}

export default App
