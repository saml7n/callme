import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import './index.css'
import App from './App'
import WorkflowPreview from './pages/WorkflowPreview'
import WorkflowBuilder from './pages/WorkflowBuilder'
import WorkflowList from './pages/WorkflowList'
import CallList from './pages/CallList'
import CallDetail from './pages/CallDetail'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route path="/workflows" element={<WorkflowList />} />
        <Route path="/workflows/new" element={<WorkflowBuilder />} />
        <Route path="/workflows/:id/edit" element={<WorkflowBuilder />} />
        <Route path="/workflows/preview" element={<WorkflowPreview />} />
        <Route path="/calls" element={<CallList />} />
        <Route path="/calls/:id" element={<CallDetail />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
