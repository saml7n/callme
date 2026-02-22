import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import './index.css'
import App from './App'
import WorkflowPreview from './pages/WorkflowPreview'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route path="/workflows/preview" element={<WorkflowPreview />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
