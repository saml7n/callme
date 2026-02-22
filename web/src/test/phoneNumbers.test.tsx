/** Unit tests for Phone Numbers settings page (Story 14). */

import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

// Mock the API module
vi.mock('@/lib/api', () => ({
  api: {
    phoneNumbers: {
      list: vi.fn(),
      create: vi.fn(),
      delete: vi.fn(),
    },
  },
}))

import { api } from '@/lib/api'
import PhoneNumbers from '@/pages/PhoneNumbers'

const mockPhones = [
  {
    id: 'ph-1',
    number: '+441234567890',
    label: 'Main Office',
    workflow_id: 'wf-1',
    workflow_name: 'Dental Reception',
    updated_at: '2024-06-01T10:00:00Z',
  },
  {
    id: 'ph-2',
    number: '+15551234567',
    label: 'US Line',
    workflow_id: null,
    workflow_name: null,
    updated_at: '2024-06-01T09:00:00Z',
  },
]

beforeEach(() => {
  vi.clearAllMocks()
})

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/settings/phone-numbers']}>
      <Routes>
        <Route path="/settings/phone-numbers" element={<PhoneNumbers />} />
      </Routes>
    </MemoryRouter>,
  )
}

// ---------------------------------------------------------------------------
// Phone Number List
// ---------------------------------------------------------------------------

describe('PhoneNumbers page', () => {
  it('renders phone number rows with status badges', async () => {
    ;(api.phoneNumbers.list as Mock).mockResolvedValue(mockPhones)

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('+441234567890')).toBeTruthy()
      expect(screen.getByText('+15551234567')).toBeTruthy()
    })

    // Labels
    expect(screen.getByText('Main Office')).toBeTruthy()
    expect(screen.getByText('US Line')).toBeTruthy()

    // Status badges
    expect(screen.getByText('In use')).toBeTruthy()
    expect(screen.getByText('Available')).toBeTruthy()

    // Workflow name link for in-use number
    expect(screen.getByText('Dental Reception')).toBeTruthy()
  })

  it('shows empty state when no numbers', async () => {
    ;(api.phoneNumbers.list as Mock).mockResolvedValue([])

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('No phone numbers registered yet.')).toBeTruthy()
    })
  })

  it('adds a phone number via the form', async () => {
    ;(api.phoneNumbers.list as Mock).mockResolvedValue([])
    ;(api.phoneNumbers.create as Mock).mockResolvedValue({
      id: 'ph-new',
      number: '+44999',
      label: 'New Line',
      workflow_id: null,
      workflow_name: null,
      updated_at: '2024-06-01T12:00:00Z',
    })

    renderPage()
    const user = userEvent.setup()

    await waitFor(() => {
      expect(screen.getByPlaceholderText('+441234567890')).toBeTruthy()
    })

    await user.type(screen.getByPlaceholderText('+441234567890'), '+44999')
    await user.type(screen.getByPlaceholderText('Main Office'), 'New Line')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    await waitFor(() => {
      expect(api.phoneNumbers.create).toHaveBeenCalledWith('+44999', 'New Line')
    })

    // New number should appear in the list
    expect(screen.getByText('+44999')).toBeTruthy()
  })

  it('disables remove button for in-use numbers', async () => {
    ;(api.phoneNumbers.list as Mock).mockResolvedValue(mockPhones)

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('+441234567890')).toBeTruthy()
    })

    const removeButtons = screen.getAllByRole('button', { name: 'Remove' })
    // First number is in-use → disabled
    expect(removeButtons[0]).toBeDisabled()
    // Second number is available → enabled
    expect(removeButtons[1]).toBeEnabled()
  })

  it('navigates to workflow builder via workflow name link', async () => {
    ;(api.phoneNumbers.list as Mock).mockResolvedValue(mockPhones)

    renderPage()

    await waitFor(() => {
      const link = screen.getByText('Dental Reception')
      expect(link.closest('a')).toHaveAttribute('href', '/workflows/wf-1/edit')
    })
  })
})
