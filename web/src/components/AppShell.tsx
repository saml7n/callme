/** Global app shell — persistent nav bar wrapping all authenticated pages. */

import { useEffect, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { clearToken } from '@/lib/auth'
import { api } from '@/lib/api'

/* ------------------------------------------------------------------ */
/* Nav items                                                           */
/* ------------------------------------------------------------------ */

const NAV_ITEMS = [
  { label: 'Workflows', to: '/workflows' },
  { label: 'Calls', to: '/calls' },
  { label: 'Live Calls', to: '/calls/live' },
  { label: 'Phone Numbers', to: '/settings/phone-numbers' },
  { label: 'Integrations', to: '/settings/integrations' },
] as const

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

export default function AppShell() {
  const location = useLocation()
  const navigate = useNavigate()
  const [warnings, setWarnings] = useState<string[]>([])

  useEffect(() => {
    api.auth.configWarnings()
      .then((res) => setWarnings(res.warnings))
      .catch(() => {})
  }, [location.pathname])

  const handleLogout = () => {
    clearToken()
    navigate('/login')
  }

  /** Check if the given path is "active" for nav highlighting. */
  const isActive = (to: string) => {
    if (to === '/') return location.pathname === '/'
    return location.pathname === to || location.pathname.startsWith(to + '/')
  }

  return (
    <div className="min-h-screen bg-gray-950 flex flex-col">
      {/* ── Nav bar ── */}
      <nav className="bg-gray-900 border-b border-gray-800 px-6 py-3 flex items-center justify-between shrink-0" data-testid="app-nav">
        {/* Left: logo + links */}
        <div className="flex items-center gap-6">
          <Link to="/" className="text-white font-bold text-lg hover:text-indigo-400 transition" data-testid="nav-home">
            Pronto
          </Link>

          <div className="flex items-center gap-1">
            {NAV_ITEMS.map(({ label, to }) => (
              <Link
                key={to}
                to={to}
                className={`px-3 py-1.5 rounded-md text-sm transition ${
                  isActive(to)
                    ? 'bg-gray-800 text-white font-medium'
                    : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50'
                }`}
                data-testid={`nav-${label.toLowerCase().replace(/\s+/g, '-')}`}
              >
                {label}
              </Link>
            ))}
          </div>
        </div>

        {/* Right: setup + sign-out */}
        <div className="flex items-center gap-3">
          <Link
            to="/setup"
            className={`p-1.5 rounded-md transition ${
              isActive('/setup')
                ? 'text-white bg-gray-800'
                : 'text-gray-500 hover:text-gray-300 hover:bg-gray-800/50'
            }`}
            title="Setup wizard"
            data-testid="nav-setup"
          >
            {/* Gear icon (heroicons outline) */}
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
            </svg>
          </Link>
          <button
            onClick={handleLogout}
            className="text-gray-500 hover:text-gray-300 text-sm transition"
            data-testid="nav-signout"
          >
            Sign Out
          </button>
        </div>
      </nav>

      {/* ── Config warnings ── */}
      {warnings.length > 0 && (
        <div className="px-6 pt-3 space-y-2" data-testid="config-warnings">
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

      {/* ── Page content ── */}
      <Outlet />
    </div>
  )
}
