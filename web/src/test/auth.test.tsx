/** Unit tests for login page, auth guard, and auth token store. */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

// Mock the API module
vi.mock('@/lib/api', () => ({
  api: {
    auth: {
      login: vi.fn(),
      check: vi.fn(),
    },
  },
}))

// Mock the auth store — keep real functions but spy on them
vi.mock('@/lib/auth', async () => {
  let token: string | null = null
  return {
    getToken: vi.fn(() => token),
    setToken: vi.fn((t: string) => {
      token = t
    }),
    clearToken: vi.fn(() => {
      token = null
    }),
    isAuthenticated: vi.fn(() => !!token),
  }
})

import { api } from '@/lib/api'
import { isAuthenticated, setToken, clearToken } from '@/lib/auth'
import Login from '@/pages/Login'
import AuthGuard from '@/components/AuthGuard'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<div>Home Page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

function renderProtected(initialEntries = ['/']) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Routes>
        <Route
          path="/"
          element={
            <AuthGuard>
              <div>Protected Content</div>
            </AuthGuard>
          }
        />
        <Route path="/login" element={<div>Login Page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

// ---------------------------------------------------------------------------
// Login page
// ---------------------------------------------------------------------------

describe('Login', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(clearToken as ReturnType<typeof vi.fn>)()
  })

  it('renders the login form', () => {
    renderLogin()
    expect(screen.getByText('CallMe')).toBeInTheDocument()
    expect(screen.getByLabelText('API Key')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  it('disables button when input is empty', () => {
    renderLogin()
    expect(screen.getByRole('button', { name: /sign in/i })).toBeDisabled()
  })

  it('navigates to / on successful login', async () => {
    const user = userEvent.setup()
    ;(api.auth.login as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      token: 'test-token-123',
    })

    renderLogin()
    await user.type(screen.getByLabelText('API Key'), 'my-secret-key')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(api.auth.login).toHaveBeenCalledWith('my-secret-key')
      expect(setToken).toHaveBeenCalledWith('test-token-123')
      expect(screen.getByText('Home Page')).toBeInTheDocument()
    })
  })

  it('shows error on invalid key', async () => {
    const user = userEvent.setup()
    ;(api.auth.login as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('Unauthorized'),
    )

    renderLogin()
    await user.type(screen.getByLabelText('API Key'), 'wrong-key')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByText('Invalid API key')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// AuthGuard
// ---------------------------------------------------------------------------

describe('AuthGuard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(clearToken as ReturnType<typeof vi.fn>)()
  })

  it('redirects to /login when not authenticated', () => {
    ;(isAuthenticated as ReturnType<typeof vi.fn>).mockReturnValue(false)
    renderProtected()
    expect(screen.getByText('Login Page')).toBeInTheDocument()
    expect(screen.queryByText('Protected Content')).not.toBeInTheDocument()
  })

  it('renders children when authenticated', () => {
    ;(isAuthenticated as ReturnType<typeof vi.fn>).mockReturnValue(true)
    renderProtected()
    expect(screen.getByText('Protected Content')).toBeInTheDocument()
    expect(screen.queryByText('Login Page')).not.toBeInTheDocument()
  })
})
