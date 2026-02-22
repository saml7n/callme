import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import './index.css'
import App from './App'
import AuthGuard from './components/AuthGuard'
import Login from './pages/Login'
import WorkflowPreview from './pages/WorkflowPreview'
import WorkflowBuilder from './pages/WorkflowBuilder'
import WorkflowList from './pages/WorkflowList'
import CallList from './pages/CallList'
import CallDetail from './pages/CallDetail'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<AuthGuard><App /></AuthGuard>} />
        <Route path="/workflows" element={<AuthGuard><WorkflowList /></AuthGuard>} />
        <Route path="/workflows/new" element={<AuthGuard><WorkflowBuilder /></AuthGuard>} />
        <Route path="/workflows/:id/edit" element={<AuthGuard><WorkflowBuilder /></AuthGuard>} />
        <Route path="/workflows/preview" element={<AuthGuard><WorkflowPreview /></AuthGuard>} />
        <Route path="/calls" element={<AuthGuard><CallList /></AuthGuard>} />
        <Route path="/calls/:id" element={<AuthGuard><CallDetail /></AuthGuard>} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
