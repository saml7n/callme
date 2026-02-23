/** Settings page for managing integrations — /settings/integrations */

import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '@/lib/api'
import type { IntegrationItem, IntegrationType } from '@/lib/types'
import { INTEGRATION_TYPE_LABELS } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

/* ------------------------------------------------------------------ */
/* Config field definitions per integration type                       */
/* ------------------------------------------------------------------ */

interface FieldDef {
  key: string
  label: string
  type: 'text' | 'password' | 'url'
  placeholder: string
  required?: boolean
}

const CONFIG_FIELDS: Record<IntegrationType, FieldDef[]> = {
  google_calendar: [
    { key: 'client_id', label: 'Client ID', type: 'text', placeholder: '...apps.googleusercontent.com', required: true },
    { key: 'client_secret', label: 'Client Secret', type: 'password', placeholder: 'OAuth client secret', required: true },
    { key: 'calendar_id', label: 'Calendar ID', type: 'text', placeholder: 'primary', required: true },
  ],
  webhook: [
    { key: 'url', label: 'URL', type: 'url', placeholder: 'https://example.com/hook', required: true },
    { key: 'method', label: 'Method', type: 'text', placeholder: 'POST' },
    { key: 'auth_header', label: 'Authorization Header', type: 'password', placeholder: 'Bearer ...' },
  ],
}

/* ------------------------------------------------------------------ */
/* Main component                                                      */
/* ------------------------------------------------------------------ */

export default function Integrations() {
  const [integrations, setIntegrations] = useState<IntegrationItem[]>([])
  const [loading, setLoading] = useState(true)

  // Dialog state
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [formType, setFormType] = useState<IntegrationType>('webhook')
  const [formName, setFormName] = useState('')
  const [formConfig, setFormConfig] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)

  // Test state
  const [testingId, setTestingId] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<{ id: string; success: boolean; detail: string } | null>(null)

  const fetchIntegrations = useCallback(async () => {
    try {
      const list = await api.integrations.list()
      setIntegrations(list)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchIntegrations() }, [fetchIntegrations])

  /* ---- Dialog helpers ---- */

  const openCreate = () => {
    setEditingId(null)
    setFormType('webhook')
    setFormName('')
    setFormConfig({})
    setDialogOpen(true)
  }

  const openEdit = (item: IntegrationItem) => {
    setEditingId(item.id)
    setFormType(item.type)
    setFormName(item.name)
    // Pre-fill with redacted values (user overwrites secrets)
    const cfg: Record<string, string> = {}
    for (const [k, v] of Object.entries(item.config_redacted)) {
      cfg[k] = typeof v === 'string' ? v : JSON.stringify(v)
    }
    setFormConfig(cfg)
    setDialogOpen(true)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      // Build clean config — drop empty strings
      const config: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(formConfig)) {
        if (v) config[k] = v
      }

      if (editingId) {
        await api.integrations.update(editingId, { name: formName, config })
      } else {
        await api.integrations.create(formType, formName, config)
      }
      setDialogOpen(false)
      await fetchIntegrations()
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this integration?')) return
    try {
      await api.integrations.delete(id)
      await fetchIntegrations()
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to delete')
    }
  }

  const handleTest = async (id: string) => {
    setTestingId(id)
    setTestResult(null)
    try {
      const result = await api.integrations.test(id)
      setTestResult({ id, ...result })
    } catch (err) {
      setTestResult({ id, success: false, detail: err instanceof Error ? err.message : 'Test failed' })
    } finally {
      setTestingId(null)
    }
  }

  const handleOAuth = async (id: string) => {
    try {
      const { url } = await api.integrations.oauthStart(id)
      window.open(url, '_blank')
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to start OAuth')
    }
  }

  /* ---- Render ---- */

  return (
    <div className="flex-1 text-white">
      <div className="bg-gray-900/50 border-b border-gray-800 px-6 py-3 flex items-center justify-between">
        <span className="text-gray-300 text-sm font-medium">Integrations</span>
        <Link to="/settings/phone-numbers">
          <Button variant="outline" size="sm">Phone Numbers</Button>
        </Link>
      </div>
      <div className="max-w-3xl mx-auto px-6 py-10">
        {/* Page heading */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold">Integrations</h1>
            <p className="text-sm text-gray-400 mt-1">
              Connect external services for use in workflows.
            </p>
          </div>
          <Button onClick={openCreate}>+ Add Integration</Button>
        </div>

        {/* List */}
        {loading ? (
          <p className="text-gray-500 text-sm">Loading…</p>
        ) : integrations.length === 0 ? (
          <div className="text-center py-16 text-gray-500">
            <p className="text-lg mb-2">No integrations configured</p>
            <p className="text-sm mb-4">Add a Google Calendar or Webhook integration to get started.</p>
            <Button onClick={openCreate}>+ Add Integration</Button>
          </div>
        ) : (
          <div className="space-y-3">
            {integrations.map((item) => (
              <div
                key={item.id}
                className="bg-gray-900 border border-gray-800 rounded-lg p-4 flex items-center justify-between"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-lg">
                    {item.type === 'google_calendar' ? '📅' : '🔗'}
                  </span>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-white truncate">{item.name}</p>
                    <p className="text-xs text-gray-500">
                      {INTEGRATION_TYPE_LABELS[item.type]}
                    </p>
                  </div>
                  {testResult?.id === item.id && (
                    <Badge
                      className={testResult.success
                        ? 'bg-green-900 text-green-300'
                        : 'bg-red-900 text-red-300'}
                    >
                      {testResult.success ? '✓ Connected' : '✗ ' + testResult.detail}
                    </Badge>
                  )}
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  {item.type === 'google_calendar' && (
                    <Button size="sm" variant="outline" className="text-xs" onClick={() => handleOAuth(item.id)}>
                      OAuth
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="outline"
                    className="text-xs"
                    disabled={testingId === item.id}
                    onClick={() => handleTest(item.id)}
                  >
                    {testingId === item.id ? 'Testing…' : 'Test'}
                  </Button>
                  <Button size="sm" variant="outline" className="text-xs" onClick={() => openEdit(item)}>
                    Edit
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    className="text-xs"
                    onClick={() => handleDelete(item.id)}
                  >
                    Delete
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Create/Edit Dialog */}
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogContent className="bg-gray-900 border-gray-800 text-white sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>{editingId ? 'Edit Integration' : 'New Integration'}</DialogTitle>
            </DialogHeader>

            <div className="space-y-4 mt-2">
              {/* Type selector (only for create) */}
              {!editingId && (
                <div className="space-y-1.5">
                  <Label className="text-gray-400">Type</Label>
                  <Select
                    value={formType}
                    onValueChange={(v) => {
                      setFormType(v as IntegrationType)
                      setFormConfig({})
                    }}
                  >
                    <SelectTrigger className="bg-gray-800 border-gray-700 text-white">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="google_calendar">📅 Google Calendar</SelectItem>
                      <SelectItem value="webhook">🔗 Webhook</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              )}

              {/* Name */}
              <div className="space-y-1.5">
                <Label className="text-gray-400">Name</Label>
                <Input
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  className="bg-gray-800 border-gray-700 text-white"
                  placeholder="My Integration"
                />
              </div>

              {/* Dynamic config fields */}
              {CONFIG_FIELDS[formType].map((field) => (
                <div key={field.key} className="space-y-1.5">
                  <Label className="text-gray-400">
                    {field.label}
                    {field.required && <span className="text-red-400 ml-1">*</span>}
                  </Label>
                  <Input
                    type={field.type === 'password' ? 'password' : 'text'}
                    value={formConfig[field.key] ?? ''}
                    onChange={(e) => setFormConfig({ ...formConfig, [field.key]: e.target.value })}
                    className="bg-gray-800 border-gray-700 text-white"
                    placeholder={field.placeholder}
                  />
                </div>
              ))}

              <div className="flex justify-end gap-2 pt-2">
                <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
                <Button onClick={handleSave} disabled={saving || !formName.trim()}>
                  {saving ? 'Saving…' : editingId ? 'Update' : 'Create'}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  )
}
