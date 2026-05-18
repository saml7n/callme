/** API client for the CallMe backend. */

import type {
  CalendarEntry,
  CallDetail,
  CallListItem,
  GoogleOAuthStatus,
  IntegrationItem,
  IntegrationTestResult,
  IntegrationType,
  PhoneNumberItem,
  PlatformStatus,
  SettingsResponse,
  TemplateItem,
  TransferResult,
  ValidateResults,
  WorkflowDetail,
  WorkflowGraph,
  WorkflowListItem,
} from './types'
import { getToken } from './auth'

const API_BASE = import.meta.env.VITE_API_URL ?? ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string>),
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  })

  // If 401/403 on a protected endpoint, clear stored token and redirect to login.
  // Skip for parbaked-owned /auth/* endpoints — they handle their own errors
  // via the calling page (e.g. inline "wrong password" UX on /login).
  if (res.status === 401 || res.status === 403) {
    const isAuthEndpoint = path.startsWith('/auth/')
    if (!isAuthEndpoint) {
      const { clearToken } = await import('./auth')
      clearToken()
      if (
        typeof window !== 'undefined' &&
        !window.location.pathname.startsWith('/login') &&
        !window.location.pathname.startsWith('/register')
      ) {
        window.location.href = '/login'
      }
    }
  }

  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status}: ${body}`)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  auth: {
    // parbaked owns /auth/* — signup creates a pending user, admin approves
    // before login works (see /admin in the admin app). The legacy
    // invite-code gate is gone; ``_inviteCode`` is accepted for type
    // compatibility with old call sites but is ignored.
    login: (email: string, password: string) =>
      request<{ token: string; user: { id: string; email: string; name: string; status: string } }>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      }),
    register: (email: string, password: string, name: string, _inviteCode?: string) =>
      request<{ user_id: string; status: string; email_sent: boolean }>('/auth/signup', {
        method: 'POST',
        body: JSON.stringify({ email, password, name }),
      }),
    me: () => request<{ id: string; email: string; name: string }>('/auth/me'),
    // Legacy compatibility shims for the pre-parbaked UI. These features are
    // gone (admin-approval is now in parbaked's /admin UI, no more API-key
    // login, no more config-warnings panel). Keep no-op stubs so existing
    // call sites don't blow up at runtime — they're harmless.
    loginWithKey: (_key: string): Promise<{ token: string; user: { id: string; email: string; name: string; status: string } }> =>
      Promise.reject(new Error('API-key login removed in the parbaked migration; use email + password.')),
    check: () => Promise.resolve({ auth_enabled: true }),
    configWarnings: () => Promise.resolve({ warnings: [] as string[] }),
  },

  workflows: {
    list: () => request<WorkflowListItem[]>('/api/workflows'),

    get: (id: string) => request<WorkflowDetail>(`/api/workflows/${id}`),

    getActive: (phoneNumber?: string) => {
      const q = phoneNumber ? `?phone_number=${encodeURIComponent(phoneNumber)}` : ''
      return request<WorkflowDetail>(`/api/workflows/active${q}`)
    },

    create: (name: string, graphJson: WorkflowGraph) =>
      request<WorkflowDetail>('/api/workflows', {
        method: 'POST',
        body: JSON.stringify({ name, graph_json: graphJson }),
      }),

    update: (id: string, body: { name?: string; graph_json?: WorkflowGraph }) =>
      request<WorkflowDetail>(`/api/workflows/${id}`, {
        method: 'PUT',
        body: JSON.stringify(body),
      }),

    publish: (id: string, phoneNumberId: string, version?: number) =>
      request<WorkflowDetail>(`/api/workflows/${id}/publish`, {
        method: 'POST',
        body: JSON.stringify({
          phone_number_id: phoneNumberId,
          ...(version !== undefined ? { version } : {}),
        }),
      }),

    delete: (id: string) =>
      request<void>(`/api/workflows/${id}`, { method: 'DELETE' }),
  },

  calls: {
    list: (limit = 50, offset = 0) =>
      request<CallListItem[]>(`/api/calls?limit=${limit}&offset=${offset}`),

    get: (id: string) => request<CallDetail>(`/api/calls/${id}`),

    live: () => request<Record<string, unknown>[]>('/api/calls/live'),

    liveCount: () => request<{ count: number }>('/api/calls/live/count'),

    transfer: (id: string) =>
      request<TransferResult>(`/api/live/${id}/transfer`, { method: 'POST' }),
  },

  phoneNumbers: {
    list: () => request<PhoneNumberItem[]>('/api/phone-numbers'),

    create: (number: string, label: string) =>
      request<PhoneNumberItem>('/api/phone-numbers', {
        method: 'POST',
        body: JSON.stringify({ number, label }),
      }),

    delete: (id: string) =>
      request<void>(`/api/phone-numbers/${id}`, { method: 'DELETE' }),
  },

  integrations: {
    list: () => request<IntegrationItem[]>('/api/integrations'),

    create: (type: IntegrationType, name: string, config: Record<string, unknown>) =>
      request<IntegrationItem>('/api/integrations', {
        method: 'POST',
        body: JSON.stringify({ type, name, config }),
      }),

    update: (id: string, body: { name?: string; config?: Record<string, unknown> }) =>
      request<IntegrationItem>(`/api/integrations/${id}`, {
        method: 'PUT',
        body: JSON.stringify(body),
      }),

    delete: (id: string) =>
      request<void>(`/api/integrations/${id}`, { method: 'DELETE' }),

    test: (id: string) =>
      request<IntegrationTestResult>(`/api/integrations/${id}/test`, { method: 'POST' }),

    oauthStart: (id: string) =>
      request<{ url: string }>(`/api/integrations/${id}/oauth/start`),

    googleStatus: () =>
      request<GoogleOAuthStatus>('/api/integrations/google/status'),

    googleConnect: () =>
      request<{ url: string }>('/api/integrations/google/connect'),

    calendars: (id: string) =>
      request<CalendarEntry[]>(`/api/integrations/${id}/calendars`),
  },

  settings: {
    get: () => request<SettingsResponse>('/api/settings'),

    put: (settings: Record<string, string>) =>
      request<SettingsResponse>('/api/settings', {
        method: 'PUT',
        body: JSON.stringify({ settings }),
      }),

    validate: () =>
      request<ValidateResults>('/api/settings/validate', { method: 'POST' }),
  },

  templates: {
    list: () => request<TemplateItem[]>('/api/templates'),
  },

  platform: {
    status: () => request<PlatformStatus>('/api/platform/status'),
  },

  // Legacy admin endpoints (demo reset / seed) were removed in the parbaked
  // migration. Stubs keep older call sites compiling; production should use
  // parbaked's /admin UI for user approval instead.
  admin: {
    reset: (): Promise<{ status: string; message: string }> =>
      Promise.reject(new Error('admin reset endpoint removed in the parbaked migration')),
    seed: (): Promise<{ status: string; message: string }> =>
      Promise.reject(new Error('admin seed endpoint removed in the parbaked migration')),
  },

  health: () =>
    request<{ status: string; public_url: string | null; demo_mode: boolean; services: Record<string, { status: string }> }>('/health?detail=true'),
}
