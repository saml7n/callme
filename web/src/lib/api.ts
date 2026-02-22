/** API client for the CallMe backend. */

import type {
  CallDetail,
  CallListItem,
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

  // If 401/403, clear stored token so user gets redirected to login
  if (res.status === 401 || res.status === 403) {
    const { clearToken } = await import('./auth')
    clearToken()
    // Only redirect if we're in a browser context
    if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
      window.location.href = '/login'
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
    login: (key: string) =>
      request<{ ok: boolean; token: string }>('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ key }),
      }),
    check: () => request<{ auth_enabled: boolean }>('/api/auth/check'),
    configWarnings: () => request<{ warnings: string[] }>('/api/auth/config-warnings'),
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

    publish: (id: string, phoneNumber: string) =>
      request<WorkflowDetail>(`/api/workflows/${id}/publish`, {
        method: 'POST',
        body: JSON.stringify({ phone_number: phoneNumber }),
      }),

    delete: (id: string) =>
      request<void>(`/api/workflows/${id}`, { method: 'DELETE' }),
  },

  calls: {
    list: (limit = 50, offset = 0) =>
      request<CallListItem[]>(`/api/calls?limit=${limit}&offset=${offset}`),

    get: (id: string) => request<CallDetail>(`/api/calls/${id}`),
  },
}
