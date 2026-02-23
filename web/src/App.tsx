import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from './lib/api'
import type { WorkflowListItem, CallListItem, PhoneNumberItem } from './lib/types'

/* ------------------------------------------------------------------ */
/* Dashboard card                                                      */
/* ------------------------------------------------------------------ */

function DashCard({
  to,
  icon,
  title,
  description,
  stat,
  accent = 'gray',
}: {
  to: string
  icon: string
  title: string
  description: string
  stat?: string
  accent?: 'indigo' | 'green' | 'gray' | 'amber'
}) {
  const accentMap = {
    indigo: 'border-indigo-800/60 hover:border-indigo-600/80 hover:bg-indigo-950/30',
    green: 'border-green-800/60 hover:border-green-600/80 hover:bg-green-950/30',
    amber: 'border-amber-800/60 hover:border-amber-600/80 hover:bg-amber-950/30',
    gray: 'border-gray-800 hover:border-gray-700 hover:bg-gray-900/50',
  }

  return (
    <Link
      to={to}
      className={`group block rounded-xl border bg-gray-900/40 p-5 transition-all ${accentMap[accent]}`}
    >
      <div className="flex items-start justify-between mb-3">
        <span className="text-2xl">{icon}</span>
        {stat && (
          <span className="text-xs font-mono text-gray-500 bg-gray-800/80 px-2 py-0.5 rounded-full">
            {stat}
          </span>
        )}
      </div>
      <h3 className="text-sm font-semibold text-white mb-1 group-hover:text-indigo-300 transition">
        {title}
      </h3>
      <p className="text-xs text-gray-500 leading-relaxed">{description}</p>
    </Link>
  )
}

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */

function App() {
  const navigate = useNavigate()
  const [workflows, setWorkflows] = useState<WorkflowListItem[]>([])
  const [calls, setCalls] = useState<CallListItem[]>([])
  const [phones, setPhones] = useState<PhoneNumberItem[]>([])
  const [loaded, setLoaded] = useState(false)

  const hydrate = useCallback(async () => {
    try {
      const settingsRes = await api.settings.get()
      if (!settingsRes.configured) {
        navigate('/setup')
        return
      }
    } catch { /* ignore */ }

    // Fetch stats in parallel
    const [wf, cl, ph] = await Promise.allSettled([
      api.workflows.list(),
      api.calls.list(5, 0),
      api.phoneNumbers.list(),
    ])
    if (wf.status === 'fulfilled') setWorkflows(wf.value)
    if (cl.status === 'fulfilled') setCalls(cl.value)
    if (ph.status === 'fulfilled') setPhones(ph.value)
    setLoaded(true)
  }, [navigate])

  useEffect(() => { hydrate() }, [hydrate])

  const activeWorkflow = workflows.find((w) => w.is_active)
  const activePhones = phones.filter((p) => p.workflow_id)
  const recentCall = calls[0]

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-4xl mx-auto px-6 py-12">
        {/* Hero */}
        <div className="mb-10">
          <h1 className="text-3xl font-bold text-white mb-2">Dashboard</h1>
          <p className="text-gray-500">
            {activeWorkflow
              ? <>Active workflow: <span className="text-indigo-400 font-medium">{activeWorkflow.name}</span> (v{activeWorkflow.version})</>
              : 'No active workflow — publish one to start taking calls.'}
          </p>
        </div>

        {/* Quick actions */}
        <section className="mb-10">
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-4">Quick Actions</h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <Link
              to="/workflows/new"
              className="flex items-center gap-3 rounded-lg border border-dashed border-gray-700 bg-gray-900/30 px-4 py-3 text-sm text-gray-400 hover:text-white hover:border-indigo-600 hover:bg-indigo-950/20 transition"
            >
              <span className="text-lg">＋</span>
              New Workflow
            </Link>
            <Link
              to="/calls/live"
              className="flex items-center gap-3 rounded-lg border border-dashed border-gray-700 bg-gray-900/30 px-4 py-3 text-sm text-gray-400 hover:text-white hover:border-green-600 hover:bg-green-950/20 transition"
            >
              <span className="text-lg">📡</span>
              Live Calls
            </Link>
            <Link
              to="/setup"
              className="flex items-center gap-3 rounded-lg border border-dashed border-gray-700 bg-gray-900/30 px-4 py-3 text-sm text-gray-400 hover:text-white hover:border-amber-600 hover:bg-amber-950/20 transition"
            >
              <span className="text-lg">⚙️</span>
              Setup Wizard
            </Link>
          </div>
        </section>

        {/* Main grid */}
        <section>
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-4">Overview</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <DashCard
              to="/workflows"
              icon="🔀"
              title="Workflows"
              description="Design and manage AI call flows"
              stat={loaded ? `${workflows.length}` : '…'}
              accent="indigo"
            />
            <DashCard
              to="/calls"
              icon="📞"
              title="Calls"
              description={recentCall
                ? `Last call ${new Date(recentCall.started_at).toLocaleDateString()}`
                : 'View your call history'}
              stat={loaded ? `${calls.length}${calls.length === 5 ? '+' : ''}` : '…'}
              accent="gray"
            />
            <DashCard
              to="/calls/live"
              icon="🟢"
              title="Live Calls"
              description="Monitor active calls in real time"
              accent="green"
            />
            <DashCard
              to="/settings/phone-numbers"
              icon="📱"
              title="Phone Numbers"
              description="Manage Twilio numbers and routing"
              stat={loaded ? `${activePhones.length} active` : '…'}
              accent="gray"
            />
            <DashCard
              to="/settings/integrations"
              icon="🔗"
              title="Integrations"
              description="Google Calendar, webhooks, and more"
              accent="gray"
            />
            <DashCard
              to="/setup"
              icon="🚀"
              title="Setup"
              description="API keys, first-run wizard, and config"
              accent="amber"
            />
          </div>
        </section>
      </div>
    </div>
  )
}

export default App
