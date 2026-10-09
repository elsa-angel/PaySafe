import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../context/useAuth'
import { homePathFor, isAdmin } from '../utils/roles'
import FullScreenLoader from './FullScreenLoader'

/** Renders child routes only for signed-in users; otherwise redirects to /login. */
export function ProtectedRoute() {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) return <FullScreenLoader />
  if (!isAuthenticated) return <Navigate to="/login" replace state={{ from: location }} />
  return <Outlet />
}

/**
 * Usability guard for role-specific areas ('admin' or 'user'). The real
 * enforcement is on the server: every admin API checks the Django superuser flag.
 */
export function RoleRoute({ role }) {
  const { user } = useAuth()
  const allowed = role === 'admin' ? isAdmin(user) : !isAdmin(user)
  return allowed ? <Outlet /> : <Navigate to={homePathFor(user)} replace />
}

/** Keeps signed-in users away from the login/signup pages. */
export function PublicOnlyRoute() {
  const { user, isAuthenticated, isLoading } = useAuth()

  if (isLoading) return <FullScreenLoader />
  if (isAuthenticated) return <Navigate to={homePathFor(user)} replace />
  return <Outlet />
}
