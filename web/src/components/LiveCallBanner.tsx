/** Persistent banner showing the number of active live calls. */

import { Link } from 'react-router-dom'
import { useLiveCallCount } from '@/hooks/useLiveCallCount'

export default function LiveCallBanner() {
  const count = useLiveCallCount()

  if (count < 1) return null

  const label = count === 1 ? '1 live call' : `${count} live calls`

  return (
    <Link
      to="/calls/live"
      className="flex items-center gap-2 px-3 py-1 rounded-full bg-green-600/20 border border-green-500/30 text-green-400 text-xs font-medium hover:bg-green-600/30 transition"
      data-testid="live-call-banner"
      aria-live="polite"
    >
      <span className="relative flex h-2 w-2">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
      </span>
      {label}
    </Link>
  )
}
