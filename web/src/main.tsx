import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import './index.css'
import App from './App'
import AuthGuard from './components/AuthGuard'
import AppShell from './components/AppShell'
import Login from './pages/Login'
import WorkflowPreview from './pages/WorkflowPreview'
import WorkflowBuilder from './pages/WorkflowBuilder'
import WorkflowList from './pages/WorkflowList'
import CallList from './pages/CallList'
import CallDetail from './pages/CallDetail'
import PhoneNumbers from './pages/PhoneNumbers'
import Integrations from './pages/Integrations'
import Setup from './pages/Setup'
import LiveCalls from './pages/LiveCalls'
import NotFound from './pages/NotFound'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        {/* All authenticated routes share the AppShell nav bar */}
        <Route element={<AuthGuard><AppShell /></AuthGuard>}>
          <Route path="/" element={<App />} />
          <Route path="/setup" element={<Setup />} />
          <Route path="/workflows" element={<WorkflowList />} />
          <Route path="/workflows/new" element={<WorkflowBuilder />} />
          <Route path="/workflows/:id/edit" element={<WorkflowBuilder />} />
          <Route path="/workflows/preview" element={<WorkflowPreview />} />
          <Route path="/calls/live" element={<LiveCalls />} />
          <Route path="/calls" element={<CallList />} />
          <Route path="/calls/:id" element={<CallDetail />} />
          <Route path="/settings/phone-numbers" element={<PhoneNumbers />} />
          <Route path="/settings/integrations" element={<Integrations />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
