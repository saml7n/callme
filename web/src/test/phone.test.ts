/** Unit tests for phone masking and formatting utilities. */

import { describe, it, expect } from 'vitest'
import { maskPhone, formatDuration, formatDateTime } from '@/lib/phone'

describe('maskPhone', () => {
  it('masks a UK mobile number', () => {
    expect(maskPhone('+447700900123')).toBe('+********0123')
  })

  it('masks a US number with spaces', () => {
    expect(maskPhone('+1 555 123 4567')).toBe('+* *** *** 4567')
  })

  it('returns empty string for empty input', () => {
    expect(maskPhone('')).toBe('')
  })

  it('preserves very short numbers unchanged', () => {
    expect(maskPhone('1234')).toBe('1234')
  })

  it('masks a number with only 5 digits', () => {
    expect(maskPhone('12345')).toBe('*2345')
  })
})

describe('formatDuration', () => {
  it('formats null as em-dash', () => {
    expect(formatDuration(null)).toBe('—')
  })

  it('formats seconds only', () => {
    expect(formatDuration(45)).toBe('45s')
  })

  it('formats minutes and seconds', () => {
    expect(formatDuration(125)).toBe('2m 5s')
  })

  it('formats hours, minutes and seconds', () => {
    expect(formatDuration(3661)).toBe('1h 1m 1s')
  })

  it('formats exactly 60 seconds as 1m 0s', () => {
    expect(formatDuration(60)).toBe('1m 0s')
  })
})

describe('formatDateTime', () => {
  it('returns a non-empty formatted string', () => {
    const result = formatDateTime('2024-01-15T14:30:00Z')
    expect(result).toBeTruthy()
    // Should contain the day number at minimum
    expect(result).toContain('15')
  })
})
