export function todayIn(settings) {
  return settings?.today || new Date().toISOString().slice(0, 10)
}

export function addDays(iso, n) {
  const d = new Date(iso + 'T00:00:00')
  d.setDate(d.getDate() + n)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function prettyDate(iso) {
  return new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
}

const SYMBOL = { NGN: '₦', KES: 'KSh ', INR: '₹', GHS: 'GH₵' }

export function money(amount, currency = 'NGN') {
  const s = SYMBOL[currency]
  const n = Number(amount || 0).toLocaleString('en-GB')
  return s ? `${s}${n}` : `${n} ${currency}`
}

export const STATUS = {
  P: { label: 'Present', short: 'P' },
  A: { label: 'Absent', short: 'A' },
  H: { label: 'Half day', short: 'H' },
  OT: { label: 'Overtime', short: 'OT' },
  L: { label: 'Paid leave', short: 'L' },
}

export const FLAG_TEXT = {
  too_dark: 'Too dark',
  duplicate_same_day: 'Repeat photo',
  duplicate_other_day: 'Photo from another day',
  unrelated: 'Looks unrelated',
  quality_dark: 'Dark',
  quality_blurry: 'Blurry',
  quality_too_far: 'Too far away',
  not_on_site: "Doesn't look like a site",
  no_person: 'No worker in check-in photo',
  timestamp_mismatch: 'Photo stamp is a different day',
}

export const TX_STATUS = {
  NOT_SENT: { label: 'Not sent', tone: 'neutral' },
  NOTHING_DUE: { label: 'Nothing due', tone: 'neutral' },
  PENDING: { label: 'Pending', tone: 'warn' },
  SUCCESS: { label: 'Paid', tone: 'ok' },
  UNCLAIMED: { label: 'Unclaimed', tone: 'warn' },
  ONHOLD: { label: 'On hold', tone: 'warn' },
  FAILED: { label: 'Failed', tone: 'bad' },
  RETURNED: { label: 'Returned', tone: 'bad' },
  BLOCKED: { label: 'Blocked', tone: 'bad' },
  REFUNDED: { label: 'Refunded', tone: 'bad' },
  REVERSED: { label: 'Reversed', tone: 'bad' },
}
