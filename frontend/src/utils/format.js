export function formatCurrency(amount, currency = 'INR') {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency }).format(Number(amount))
}

export function formatDateTime(iso) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export function formatDate(iso) {
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: 'medium' })
}

export function formatCompact(value) {
  // en-US compact (K, M, B): clearer than en-IN's "T" for thousands
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(Number(value))
}

/** Chart axis label for a bucket start date (ISO yyyy-mm-dd, treated as UTC). */
export function formatPeriod(iso, groupBy = 'day') {
  const date = new Date(`${iso}T00:00:00Z`)
  const options =
    groupBy === 'month' ? { month: 'short', year: 'numeric' } : { day: 'numeric', month: 'short' }
  const text = date.toLocaleDateString(undefined, { ...options, timeZone: 'UTC' })
  return groupBy === 'week' ? `Week of ${text}` : text
}
