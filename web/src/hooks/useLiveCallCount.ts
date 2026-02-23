/** Hook that polls the live call count endpoint and returns the current count. */

import { useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'

const POLL_INTERVAL_MS = 5_000

/**
 * Poll `/api/calls/live/count` every 5 seconds.
 * Returns the number of currently active calls.
 */
export function useLiveCallCount(): number {
  const [count, setCount] = useState(0)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    let cancelled = false

    const poll = async () => {
      try {
        const { count: c } = await api.calls.liveCount()
        if (!cancelled) setCount(c)
      } catch {
        // Silently ignore — banner just keeps last known count
      }
    }

    // Fire immediately, then every 5s
    poll()
    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [])

  return count
}
