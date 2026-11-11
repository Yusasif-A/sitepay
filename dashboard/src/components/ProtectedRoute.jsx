import { Navigate } from 'react-router-dom'
import { useAuth } from '../lib/AuthContext'

export function RequireSupervisor({ children }) {
  const { token, loading } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  if (loading) return <div className="center-loading"><span className="spinner spinner-dark" /></div>
  return children
}
