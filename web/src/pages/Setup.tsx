/** Setup wizard — guided onboarding flow (Story 17).
 *
 * Steps: 1) Welcome  2) API Keys  3) Phone Number  4) First Workflow  5) Publish & Test
 */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/lib/api'
import type { PhoneNumberItem, TemplateItem, WorkflowDetail } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'

const STEPS = ['Welcome', 'API Keys', 'Phone Number', 'First Workflow', 'Publish & Test'] as const

// Field config for step 2
const API_KEY_FIELDS = [
  {
    key: 'twilio_account_sid',
    label: 'Twilio Account SID',
    hint: 'Find it on your Twilio Console dashboard',
    link: 'https://console.twilio.com/',
    service: 'twilio',
  },
  {
    key: 'twilio_api_key_sid',
    label: 'Twilio API Key SID',
    hint: 'Create one at Account → API keys & tokens in the Twilio Console',
    link: 'https://console.twilio.com/us1/account/keys-credentials/api-keys',
    service: 'twilio',
  },
  {
    key: 'twilio_api_key_secret',
    label: 'Twilio API Key Secret',
    hint: 'Shown once when you create the API key — paste it here',
    link: 'https://console.twilio.com/us1/account/keys-credentials/api-keys',
    service: 'twilio',
  },
  {
    key: 'deepgram_api_key',
    label: 'Deepgram API Key',
    hint: 'Create one at Settings → API Keys in the Deepgram dashboard',
    link: 'https://console.deepgram.com/settings/api-keys',
    service: 'deepgram',
  },
  {
    key: 'elevenlabs_api_key',
    label: 'ElevenLabs API Key',
    hint: 'Go to Profile → API Keys in your ElevenLabs dashboard',
    link: 'https://elevenlabs.io/app/settings/api-keys',
    service: 'elevenlabs',
  },
  {
    key: 'openai_api_key',
    label: 'OpenAI API Key',
    hint: 'Create one at platform.openai.com → API Keys',
    link: 'https://platform.openai.com/api-keys',
    service: 'openai',
  },
] as const

export default function Setup() {
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [settings, setSettings] = useState<Record<string, string>>({})
  const [validation, setValidation] = useState<Record<string, string>>({})
  const [validating, setValidating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [expandedHints, setExpandedHints] = useState<Set<string>>(new Set())

  // Step 3 state
  const [twilioPhone, setTwilioPhone] = useState('')
  const [adminPhone, setAdminPhone] = useState('')

  // Step 4 state
  const [templates, setTemplates] = useState<TemplateItem[]>([])
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null)
  const [createdWorkflow, setCreatedWorkflow] = useState<WorkflowDetail | null>(null)
  const [creatingWorkflow, setCreatingWorkflow] = useState(false)

  // Step 5 state
  const [phoneNumbers, setPhoneNumbers] = useState<PhoneNumberItem[]>([])
  const [publishing, setPublishing] = useState(false)
  const [published, setPublished] = useState(false)

  // Load existing settings on mount — pre-fill fields and auto-validate if keys exist
  useEffect(() => {
    let cancelled = false

    async function hydrate() {
      try {
        // 1. Load settings and pre-fill fields
        const res = await api.settings.get()
        if (cancelled) return
        const existing: Record<string, string> = {}
        for (const [k, v] of Object.entries(res.settings)) {
          if (v) existing[k] = v
        }
        setSettings((prev) => ({ ...existing, ...prev }))

        // Pre-fill phone numbers from saved settings
        if (existing.twilio_phone_number) setTwilioPhone((p) => p || existing.twilio_phone_number)
        if (existing.admin_phone_number) setAdminPhone((p) => p || existing.admin_phone_number)

        // If API keys are configured, auto-validate so the user can skip through
        if (res.configured) {
          setValidating(true)
          try {
            const v = await api.settings.validate()
            if (!cancelled) setValidation(v.results)
          } finally {
            if (!cancelled) setValidating(false)
          }
        }

        // 2. Load phone numbers (for step 5)
        const phones = await api.phoneNumbers.list()
        if (!cancelled) setPhoneNumbers(phones)

        // 3. Load existing workflows — resume step 4/5 if one already exists
        const workflows = await api.workflows.list()
        if (!cancelled && workflows.length > 0) {
          const wf = await api.workflows.get(workflows[0].id)
          if (!cancelled) setCreatedWorkflow(wf)
        }

        // 4. Load templates (for step 4)
        const tmpls = await api.templates.list()
        if (!cancelled) setTemplates(tmpls)
      } catch {
        // ignore — offline or server not started yet
      }
    }

    hydrate()
    return () => { cancelled = true }
  }, [])

  const updateSetting = (key: string, value: string) => {
    setSettings((prev) => ({ ...prev, [key]: value }))
  }

  const toggleHint = (key: string) => {
    setExpandedHints((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const saveSettings = async (fields: Record<string, string>) => {
    setSaving(true)
    try {
      // Filter out redacted values (user hasn't changed them)
      const toSave: Record<string, string> = {}
      for (const [k, v] of Object.entries(fields)) {
        if (v && !v.startsWith('••••')) {
          toSave[k] = v
        }
      }
      if (Object.keys(toSave).length > 0) {
        await api.settings.put(toSave)
      }
    } finally {
      setSaving(false)
    }
  }

  const handleValidateAll = async () => {
    // Save first, then validate
    const apiKeyFields: Record<string, string> = {}
    for (const f of API_KEY_FIELDS) {
      if (settings[f.key]) apiKeyFields[f.key] = settings[f.key]
    }
    await saveSettings(apiKeyFields)

    setValidating(true)
    try {
      const res = await api.settings.validate()
      setValidation(res.results)
    } catch {
      setValidation({})
    } finally {
      setValidating(false)
    }
  }

  const handleSavePhoneNumbers = async () => {
    const toSave: Record<string, string> = {}
    if (twilioPhone) toSave.twilio_phone_number = twilioPhone
    if (adminPhone) toSave.admin_phone_number = adminPhone

    await saveSettings(toSave)

    // Also register the phone number in the system if not already there
    if (twilioPhone) {
      const existing = await api.phoneNumbers.list()
      if (!existing.find((p) => p.number === twilioPhone)) {
        await api.phoneNumbers.create(twilioPhone, 'Primary')
      }
      setPhoneNumbers(await api.phoneNumbers.list())
    }
  }

  const handleCreateWorkflow = async () => {
    if (!selectedTemplate) return
    const tmpl = templates.find((t) => t.id === selectedTemplate)
    if (!tmpl) return

    setCreatingWorkflow(true)
    try {
      const wf = await api.workflows.create(tmpl.name, tmpl.graph)
      setCreatedWorkflow(wf)
    } catch {
      // ignore
    } finally {
      setCreatingWorkflow(false)
    }
  }

  const handlePublish = async () => {
    if (!createdWorkflow || phoneNumbers.length === 0) return
    setPublishing(true)
    try {
      await api.workflows.publish(createdWorkflow.id, phoneNumbers[0].id, createdWorkflow.version)
      setPublished(true)
    } catch {
      // ignore
    } finally {
      setPublishing(false)
    }
  }

  const handleFinish = () => {
    navigate('/workflows')
  }

  const canProceedStep = (s: number): boolean => {
    switch (s) {
      case 0: return true // Welcome
      case 1: {
        // Allow proceeding if validation passed OR if all core keys are already saved (redacted)
        const validated = Object.values(validation).some((v) => v === 'ok')
        const coreKeys = ['twilio_account_sid', 'deepgram_api_key', 'elevenlabs_api_key', 'openai_api_key']
        const allConfigured = coreKeys.every((k) => settings[k] && settings[k].length > 0)
        return validated || allConfigured
      }
      case 2: return !!twilioPhone
      case 3: return createdWorkflow !== null
      case 4: return true
      default: return true
    }
  }

  const nextStep = () => {
    if (step < STEPS.length - 1) setStep(step + 1)
  }

  const prevStep = () => {
    if (step > 0) setStep(step - 1)
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Progress bar */}
      <div className="border-b border-gray-800 bg-gray-900/50">
        <div className="mx-auto max-w-2xl px-6 py-4">
          <div className="flex items-center justify-between mb-2">
            {STEPS.map((name, i) => (
              <button
                key={name}
                onClick={() => setStep(i)}
                className={`text-xs font-medium transition ${
                  i === step ? 'text-indigo-400' : i < step ? 'text-gray-400' : 'text-gray-600'
                }`}
              >
                {name}
              </button>
            ))}
          </div>
          <div className="h-1 bg-gray-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-indigo-500 transition-all duration-300"
              style={{ width: `${((step + 1) / STEPS.length) * 100}%` }}
            />
          </div>
        </div>
      </div>

      {/* Step content */}
      <div className="mx-auto max-w-2xl px-6 py-12">
        {/* Step 1: Welcome */}
        {step === 0 && (
          <div className="text-center space-y-6" data-testid="step-welcome">
            <h1 className="text-3xl font-bold">Welcome to Pronto!</h1>
            <p className="text-lg text-gray-400">
              Let's get your AI receptionist running. This wizard will walk you through:
            </p>
            <div className="grid gap-3 text-left max-w-md mx-auto">
              <div className="flex items-start gap-3 text-gray-300">
                <span className="text-xl mt-0.5">🔑</span>
                <div>
                  <div className="font-medium">API Keys</div>
                  <div className="text-sm text-gray-500">Connect Twilio, Deepgram, ElevenLabs, and OpenAI</div>
                </div>
              </div>
              <div className="flex items-start gap-3 text-gray-300">
                <span className="text-xl mt-0.5">📞</span>
                <div>
                  <div className="font-medium">Phone Number</div>
                  <div className="text-sm text-gray-500">Set up your Twilio number for incoming calls</div>
                </div>
              </div>
              <div className="flex items-start gap-3 text-gray-300">
                <span className="text-xl mt-0.5">🤖</span>
                <div>
                  <div className="font-medium">First Workflow</div>
                  <div className="text-sm text-gray-500">Choose a starter template or build from scratch</div>
                </div>
              </div>
              <div className="flex items-start gap-3 text-gray-300">
                <span className="text-xl mt-0.5">🚀</span>
                <div>
                  <div className="font-medium">Publish & Test</div>
                  <div className="text-sm text-gray-500">Go live and call your number to test</div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Step 2: API Keys */}
        {step === 1 && (
          <div className="space-y-6" data-testid="step-api-keys">
            <div>
              <h2 className="text-2xl font-bold mb-1">API Keys</h2>
              <p className="text-gray-400">Enter your API keys for each service. We'll test them all at once.</p>
            </div>

            <div className="space-y-4">
              {API_KEY_FIELDS.map((field) => {
                const val = settings[field.key] ?? ''
                const isRedacted = val.startsWith('••••')
                return (
                <div key={field.key} className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <Label htmlFor={field.key}>{field.label}</Label>
                    <div className="flex items-center gap-2">
                      {isRedacted && !validation[field.service] && (
                        <Badge className="bg-gray-800 text-gray-400 border-gray-700/50">Saved</Badge>
                      )}
                      {validation[field.service] === 'ok' && (
                        <Badge className="bg-green-900/50 text-green-400 border-green-700/50">✓ Valid</Badge>
                      )}
                      {validation[field.service] && validation[field.service] !== 'ok' && validation[field.service] !== 'not_configured' && (
                        <Badge className="bg-red-900/50 text-red-400 border-red-700/50">✗ Error</Badge>
                      )}
                    </div>
                  </div>
                  {isRedacted ? (
                    <div className="flex gap-2">
                      <Input
                        id={field.key}
                        type="text"
                        readOnly
                        value={val}
                        className="bg-gray-900 border-gray-700 text-gray-500 flex-1"
                      />
                      <Button
                        variant="outline"
                        size="sm"
                        className="border-gray-700 text-gray-400 shrink-0"
                        onClick={() => updateSetting(field.key, '')}
                      >
                        Change
                      </Button>
                    </div>
                  ) : (
                    <Input
                      id={field.key}
                      type="password"
                      placeholder={field.label}
                      value={val}
                      onChange={(e) => updateSetting(field.key, e.target.value)}
                      className="bg-gray-900 border-gray-700"
                    />
                  )}
                  <button
                    onClick={() => toggleHint(field.key)}
                    className="text-xs text-indigo-400 hover:text-indigo-300 transition"
                  >
                    {expandedHints.has(field.key) ? '▾' : '▸'} Where do I find this?
                  </button>
                  {expandedHints.has(field.key) && (
                    <div className="text-xs text-gray-500 pl-4 border-l border-gray-800">
                      {field.hint}.{' '}
                      <a href={field.link} target="_blank" rel="noopener noreferrer" className="text-indigo-400 hover:underline">
                        Open dashboard →
                      </a>
                    </div>
                  )}
                </div>
              )})}
            </div>

            <Button
              onClick={handleValidateAll}
              disabled={validating}
              className="w-full"
            >
              {validating ? 'Validating...' : 'Validate All'}
            </Button>
          </div>
        )}

        {/* Step 3: Phone Number */}
        {step === 2 && (
          <div className="space-y-6" data-testid="step-phone-number">
            <div>
              <h2 className="text-2xl font-bold mb-1">Phone Number</h2>
              <p className="text-gray-400">Enter the Twilio phone number where your AI receptionist will answer calls.</p>
            </div>

            <div className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="twilio_phone">Twilio Phone Number</Label>
                <Input
                  id="twilio_phone"
                  placeholder="+15551234567"
                  value={twilioPhone}
                  onChange={(e) => setTwilioPhone(e.target.value)}
                  className="bg-gray-900 border-gray-700"
                />
                <p className="text-xs text-gray-500">
                  E.164 format (e.g., +15551234567). This number must belong to your Twilio account.
                  {twilioPhone.startsWith('••••') && (
                    <span className="text-indigo-400 ml-1">Already saved — clear and re-enter to change.</span>
                  )}
                </p>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="admin_phone">Your Mobile Number (for alerts)</Label>
                <Input
                  id="admin_phone"
                  placeholder="+15559876543"
                  value={adminPhone}
                  onChange={(e) => setAdminPhone(e.target.value)}
                  className="bg-gray-900 border-gray-700"
                />
                <p className="text-xs text-gray-500">
                  We'll text you when a live call comes in. Optional.
                  {adminPhone.startsWith('••••') && (
                    <span className="text-indigo-400 ml-1">Already saved — clear and re-enter to change.</span>
                  )}
                </p>
              </div>
            </div>

            <Button
              onClick={async () => {
                // Only save if the user actually entered new values (not redacted)
                if ((twilioPhone && !twilioPhone.startsWith('••••')) || (adminPhone && !adminPhone.startsWith('••••'))) {
                  await handleSavePhoneNumbers()
                }
                nextStep()
              }}
              disabled={!twilioPhone || saving}
            >
              {saving ? 'Saving...' : 'Save & Continue'}
            </Button>
          </div>
        )}

        {/* Step 4: First Workflow */}
        {step === 3 && (
          <div className="space-y-6" data-testid="step-first-workflow">
            <div>
              <h2 className="text-2xl font-bold mb-1">First Workflow</h2>
              <p className="text-gray-400">Choose a starter template to get going quickly, or start from scratch.</p>
            </div>

            <div className="grid gap-3">
              {templates.map((tmpl) => (
                <button
                  key={tmpl.id}
                  onClick={() => setSelectedTemplate(tmpl.id)}
                  className={`text-left p-4 rounded-lg border transition ${
                    selectedTemplate === tmpl.id
                      ? 'border-indigo-500 bg-indigo-950/30'
                      : 'border-gray-800 bg-gray-900/50 hover:border-gray-700'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <span className="text-2xl">{tmpl.icon}</span>
                    <div>
                      <div className="font-medium">{tmpl.name}</div>
                      <div className="text-sm text-gray-400">{tmpl.description}</div>
                    </div>
                  </div>
                </button>
              ))}

              <button
                onClick={() => { navigate('/workflows/new'); }}
                className="text-left p-4 rounded-lg border border-gray-800 bg-gray-900/50 hover:border-gray-700 transition"
              >
                <div className="flex items-center gap-3">
                  <span className="text-2xl">✏️</span>
                  <div>
                    <div className="font-medium">Start from Scratch</div>
                    <div className="text-sm text-gray-400">Open the workflow builder with a blank canvas.</div>
                  </div>
                </div>
              </button>
            </div>

            {selectedTemplate && !createdWorkflow && (
              <Button
                onClick={handleCreateWorkflow}
                disabled={creatingWorkflow}
                className="w-full"
              >
                {creatingWorkflow ? 'Creating...' : 'Use This Template'}
              </Button>
            )}

            {createdWorkflow && (
              <div className="p-4 rounded-lg border border-green-800/50 bg-green-950/20">
                <div className="flex items-center gap-2">
                  <span className="text-green-400">✓</span>
                  <span className="text-green-300 font-medium">Workflow "{createdWorkflow.name}" created!</span>
                </div>
                <p className="text-sm text-gray-400 mt-1">You can edit it later in the workflow builder.</p>
              </div>
            )}
          </div>
        )}

        {/* Step 5: Publish & Test */}
        {step === 4 && (
          <div className="space-y-6" data-testid="step-publish">
            <div>
              <h2 className="text-2xl font-bold mb-1">Publish & Test</h2>
              <p className="text-gray-400">Make your workflow live and test it with a real phone call.</p>
            </div>

            {!published ? (
              <>
                {createdWorkflow && phoneNumbers.length > 0 ? (
                  <div className="space-y-4">
                    <div className="p-4 rounded-lg border border-gray-800 bg-gray-900/50">
                      <div className="text-sm text-gray-400">Workflow</div>
                      <div className="font-medium">{createdWorkflow.name}</div>
                    </div>
                    <div className="p-4 rounded-lg border border-gray-800 bg-gray-900/50">
                      <div className="text-sm text-gray-400">Phone Number</div>
                      <div className="font-medium">{phoneNumbers[0].number}</div>
                    </div>
                    <Button onClick={handlePublish} disabled={publishing} className="w-full">
                      {publishing ? 'Publishing...' : 'Publish Workflow'}
                    </Button>
                  </div>
                ) : (
                  <div className="text-center text-gray-400 py-8">
                    {!createdWorkflow && <p>Go back to Step 4 to create a workflow first.</p>}
                    {createdWorkflow && phoneNumbers.length === 0 && <p>Go back to Step 3 to add a phone number.</p>}
                  </div>
                )}
              </>
            ) : (
              <div className="text-center space-y-4">
                <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-green-950/50 border border-green-700/50">
                  <span className="text-3xl">🎉</span>
                </div>
                <h3 className="text-xl font-bold text-green-400">Your AI receptionist is live!</h3>
                <p className="text-lg text-gray-300">
                  Call <span className="font-mono text-white">{phoneNumbers[0]?.number || twilioPhone}</span> now to test!
                </p>
                <div className="flex items-center justify-center gap-2 text-sm text-gray-500">
                  <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
                  Active
                </div>
              </div>
            )}
          </div>
        )}

        {/* Navigation */}
        <div className="flex justify-between mt-8 pt-6 border-t border-gray-800">
          <Button
            variant="outline"
            onClick={prevStep}
            disabled={step === 0}
            className="border-gray-700 text-gray-300"
          >
            Back
          </Button>

          {step < STEPS.length - 1 ? (
            <Button onClick={nextStep} disabled={!canProceedStep(step)}>
              Next
            </Button>
          ) : (
            <Button onClick={handleFinish}>
              Go to Dashboard
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
