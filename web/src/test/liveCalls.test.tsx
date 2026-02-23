/** Unit tests for Live Calls page. */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'

// ── Mock API ──
vi.mock('@/lib/api', () => ({
  api: {
    calls: {
      live: vi.fn().mockResolvedValue([]),
      transfer: vi.fn().mockResolvedValue({ status: 'transferred' }),
    },
  },
}))

vi.mock('@/lib/auth', () => ({
  getToken: vi.fn().mockReturnValue('test-token'),
  isAuthenticated: vi.fn().mockReturnValue(true),
  clearToken: vi.fn(),
}))

import { api } from '@/lib/api'
import LiveCalls from '@/pages/LiveCalls'

// ── WebSocket mock ──
type WsHandler = ((ev: { data: string }) => void) | null

let mockWsInstances: MockWebSocket[] = []

class MockWebSocket {
  url: string
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: WsHandler = null
  readyState = 1
  close = vi.fn()

  constructor(url: string) {
    this.url = url
    mockWsInstances.push(this)
    // Fire onopen on next tick
    setTimeout(() => this.onopen?.(), 0)
  }

  /** Helper to simulate the server pushing a message */
  simulateMessage(data: object) {
    this.onmessage?.({ data: JSON.stringify(data) })
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockWsInstances = []
  vi.stubGlobal('WebSocket', MockWebSocket)
  // Suppress Notification API
  vi.stubGlobal('Notification', { permission: 'denied', requestPermission: vi.fn() })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/calls/live']}>
      <LiveCalls />
    </MemoryRouter>,
  )

// ── Tests ──

describe('LiveCalls page', () => {
  it('shows empty state when no calls', async () => {
    renderPage()
    expect(screen.getByTestId('empty-state')).toBeInTheDocument()
    expect(screen.getByText('No active calls')).toBeInTheDocument()
  })

  it('connects to WebSocket with token', async () => {
    renderPage()
    await waitFor(() => expect(mockWsInstances.length).toBe(1))
    expect(mockWsInstances[0].url).toContain('/ws/calls/live')
    expect(mockWsInstances[0].url).toContain('token=test-token')
  })

  it('shows connected badge after WebSocket opens', async () => {
    renderPage()
    await waitFor(() => expect(mockWsInstances.length).toBe(1))
    // Trigger onopen
    await act(async () => {
      mockWsInstances[0].onopen?.()
    })
    expect(screen.getByText('Connected')).toBeInTheDocument()
  })

  it('renders a call card when snapshot has active calls', async () => {
    renderPage()
    await waitFor(() => expect(mockWsInstances.length).toBe(1))
    const ws = mockWsInstances[0]

    await act(async () => {
      ws.onopen?.()
      ws.simulateMessage({
        type: 'snapshot',
        calls: [
          {
            call_id: 'c1',
            call_sid: 'CS1',
            caller_number: '+447700900123',
            workflow_name: 'Reception',
            started_at: Date.now() / 1000 - 60,
          },
        ],
      })
    })

    expect(screen.getByTestId('live-call-card')).toBeInTheDocument()
    expect(screen.getByText('Reception')).toBeInTheDocument()
  })

  it('renders new call from call_started event', async () => {
    renderPage()
    await waitFor(() => expect(mockWsInstances.length).toBe(1))
    const ws = mockWsInstances[0]

    await act(async () => {
      ws.onopen?.()
      ws.simulateMessage({ type: 'snapshot', calls: [] })
      ws.simulateMessage({
        type: 'call_started',
        call_id: 'c2',
        caller_number: '+15551234567',
        workflow_name: 'Sales',
        timestamp: Date.now() / 1000,
      })
    })

    expect(screen.getByTestId('live-call-card')).toBeInTheDocument()
    expect(screen.getByText('Sales')).toBeInTheDocument()
  })

  it('adds transcript messages to the call', async () => {
    renderPage()
    await waitFor(() => expect(mockWsInstances.length).toBe(1))
    const ws = mockWsInstances[0]

    await act(async () => {
      ws.onopen?.()
      ws.simulateMessage({
        type: 'snapshot',
        calls: [
          {
            call_id: 'c1',
            call_sid: 'CS1',
            caller_number: '+447700900123',
            workflow_name: 'Reception',
            started_at: Date.now() / 1000,
          },
        ],
      })
      ws.simulateMessage({
        type: 'transcript',
        call_id: 'c1',
        role: 'caller',
        text: 'Hello there',
        timestamp: Date.now() / 1000,
      })
      ws.simulateMessage({
        type: 'transcript',
        call_id: 'c1',
        role: 'ai',
        text: 'Hi! How can I help?',
        timestamp: Date.now() / 1000,
      })
    })

    expect(screen.getByTestId('msg-caller')).toHaveTextContent('Hello there')
    expect(screen.getByTestId('msg-ai')).toHaveTextContent('Hi! How can I help?')
  })

  it('marks call as ended and shows view call log link', async () => {
    renderPage()
    await waitFor(() => expect(mockWsInstances.length).toBe(1))
    const ws = mockWsInstances[0]

    await act(async () => {
      ws.onopen?.()
      ws.simulateMessage({
        type: 'snapshot',
        calls: [
          {
            call_id: 'c1',
            call_sid: 'CS1',
            caller_number: '+447700900123',
            workflow_name: 'Test',
            started_at: Date.now() / 1000,
          },
        ],
      })
    })

    expect(screen.getByTestId('live-call-card')).toBeInTheDocument()

    await act(async () => {
      ws.simulateMessage({ type: 'call_ended', call_id: 'c1', timestamp: Date.now() / 1000 })
    })

    // Active call card goes away, ended state appears
    expect(screen.queryByTestId('live-call-card')).not.toBeInTheDocument()
    expect(screen.getByTestId('ended-call')).toBeInTheDocument()
    expect(screen.getByText('View call log')).toBeInTheDocument()
  })

  it('calls transfer API when transfer button clicked', async () => {
    const user = userEvent.setup()
    renderPage()
    await waitFor(() => expect(mockWsInstances.length).toBe(1))
    const ws = mockWsInstances[0]

    await act(async () => {
      ws.onopen?.()
      ws.simulateMessage({
        type: 'snapshot',
        calls: [
          {
            call_id: 'c1',
            call_sid: 'CS1',
            caller_number: '+15551234567',
            workflow_name: 'W',
            started_at: Date.now() / 1000,
          },
        ],
      })
    })

    const transferBtn = screen.getByTestId('transfer-btn')
    expect(transferBtn).toBeInTheDocument()

    await user.click(transferBtn)

    await waitFor(() => {
      expect(api.calls.transfer).toHaveBeenCalledWith('c1')
    })
  })

  it('shows transferred badge after transfer_started event', async () => {
    renderPage()
    await waitFor(() => expect(mockWsInstances.length).toBe(1))
    const ws = mockWsInstances[0]

    await act(async () => {
      ws.onopen?.()
      ws.simulateMessage({
        type: 'snapshot',
        calls: [
          {
            call_id: 'c1',
            call_sid: 'CS1',
            caller_number: '+15551234567',
            workflow_name: 'W',
            started_at: Date.now() / 1000,
          },
        ],
      })
    })

    expect(screen.getByText('AI Active')).toBeInTheDocument()

    await act(async () => {
      ws.simulateMessage({ type: 'transfer_started', call_id: 'c1', timestamp: Date.now() / 1000 })
    })

    expect(screen.getByText('Transferred')).toBeInTheDocument()
    // Transfer button should disappear
    expect(screen.queryByTestId('transfer-btn')).not.toBeInTheDocument()
  })

  it('masks phone number in call card', async () => {
    renderPage()
    await waitFor(() => expect(mockWsInstances.length).toBe(1))
    const ws = mockWsInstances[0]

    await act(async () => {
      ws.onopen?.()
      ws.simulateMessage({
        type: 'snapshot',
        calls: [
          {
            call_id: 'c1',
            call_sid: 'CS1',
            caller_number: '+447700900123',
            workflow_name: 'R',
            started_at: Date.now() / 1000,
          },
        ],
      })
    })

    const callerEl = screen.getByTestId('caller-number')
    // Should show masked: first 3 + bullets + last 3
    expect(callerEl.textContent).toMatch(/^\+44.*123$/)
    expect(callerEl.textContent).toContain('•')
  })

  it('has navigation links to Call Log and Workflows', () => {
    renderPage()
    expect(screen.getByText('Call Log')).toBeInTheDocument()
    expect(screen.getByText('Workflows')).toBeInTheDocument()
  })
})
