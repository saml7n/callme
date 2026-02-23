/** 404 page — shown for unknown routes. */

import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <div className="flex-1 flex items-center justify-center">
      <div className="text-center">
        <h1 className="text-6xl font-bold text-gray-700 mb-4">404</h1>
        <p className="text-gray-400 mb-6">Page not found</p>
        <Link
          to="/"
          className="px-5 py-2.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 transition font-medium"
        >
          Go Home
        </Link>
      </div>
    </div>
  )
}
