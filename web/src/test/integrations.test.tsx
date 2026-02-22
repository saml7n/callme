/** Unit tests for integration picker (ConfigPanel), ActionNode, Integrations page. */

import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

// Mock the API module — include all namespaces used across these tests
vi.mock('@/lib/api', () => ({
  api: {
    integrations: {
      list: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
      test: vi.fn(),
      oauthStart: vi.fn(),
    },
  },
}))

import { api } from '@/lib/api'
import Integrations from '@/pages/Integrations'
import ActionNode from '@/components/nodes/ActionNode'
import type { ActionNodeData } from '@/components/nodes/ActionNode'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const mockIntegrations = [
  {
    id: 'int-1',
    type: 'google_calendar' as const,
    name: 'Office Calendar',
    config_redacted: { client_id: 'abc***', calendar_id: 'primary' },
    created_at: '2024-06-01T10:00:00Z',
    updated_at: '2024-06-01T10:00:00Z',
  },
  {
    id: 'int-2',
    type: 'webhook' as const,
    name: 'Slack Hook',
    config_redacted: { url: 'https://hooks.slack.com/***' },
    created_at: '2024-06-02T10:00:00Z',
    updated_at: '2024-06-02T10:00:00Z',
  },
]

beforeEach(() => {
  vi.clearAllMocks()
})

// ===========================================================================
// Integrations settings page
// ===========================================================================

describe('Integrations settings page', () => {
  function renderPage() {
    return render(
      <MemoryRouter initialEntries={['/settings/integrations']}>
        <Routes>
          <Route path="/settings/integrations" element={<Integrations />} />
          <Route path="/" element={<div>Home</div>} />
        </Routes>
      </MemoryRouter>,
    )
  }

  it('shows empty state when no integrations exist', async () => {
    ;(api.integrations.list as Mock).mockResolvedValue([])
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('No integrations configured')).toBeInTheDocument()
    })
  })

  it('lists integrations with type labels', async () => {
    ;(api.integrations.list as Mock).mockResolvedValue(mockIntegrations)
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('Office Calendar')).toBeInTheDocument()
      expect(screen.getByText('Slack Hook')).toBeInTheDocument()
      expect(screen.getByText('Google Calendar')).toBeInTheDocument()
      expect(screen.getByText('Webhook')).toBeInTheDocument()
    })
  })

  it('shows test result badge on success', async () => {
    ;(api.integrations.list as Mock).mockResolvedValue(mockIntegrations)
    ;(api.integrations.test as Mock).mockResolvedValue({ success: true, detail: 'OK' })
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('Office Calendar')).toBeInTheDocument()
    })
    // Find the first Test button and click it
    const testButtons = screen.getAllByText('Test')
    await userEvent.click(testButtons[0])
    await waitFor(() => {
      expect(screen.getByText('✓ Connected')).toBeInTheDocument()
    })
  })

  it('shows test result badge on failure', async () => {
    ;(api.integrations.list as Mock).mockResolvedValue(mockIntegrations)
    ;(api.integrations.test as Mock).mockResolvedValue({ success: false, detail: 'Timeout' })
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('Slack Hook')).toBeInTheDocument()
    })
    const testButtons = screen.getAllByText('Test')
    await userEvent.click(testButtons[1])
    await waitFor(() => {
      expect(screen.getByText('✗ Timeout')).toBeInTheDocument()
    })
  })

  it('opens create dialog on add button click', async () => {
    ;(api.integrations.list as Mock).mockResolvedValue([])
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('No integrations configured')).toBeInTheDocument()
    })
    // There are two Add buttons (header + empty state)
    const addButtons = screen.getAllByText('+ Add Integration')
    await userEvent.click(addButtons[0])
    await waitFor(() => {
      expect(screen.getByText('New Integration')).toBeInTheDocument()
    })
  })

  it('calls delete with confirmation', async () => {
    ;(api.integrations.list as Mock).mockResolvedValue(mockIntegrations)
    ;(api.integrations.delete as Mock).mockResolvedValue({})
    // Mock confirm
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('Office Calendar')).toBeInTheDocument()
    })
    const deleteButtons = screen.getAllByText('Delete')
    await userEvent.click(deleteButtons[0])
    expect(window.confirm).toHaveBeenCalledWith('Delete this integration?')
    expect(api.integrations.delete).toHaveBeenCalledWith('int-1')
  })

  it('opens OAuth window for google_calendar', async () => {
    ;(api.integrations.list as Mock).mockResolvedValue(mockIntegrations)
    ;(api.integrations.oauthStart as Mock).mockResolvedValue({ url: 'https://accounts.google.com/oauth' })
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('Office Calendar')).toBeInTheDocument()
    })
    await userEvent.click(screen.getByText('OAuth'))
    await waitFor(() => {
      expect(openSpy).toHaveBeenCalledWith('https://accounts.google.com/oauth', '_blank')
    })
  })
})

// ===========================================================================
// ActionNode integration rendering
// ===========================================================================

describe('ActionNode – integration rendering', () => {
  // We need to mock React Flow context for Handle components
  vi.mock('@xyflow/react', async () => {
    const actual = await vi.importActual<typeof import('@xyflow/react')>('@xyflow/react')
    return {
      ...actual,
      Handle: ({ type, position }: { type: string; position: string }) => (
        <div data-testid={`handle-${type}`} data-position={position} />
      ),
    }
  })

  const baseProps = {
    id: 'action_1',
    type: 'action' as const,
    selected: false,
    zIndex: 0,
    isConnectable: true,
    positionAbsoluteX: 0,
    positionAbsoluteY: 0,
    dragging: false,
    deletable: true,
    selectable: true,
    parentId: undefined,
    sourcePosition: undefined,
    targetPosition: undefined,
    dragHandle: undefined,
    width: 256,
    height: 100,
    measured: { width: 256, height: 100 },
  }

  it('shows integration preview with icon and action', () => {
    const data: ActionNodeData = {
      label: 'Book',
      action_type: 'integration',
      integration_id: 'int-1',
      integration_name: 'Office Calendar',
      integration_type: 'google_calendar',
      integration_action: 'book_appointment',
    }
    const { container } = render(<ActionNode data={data} {...baseProps} />)
    expect(screen.getByText(/📅 Google Calendar → Book Appointment/)).toBeInTheDocument()
    // Should have source handle (integration nodes are not terminal)
    const sourceHandle = container.querySelector('[data-testid="handle-source"]')
    expect(sourceHandle).toBeInTheDocument()
  })

  it('shows "No integration selected" when no integration chosen', () => {
    const data: ActionNodeData = {
      label: 'Action',
      action_type: 'integration',
    }
    render(<ActionNode data={data} {...baseProps} />)
    expect(screen.getByText('No integration selected')).toBeInTheDocument()
  })

  it('shows warning badge when integration is missing', () => {
    const data: ActionNodeData = {
      label: 'Bad Action',
      action_type: 'integration',
      integration_id: 'int-deleted',
      integration_name: 'Deleted Calendar',
      integration_type: 'google_calendar',
      integration_action: 'book_appointment',
      integration_missing: true,
    }
    render(<ActionNode data={data} {...baseProps} />)
    expect(screen.getByText('⚠ Integration deleted')).toBeInTheDocument()
  })

  it('shows webhook icon for webhook integration', () => {
    const data: ActionNodeData = {
      label: 'Notify',
      action_type: 'integration',
      integration_id: 'int-2',
      integration_name: 'Slack Hook',
      integration_type: 'webhook',
      integration_action: 'call_webhook',
    }
    render(<ActionNode data={data} {...baseProps} />)
    expect(screen.getByText(/🔗 Webhook → Call Webhook/)).toBeInTheDocument()
  })

  it('does not show source handle for end_call type', () => {
    const data: ActionNodeData = {
      label: 'End',
      action_type: 'end_call',
      message: 'Goodbye',
    }
    const { container } = render(<ActionNode data={data} {...baseProps} />)
    const sourceHandle = container.querySelector('[data-testid="handle-source"]')
    expect(sourceHandle).toBeNull()
  })
})
