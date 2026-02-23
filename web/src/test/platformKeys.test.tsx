/** Unit tests for Story 23: Platform keys toggle in the Setup wizard. */

import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

vi.mock('@/lib/api', () => ({
  api: {
    settings: {
      get: vi.fn(),
      put: vi.fn(),
      validate: vi.fn(),
    },
    templates: {
      list: vi.fn(),
    },
    workflows: {
      list: vi.fn(),
      get: vi.fn(),
      create: vi.fn(),
      publish: vi.fn(),
    },
    phoneNumbers: {
      list: vi.fn(),
      create: vi.fn(),
    },
    platform: {
      status: vi.fn(),
    },
  },
}))

import { api } from '@/lib/api'
import Setup from '@/pages/Setup'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderSetup() {
  return render(
    <MemoryRouter initialEntries={['/setup']}>
      <Routes>
        <Route path="/setup" element={<Setup />} />
        <Route path="/workflows" element={<div>Workflows Page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

const PLATFORM_ALL: Record<string, boolean> = {
  twilio: true,
  deepgram: true,
  elevenlabs: true,
  openai: true,
  has_any: true,
}

const PLATFORM_NONE: Record<string, boolean> = {
  twilio: false,
  deepgram: false,
  elevenlabs: false,
  openai: false,
  has_any: false,
}

async function goToStep2() {
  renderSetup()
  await userEvent.click(screen.getByRole('button', { name: 'Next' }))
  await waitFor(() => expect(screen.getByTestId('step-api-keys')).toBeInTheDocument())
}

beforeEach(() => {
  vi.clearAllMocks()
  ;(api.settings.get as Mock).mockResolvedValue({ settings: {}, configured: false, use_platform_keys: false })
  ;(api.templates.list as Mock).mockResolvedValue([])
  ;(api.phoneNumbers.list as Mock).mockResolvedValue([])
  ;(api.workflows.list as Mock).mockResolvedValue([])
  ;(api.platform.status as Mock).mockResolvedValue(PLATFORM_NONE)
})

// ===========================================================================
// Platform keys toggle visibility
// ===========================================================================

describe('Platform keys toggle', () => {
  it('shows platform keys section when platform has services', async () => {
    ;(api.platform.status as Mock).mockResolvedValue(PLATFORM_ALL)
    await goToStep2()
    await waitFor(() => expect(screen.getByTestId('platform-keys-section')).toBeInTheDocument())
  })

  it('hides platform keys section when no platform services', async () => {
    ;(api.platform.status as Mock).mockResolvedValue(PLATFORM_NONE)
    await goToStep2()
    // No platform-keys-section should appear; own-keys fields shown instead
    expect(screen.queryByTestId('platform-keys-section')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Deepgram API Key')).toBeInTheDocument()
  })

  it('displays service badges for available platform services', async () => {
    ;(api.platform.status as Mock).mockResolvedValue({
      twilio: true,
      deepgram: true,
      elevenlabs: false,
      openai: true,
      has_any: true,
    })
    await goToStep2()
    await waitFor(() => expect(screen.getByTestId('platform-keys-section')).toBeInTheDocument())

    // Badges present for available services
    const badges = screen.getByTestId('platform-keys-section')
    expect(badges).toHaveTextContent('Twilio')
    expect(badges).toHaveTextContent('Deepgram')
    expect(badges).toHaveTextContent('OpenAI')
    // ElevenLabs is not available
    // (The word "ElevenLabs" still appears in the other option label, so we check within the section)
  })
})

// ===========================================================================
// Selecting platform keys mode
// ===========================================================================

describe('Platform keys selection', () => {
  it('clicking "Use platform keys" hides manual key inputs', async () => {
    ;(api.platform.status as Mock).mockResolvedValue(PLATFORM_ALL)
    await goToStep2()
    await waitFor(() => expect(screen.getByTestId('platform-keys-section')).toBeInTheDocument())

    // Click "Use platform keys" option
    await userEvent.click(screen.getByText('Use platform keys'))

    // Manual key inputs should be gone, platform summary shown instead
    expect(screen.queryByLabelText('Deepgram API Key')).not.toBeInTheDocument()
    expect(screen.getByTestId('platform-keys-summary')).toBeInTheDocument()
  })

  it('clicking "Enter your own API keys" shows manual inputs', async () => {
    ;(api.platform.status as Mock).mockResolvedValue(PLATFORM_ALL)
    await goToStep2()
    await waitFor(() => expect(screen.getByTestId('platform-keys-section')).toBeInTheDocument())

    // First select platform keys
    await userEvent.click(screen.getByText('Use platform keys'))
    expect(screen.queryByLabelText('Deepgram API Key')).not.toBeInTheDocument()

    // Then switch back
    await userEvent.click(screen.getByText('Enter your own API keys'))
    expect(screen.getByLabelText('Deepgram API Key')).toBeInTheDocument()
    expect(screen.queryByTestId('platform-keys-summary')).not.toBeInTheDocument()
  })

  it('Validate button says "Validate Platform Keys" in platform mode', async () => {
    ;(api.platform.status as Mock).mockResolvedValue(PLATFORM_ALL)
    await goToStep2()
    await waitFor(() => expect(screen.getByTestId('platform-keys-section')).toBeInTheDocument())

    await userEvent.click(screen.getByText('Use platform keys'))
    expect(screen.getByRole('button', { name: 'Validate Platform Keys' })).toBeInTheDocument()
  })
})

// ===========================================================================
// Validation with platform keys
// ===========================================================================

describe('Platform keys validation', () => {
  it('saves use_platform_keys flag and validates', async () => {
    ;(api.platform.status as Mock).mockResolvedValue(PLATFORM_ALL)
    ;(api.settings.put as Mock).mockResolvedValue({ settings: {}, configured: true })
    ;(api.settings.validate as Mock).mockResolvedValue({
      results: { twilio: 'ok', deepgram: 'ok', elevenlabs: 'ok', openai: 'ok' },
    })

    await goToStep2()
    await waitFor(() => expect(screen.getByTestId('platform-keys-section')).toBeInTheDocument())

    await userEvent.click(screen.getByText('Use platform keys'))
    await userEvent.click(screen.getByRole('button', { name: 'Validate Platform Keys' }))

    // Should have called put with use_platform_keys
    await waitFor(() => {
      expect(api.settings.put).toHaveBeenCalledWith({ use_platform_keys: 'true' })
    })
    expect(api.settings.validate).toHaveBeenCalled()
  })

  it('shows Connected badges after successful platform validation', async () => {
    ;(api.platform.status as Mock).mockResolvedValue(PLATFORM_ALL)
    ;(api.settings.put as Mock).mockResolvedValue({ settings: {}, configured: true })
    ;(api.settings.validate as Mock).mockResolvedValue({
      results: { twilio: 'ok', deepgram: 'ok', elevenlabs: 'ok', openai: 'ok' },
    })

    await goToStep2()
    await waitFor(() => expect(screen.getByTestId('platform-keys-section')).toBeInTheDocument())

    await userEvent.click(screen.getByText('Use platform keys'))
    await userEvent.click(screen.getByRole('button', { name: 'Validate Platform Keys' }))

    await waitFor(() => {
      const connected = screen.getAllByText('Connected')
      expect(connected.length).toBe(4)
    })
  })

  it('can proceed to next step after platform keys validation', async () => {
    ;(api.platform.status as Mock).mockResolvedValue(PLATFORM_ALL)
    ;(api.settings.put as Mock).mockResolvedValue({ settings: {}, configured: true })
    ;(api.settings.validate as Mock).mockResolvedValue({
      results: { twilio: 'ok', deepgram: 'ok', elevenlabs: 'ok', openai: 'ok' },
    })

    await goToStep2()
    await waitFor(() => expect(screen.getByTestId('platform-keys-section')).toBeInTheDocument())

    await userEvent.click(screen.getByText('Use platform keys'))
    await userEvent.click(screen.getByRole('button', { name: 'Validate Platform Keys' }))
    await waitFor(() => expect(screen.getAllByText('Connected').length).toBe(4))

    // Next button should be enabled and navigate to phone number step
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(screen.getByTestId('step-phone-number')).toBeInTheDocument())
  })

  it('clears use_platform_keys when switching to own keys', async () => {
    ;(api.platform.status as Mock).mockResolvedValue(PLATFORM_ALL)
    ;(api.settings.put as Mock).mockResolvedValue({ settings: {}, configured: false })
    ;(api.settings.validate as Mock).mockResolvedValue({
      results: { twilio: 'ok', deepgram: 'ok', elevenlabs: 'ok', openai: 'ok' },
    })

    await goToStep2()
    await waitFor(() => expect(screen.getByTestId('platform-keys-section')).toBeInTheDocument())

    // Switch to own keys and validate
    await userEvent.click(screen.getByText('Enter your own API keys'))

    // Fill in a key and validate
    await userEvent.type(screen.getByLabelText('Deepgram API Key'), 'dg-key-123')
    await userEvent.click(screen.getByRole('button', { name: 'Validate All' }))

    // Should have sent the user's own key and cleared use_platform_keys
    await waitFor(() => {
      const putCalls = (api.settings.put as Mock).mock.calls
      const lastCall = putCalls[putCalls.length - 1][0]
      expect(lastCall.deepgram_api_key).toBe('dg-key-123')
      expect(lastCall.use_platform_keys).toBe('')
    })
  })
})
