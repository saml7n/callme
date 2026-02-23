/** Unit tests for the AppShell global navigation component. */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import AppShell from '@/components/AppShell'

// Mock API
vi.mock('@/lib/api', () => ({
  api: {
    auth: {
      configWarnings: vi.fn().mockResolvedValue({ warnings: [] }),
    },
    calls: {
      liveCount: vi.fn().mockResolvedValue({ count: 0 }),
    },
  },
}))

// Mock auth store
vi.mock('@/lib/auth', () => {
  let token: string | null = 'test-token'
  return {
    getToken: vi.fn(() => token),
    setToken: vi.fn((t: string) => { token = t }),
    clearToken: vi.fn(() => { token = null }),
    isAuthenticated: vi.fn(() => !!token),
    getUserInfo: vi.fn(() => ({ id: 'test-id', email: 'test@example.com', name: 'Test User' })),
  }
})

import { api } from '@/lib/api'

function renderShell(initialPath = '/') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<div>Home Page</div>} />
          <Route path="/workflows" element={<div>Workflows Page</div>} />
          <Route path="/calls" element={<div>Calls Page</div>} />
          <Route path="/calls/live" element={<div>Live Calls Page</div>} />
          <Route path="/settings/phone-numbers" element={<div>Phone Numbers Page</div>} />
          <Route path="/settings/integrations" element={<div>Integrations Page</div>} />
          <Route path="/setup" element={<div>Setup Page</div>} />
          <Route path="*" element={<div>404 Page</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('AppShell', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(api.auth.configWarnings as ReturnType<typeof vi.fn>).mockResolvedValue({ warnings: [] })
  })

  it('renders the Pronto logo linking to home', () => {
    renderShell()
    const logo = screen.getByTestId('nav-home')
    expect(logo).toHaveTextContent('Pronto')
    expect(logo).toHaveAttribute('href', '/')
  })

  it('renders all top-level nav links', () => {
    renderShell()
    const nav = screen.getByTestId('app-nav')
    expect(within(nav).getByTestId('nav-workflows')).toHaveAttribute('href', '/workflows')
    expect(within(nav).getByTestId('nav-calls')).toHaveAttribute('href', '/calls')
    expect(within(nav).getByTestId('nav-live-calls')).toHaveAttribute('href', '/calls/live')
    expect(within(nav).getByTestId('nav-phone-numbers')).toHaveAttribute('href', '/settings/phone-numbers')
    expect(within(nav).getByTestId('nav-integrations')).toHaveAttribute('href', '/settings/integrations')
  })

  it('renders setup gear icon and sign-out button', () => {
    renderShell()
    expect(screen.getByTestId('nav-setup')).toHaveAttribute('href', '/setup')
    expect(screen.getByTestId('nav-signout')).toBeInTheDocument()
  })

  it('highlights the active nav link', () => {
    renderShell('/workflows')
    const workflowsLink = screen.getByTestId('nav-workflows')
    expect(workflowsLink.className).toContain('text-white')
    // Other links should not have active class
    const callsLink = screen.getByTestId('nav-calls')
    expect(callsLink.className).not.toContain('text-white')
  })

  it('renders child route content via Outlet', () => {
    renderShell('/workflows')
    expect(screen.getByText('Workflows Page')).toBeInTheDocument()
  })

  it('navigates when nav links are clicked', async () => {
    const user = userEvent.setup()
    renderShell('/')
    expect(screen.getByText('Home Page')).toBeInTheDocument()

    await user.click(screen.getByTestId('nav-workflows'))
    expect(screen.getByText('Workflows Page')).toBeInTheDocument()

    await user.click(screen.getByTestId('nav-calls'))
    expect(screen.getByText('Calls Page')).toBeInTheDocument()
  })

  it('shows config warning banners', async () => {
    ;(api.auth.configWarnings as ReturnType<typeof vi.fn>).mockResolvedValue({
      warnings: ['No fallback phone number configured'],
    })
    renderShell()
    const banner = await screen.findByTestId('config-warnings')
    expect(banner).toHaveTextContent('No fallback phone number configured')
  })

  it('does not show warnings when there are none', () => {
    renderShell()
    expect(screen.queryByTestId('config-warnings')).not.toBeInTheDocument()
  })
})

describe('404 page', () => {
  it('renders for unknown routes', () => {
    renderShell('/some/unknown/path')
    expect(screen.getByText('404 Page')).toBeInTheDocument()
  })
})
