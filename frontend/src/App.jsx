import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './auth'
import { ToastProvider, Spinner } from './components/ui'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Projects from './pages/Projects'
import Campaigns from './pages/Campaigns'
import CampaignBuilder from './pages/CampaignBuilder'
import Templates from './pages/Templates'
import Tracking from './pages/Tracking'
import Users from './pages/Users'
import Roles from './pages/Roles'
import Settings from './pages/Settings'

function Protected({ children }) {
  const { user, loading } = useAuth()
  if (loading) return <Spinner />
  if (!user) return <Navigate to="/login" replace />
  return children
}

export default function App() {
  const { loading } = useAuth()
  if (loading) return <Spinner />
  return (
    <ToastProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Protected><Dashboard /></Protected>} />
        <Route path="/projects" element={<Protected><Projects /></Protected>} />
        <Route path="/campaigns" element={<Protected><Campaigns /></Protected>} />
        <Route path="/campaigns/:id" element={<Protected><CampaignBuilder /></Protected>} />
        <Route path="/templates" element={<Protected><Templates /></Protected>} />
        <Route path="/tracking" element={<Protected><Tracking /></Protected>} />
        <Route path="/users" element={<Protected><Users /></Protected>} />
        <Route path="/roles" element={<Protected><Roles /></Protected>} />
        <Route path="/settings" element={<Protected><Settings /></Protected>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </ToastProvider>
  )
}
