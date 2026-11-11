import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from './api'

const TOKEN_KEY = 'sitepay_token'
const SITE_KEY = 'sitepay_site'
const AuthContext = createContext(null)

function readStorage(key) {
  try { return localStorage.getItem(key) || '' } catch { return '' }
}
function writeStorage(key, value) {
  try { value ? localStorage.setItem(key, value) : localStorage.removeItem(key) } catch { /* private mode */ }
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => readStorage(TOKEN_KEY))
  const [me, setMe] = useState(null)
  const [siteId, setSiteIdState] = useState(() => readStorage(SITE_KEY))
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async (t = token) => {
    if (!t) { setMe(null); setLoading(false); return null }
    try {
      const data = await api.get('/api/me', t)
      setMe(data)
      setSiteIdState((current) => {
        const valid = data.sites.some((s) => s.site_id === current)
        const next = valid ? current : (data.sites[0]?.site_id || '')
        writeStorage(SITE_KEY, next)
        return next
      })
      return data
    } catch (err) {
      if (err.status === 401) logout()
      return null
    } finally {
      setLoading(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  useEffect(() => { refresh() }, [refresh])

  function setSession(newToken) {
    writeStorage(TOKEN_KEY, newToken)
    setToken(newToken)
  }

  async function login(email, password) {
    const { token: t } = await api.post('/api/auth/login', { email, password })
    setSession(t)
  }

  async function signup(fields) {
    const { token: t } = await api.post('/api/auth/signup', fields)
    setSession(t)
  }

  function logout() {
    writeStorage(TOKEN_KEY, '')
    setToken('')
    setMe(null)
  }

  function setSiteId(id) {
    writeStorage(SITE_KEY, id)
    setSiteIdState(id)
  }

  const site = me?.sites.find((s) => s.site_id === siteId) || null
  const value = { token, me, site, siteId, setSiteId, login, signup, logout, refresh, loading }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
