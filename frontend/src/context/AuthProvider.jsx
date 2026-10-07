import { useCallback, useEffect, useMemo, useState } from 'react'
import { authService } from '../services/authService'
import { AuthContext } from './auth-context'

export default function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [isLoading, setIsLoading] = useState(true)

  // Restore the session (if any) once on startup.
  useEffect(() => {
    let cancelled = false
    async function restoreSession() {
      try {
        await authService.init()
        const currentUser = await authService.currentUser()
        if (!cancelled) setUser(currentUser)
      } catch {
        if (!cancelled) setUser(null)
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }
    restoreSession()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (credentials) => {
    const loggedInUser = await authService.login(credentials)
    setUser(loggedInUser)
    return loggedInUser
  }, [])

  const logout = useCallback(async () => {
    try {
      await authService.logout()
    } finally {
      setUser(null)
    }
  }, [])

  // Saves the profile in Django, then updates the shared user state so the
  // new name shows everywhere immediately.
  const updateProfile = useCallback(async (profile) => {
    const updatedUser = await authService.updateProfile(profile)
    setUser(updatedUser)
    return updatedUser
  }, [])

  const value = useMemo(
    () => ({ user, isAuthenticated: Boolean(user), isLoading, login, logout, updateProfile }),
    [user, isLoading, login, logout, updateProfile],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
