/** Unit tests for Call List and Call Detail pages. */

import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

// Mock the API module
vi.mock('@/lib/api', () => ({
  api: {
    calls: {
      list: vi.fn(),
      get: vi.fn(),
    },
  },
}))

import { api } from '@/lib/api'
import CallList from '@/pages/CallList'
import CallDetail from '@/pages/CallDetail'

const mockCalls = [
  {
    id: '111',
    call_sid: 'CA111',
    from_number: '+447700900123',
    to_number: '+441234567890',
    workflow_id: 'wf-1',
    workflow_name: 'Reception',
    started_at: '2024-06-01T10:00:00Z',
    ended_at: '2024-06-01T10:05:00Z',
    duration_seconds: 300,
    status: 'completed',
  },
  {
    id: '222',
    call_sid: 'CA222',
    from_number: '+15551234567',
    to_number: '+441234567890',
    workflow_id: null,
    workflow_name: null,
    started_at: '2024-06-01T09:00:00Z',
    ended_at: null,
    duration_seconds: null,
    status: 'in_progress',
  },
]

const mockCallDetail = {
  ...mockCalls[0],
  events: [
    {
      id: 'e1',
      timestamp: '2024-06-01T10:00:01Z',
      event_type: 'transcript',
      data_json: { text: 'Hello, I need to book an appointment.' },
    },
    {
      id: 'e2',
      timestamp: '2024-06-01T10:00:03Z',
      event_type: 'llm_response',
      data_json: { text: 'Of course! Let me help you with that.' },
    },
    {
      id: 'e3',
      timestamp: '2024-06-01T10:00:05Z',
      event_type: 'node_transition',
      data_json: { node_id: 'booking' },
    },
    {
      id: 'e4',
      timestamp: '2024-06-01T10:00:10Z',
      event_type: 'summary_generated',
      data_json: { summary: 'Caller booked an appointment for Tuesday.' },
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// CallList
// ---------------------------------------------------------------------------

describe('CallList', () => {
  it('renders call rows with masked phone numbers', async () => {
    ;(api.calls.list as Mock).mockResolvedValue(mockCalls)

    render(
      <MemoryRouter initialEntries={['/calls']}>
        <Routes>
          <Route path="/calls" element={<CallList />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getAllByTestId('call-row')).toHaveLength(2)
    })

    // Phone number should be masked — last 4 visible
    expect(screen.getByText(/\*.*0123/)).toBeTruthy()
    // Workflow name
    expect(screen.getByText('Reception')).toBeTruthy()
    // Status badge
    expect(screen.getByText('completed')).toBeTruthy()
    expect(screen.getByText('in progress')).toBeTruthy()
  })

  it('shows empty state when no calls', async () => {
    ;(api.calls.list as Mock).mockResolvedValue([])

    render(
      <MemoryRouter initialEntries={['/calls']}>
        <Routes>
          <Route path="/calls" element={<CallList />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('No calls yet')).toBeTruthy()
    })
  })

  it('shows error state on API failure', async () => {
    ;(api.calls.list as Mock).mockRejectedValue(new Error('500: Server Error'))

    render(
      <MemoryRouter initialEntries={['/calls']}>
        <Routes>
          <Route path="/calls" element={<CallList />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('500: Server Error')).toBeTruthy()
    })
  })

  it('navigates to call detail on row click', async () => {
    ;(api.calls.list as Mock).mockResolvedValue([mockCalls[0]])
    ;(api.calls.get as Mock).mockResolvedValue(mockCallDetail)
    const user = userEvent.setup()

    render(
      <MemoryRouter initialEntries={['/calls']}>
        <Routes>
          <Route path="/calls" element={<CallList />} />
          <Route path="/calls/:id" element={<CallDetail />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('call-row')).toBeTruthy()
    })

    await user.click(screen.getByTestId('call-row'))

    await waitFor(() => {
      // Detail page should render the caller
      expect(screen.getByText(/\+447700900123/)).toBeTruthy()
    })
  })
})

// ---------------------------------------------------------------------------
// CallDetail
// ---------------------------------------------------------------------------

describe('CallDetail', () => {
  it('renders call metadata and transcript', async () => {
    ;(api.calls.get as Mock).mockResolvedValue(mockCallDetail)

    render(
      <MemoryRouter initialEntries={['/calls/111']}>
        <Routes>
          <Route path="/calls/:id" element={<CallDetail />} />
        </Routes>
      </MemoryRouter>,
    )

    // Wait for metadata
    await waitFor(() => {
      expect(screen.getByText(/\+447700900123/)).toBeTruthy()
    })

    // Workflow name
    expect(screen.getByText('Reception')).toBeTruthy()
    // Status badge
    expect(screen.getByText('completed')).toBeTruthy()
    // Transcript bubbles
    expect(screen.getByText('Hello, I need to book an appointment.')).toBeTruthy()
    expect(screen.getByText('Of course! Let me help you with that.')).toBeTruthy()
    // Node transition
    expect(screen.getByText('booking')).toBeTruthy()
    // Summary
    expect(screen.getByText('Caller booked an appointment for Tuesday.')).toBeTruthy()
  })

  it('shows error on 404', async () => {
    ;(api.calls.get as Mock).mockRejectedValue(new Error('404: Call not found'))

    render(
      <MemoryRouter initialEntries={['/calls/bad-id']}>
        <Routes>
          <Route path="/calls/:id" element={<CallDetail />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('404: Call not found')).toBeTruthy()
    })
  })

  it('shows empty events message when no events', async () => {
    ;(api.calls.get as Mock).mockResolvedValue({ ...mockCallDetail, events: [] })

    render(
      <MemoryRouter initialEntries={['/calls/111']}>
        <Routes>
          <Route path="/calls/:id" element={<CallDetail />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('No events recorded for this call.')).toBeTruthy()
    })
  })
})
