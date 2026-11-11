import { Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './lib/AuthContext'
import { RequireSupervisor } from './components/ProtectedRoute'
import DashboardLayout from './components/DashboardLayout'
import Landing from './pages/Landing'
import { Login, Signup } from './pages/Auth'
import Register from './pages/Register'
import PayRuns from './pages/PayRuns'
import Crew from './pages/Crew'
import Sites from './pages/Sites'
import SiteCalendar from './pages/SiteCalendar'

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/app" element={<RequireSupervisor><DashboardLayout /></RequireSupervisor>}>
          <Route index element={<Register />} />
          <Route path="calendar" element={<SiteCalendar />} />
          <Route path="pay" element={<PayRuns />} />
          <Route path="crew" element={<Crew />} />
          <Route path="sites" element={<Sites />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  )
}
