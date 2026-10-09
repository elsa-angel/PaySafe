/** The backend decides the role (derived from Django's superuser flag); the UI only reads it. */
export const isAdmin = (user) => user?.role === 'admin'

export const homePathFor = (user) => (isAdmin(user) ? '/admin' : '/')

/** After login: go back to where the person was heading, unless their role may not open it. */
export function resolvePostLoginPath(user, requestedPath) {
  const wantsAdminArea = typeof requestedPath === 'string' && requestedPath.startsWith('/admin')
  if (requestedPath && requestedPath !== '/login' && isAdmin(user) === wantsAdminArea) return requestedPath
  return homePathFor(user)
}
