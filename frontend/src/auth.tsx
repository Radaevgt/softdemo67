import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { api, setUnauthorizedHandler, token } from './api'
import type { Role, User } from './types'

interface AuthState {
  user: User | null
  loading: boolean
  signIn: (login: string, password: string) => Promise<void>
  signOut: () => void
  can: (...roles: Role[]) => boolean
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const signOut = useCallback(() => {
    token.clear()
    setUser(null)
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null))
  }, [])

  useEffect(() => {
    if (!token.get()) {
      setLoading(false)
      return
    }
    api
      .me()
      .then(setUser)
      .catch(() => token.clear())
      .finally(() => setLoading(false))
  }, [])

  const signIn = useCallback(async (login: string, password: string) => {
    await api.login(login, password)
    setUser(await api.me())
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      signIn,
      signOut,
      can: (...roles: Role[]) => (user ? roles.includes(user.role) : false),
    }),
    [user, loading, signIn, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth вызван вне AuthProvider')
  return context
}
