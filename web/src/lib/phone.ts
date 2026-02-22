/** Phone number masking utility. */

/**
 * Mask a phone number for display in list views.
 * "+44 7700 900123" → "+44 *** *** 0123"
 * Only the last 4 digits remain visible.
 */
export function maskPhone(number: string): string {
  if (!number) return ''
  const digits = number.replace(/\D/g, '')
  if (digits.length <= 4) return number
  const last4 = digits.slice(-4)
  // Build masked version preserving the country code style
  const prefix = number.slice(0, number.length - 4)
  const masked = prefix.replace(/\d/g, '*')
  return masked + last4
}

/**
 * Format a duration in seconds to a human-readable string.
 * 65 → "1m 5s", 3661 → "1h 1m 1s"
 */
export function formatDuration(seconds: number | null): string {
  if (seconds == null) return '—'
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const remainder = s % 60
  if (m < 60) return `${m}m ${remainder}s`
  const h = Math.floor(m / 60)
  const mRemainder = m % 60
  return `${h}h ${mRemainder}m ${remainder}s`
}

/**
 * Format ISO datetime to local short string.
 */
export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
