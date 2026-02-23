/** Unit tests for LiveCallBanner and useLiveCallCount hook. */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

// Mock API
vi.mock('@/lib/api', () => ({
  api: {
    calls: {
      liveCount: vi.fn().mockResolvedValue({ count: 0 }),
    },
    auth: {
      configWarnings: vi.fn().mockResolvedValue({ warnings: [] }),
    },
  },
}))

vi.mock('@/lib/auth', () => ({
  getToken: vi.fn(() => 'test-token'),
  setToken: vi.fn(),
  clearToken: vi.fn(),
  isAuthenticated: vi.fn(() => true),
}))

import { api } from '@/lib/api'
import LiveCallBanner from '@/components/LiveCallBanner'

function renderBanner() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route
          path="/"
          element={
            <>
              <LiveCallBanner />
              <div>Home</div>
            </>
          }
        />
        <Route path="/calls/live" element={<div>Live Calls Page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('LiveCallBanner', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders nothing when count is 0', async () => {
    ;(api.calls.liveCount as ReturnType<typeof vi.fn>).mockResolvedValue({ count: 0 })
    renderBanner()

    // Wait for the initial fetch to resolve
    await waitFor(() => {
      expect(api.calls.liveCount).toHaveBeenCalled()
    })

    // Banner should not appear
    expect(screen.queryByTestId('live-call-banner')).not.toBeInTheDocument()
  })

  it('renders "1 live call" when count is 1', async () => {
    ;(api.calls.liveCount as ReturnType<typeof vi.fn>).mockResolvedValue({ count: 1 })
    renderBanner()

    const banner = await screen.findByTestId('live-call-banner')
    expect(banner).toHaveTextContent('1 live call')
    // Should NOT say "calls" (plural)
    expect(banner.textContent).not.toContain('calls')
  })

  it('renders "3 live calls" when count is 3', async () => {
    ;(api.calls.liveCount as ReturnType<typeof vi.fn>).mockResolvedValue({ count: 3 })
    renderBanner()

    const banner = await screen.findByTestId('live-call-banner')
    expect(banner).toHaveTextContent('3 live calls')
  })

  it('navigates to /calls/live when clicked', async () => {
    ;(api.calls.liveCount as ReturnType<typeof vi.fn>).mockResolvedValue({ count: 2 })
    const user = userEvent.setup()
    renderBanner()

    const banner = await screen.findByTestId('live-call-banner')
    await user.click(banner)
    expect(screen.getByText('Live Calls Page')).toBeInTheDocument()
  })

  it('has aria-live="polite" for accessibility', async () => {
    ;(api.calls.liveCount as ReturnType<typeof vi.fn>).mockResolvedValue({ count: 1 })
    renderBanner()

    const banner = await screen.findByTestId('live-call-banner')
    expect(banner).toHaveAttribute('aria-live', 'polite')
  })

  it('has the correct link href', async () => {
    ;(api.calls.liveCount as ReturnType<typeof vi.fn>).mockResolvedValue({ count: 2 })
    renderBanner()

    const banner = await screen.findByTestId('live-call-banner')
    expect(banner).toHaveAttribute('href', '/calls/live')
  })

  it('shows pulsing indicator dot', async () => {
    ;(api.calls.liveCount as ReturnType<typeof vi.fn>).mockResolvedValue({ count: 1 })
    renderBanner()

    const banner = await screen.findByTestId('live-call-banner')
    // The banner contains an animated ping dot
    const dots = banner.querySelectorAll('.animate-ping')
    expect(dots.length).toBe(1)
  })
})
