/** Auth guard — redirects to /login if not authenticated. */

import { Navigate } from 'react-router-dom'
import { isAuthenticated } from '@/lib/auth'

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}
