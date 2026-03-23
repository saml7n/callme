/** Unit tests for login page, register page, auth guard, and auth token store. */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

// Mock the API module
vi.mock('@/lib/api', () => ({
  api: {
    auth: {
      login: vi.fn(),
      loginWithKey: vi.fn(),
      register: vi.fn(),
      check: vi.fn(),
      me: vi.fn(),
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
    getUserInfo: vi.fn(() => null),
  }
})

import { api } from '@/lib/api'
import { isAuthenticated, setToken, clearToken } from '@/lib/auth'
import Login from '@/pages/Login'
import Register from '@/pages/Register'
import AuthGuard from '@/components/AuthGuard'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<div>Register Page</div>} />
        <Route path="/" element={<div>Home Page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

function renderRegister() {
  return render(
    <MemoryRouter initialEntries={['/register']}>
      <Routes>
        <Route path="/register" element={<Register />} />
        <Route path="/login" element={<div>Login Page</div>} />
        <Route path="/setup" element={<div>Setup Page</div>} />
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
    vi.mocked(clearToken)()
  })

  it('renders the email + password login form by default', () => {
    renderLogin()
    expect(screen.getByText('Pronto')).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  it('disables button when both fields are empty', () => {
    renderLogin()
    expect(screen.getByRole('button', { name: /sign in/i })).toBeDisabled()
  })

  it('navigates to / on successful email login', async () => {
    const user = userEvent.setup()
    ;(api.auth.login as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      token: 'jwt-token-123',
      user: { id: '1', email: 'test@x.com', name: 'Test' },
    })

    renderLogin()
    await user.type(screen.getByLabelText('Email'), 'test@x.com')
    await user.type(screen.getByLabelText('Password'), 'mypassword')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(api.auth.login).toHaveBeenCalledWith('test@x.com', 'mypassword')
      expect(setToken).toHaveBeenCalledWith('jwt-token-123')
      expect(screen.getByText('Home Page')).toBeInTheDocument()
    })
  })

  it('shows error on invalid credentials', async () => {
    const user = userEvent.setup()
    ;(api.auth.login as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('Unauthorized'),
    )

    renderLogin()
    await user.type(screen.getByLabelText('Email'), 'test@x.com')
    await user.type(screen.getByLabelText('Password'), 'wrong')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByText('Invalid email or password')).toBeInTheDocument()
    })
  })

  it('can toggle to API key mode and login', async () => {
    const user = userEvent.setup()
    ;(api.auth.loginWithKey as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      token: 'jwt-from-key',
    })

    renderLogin()
    await user.click(screen.getByText('Use API key instead'))
    expect(screen.getByLabelText('API Key')).toBeInTheDocument()

    await user.type(screen.getByLabelText('API Key'), 'my-api-key')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(api.auth.loginWithKey).toHaveBeenCalledWith('my-api-key')
      expect(setToken).toHaveBeenCalledWith('jwt-from-key')
      expect(screen.getByText('Home Page')).toBeInTheDocument()
    })
  })

  it('has a link to the register page', () => {
    renderLogin()
    expect(screen.getByText('Sign up')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Register page
// ---------------------------------------------------------------------------

describe('Register', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(clearToken)()
  })

  it('renders the registration form with invite code field', () => {
    renderRegister()
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByLabelText('Invite Code')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign up/i })).toBeInTheDocument()
  })

  it('navigates to /setup on successful registration', async () => {
    const user = userEvent.setup()
    ;(api.auth.register as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      token: 'jwt-new-user',
      user: { id: '2', email: 'new@x.com', name: 'New' },
    })

    renderRegister()
    await user.type(screen.getByLabelText('Email'), 'new@x.com')
    await user.type(screen.getByLabelText('Name'), 'New')
    await user.type(screen.getByLabelText('Password'), 'password123')
    await user.type(screen.getByLabelText('Invite Code'), 'welcome2026')
    await user.click(screen.getByRole('button', { name: /sign up/i }))

    await waitFor(() => {
      expect(api.auth.register).toHaveBeenCalledWith('new@x.com', 'password123', 'New', 'welcome2026')
      expect(setToken).toHaveBeenCalledWith('jwt-new-user')
      expect(screen.getByText('Setup Page')).toBeInTheDocument()
    })
  })

  it('shows error on failure', async () => {
    const user = userEvent.setup()
    ;(api.auth.register as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('Email already registered'),
    )

    renderRegister()
    await user.type(screen.getByLabelText('Email'), 'dup@x.com')
    await user.type(screen.getByLabelText('Password'), 'password123')
    await user.type(screen.getByLabelText('Invite Code'), 'code123')
    await user.click(screen.getByRole('button', { name: /sign up/i }))

    await waitFor(() => {
      expect(screen.getByTestId('register-error')).toBeInTheDocument()
    })
  })

  it('shows error for invalid invite code (403)', async () => {
    const user = userEvent.setup()
    ;(api.auth.register as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('403: Invalid invite code'),
    )

    renderRegister()
    await user.type(screen.getByLabelText('Email'), 'new@x.com')
    await user.type(screen.getByLabelText('Password'), 'password1')
    await user.type(screen.getByLabelText('Invite Code'), 'wrong-code')
    await user.click(screen.getByRole('button', { name: /sign up/i }))

    await waitFor(() => {
      expect(screen.getByText('Invalid invite code')).toBeInTheDocument()
    })
  })

  it('shows error when registration is disabled (403)', async () => {
    const user = userEvent.setup()
    ;(api.auth.register as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('403: Registration is disabled'),
    )

    renderRegister()
    await user.type(screen.getByLabelText('Email'), 'new@x.com')
    await user.type(screen.getByLabelText('Password'), 'password1')
    await user.type(screen.getByLabelText('Invite Code'), 'some-code')
    await user.click(screen.getByRole('button', { name: /sign up/i }))

    await waitFor(() => {
      expect(screen.getByText('Registration is currently disabled')).toBeInTheDocument()
    })
  })

  it('has a link to the login page', () => {
    renderRegister()
    expect(screen.getByText('Sign in')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// AuthGuard
// ---------------------------------------------------------------------------

describe('AuthGuard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(clearToken)()
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
