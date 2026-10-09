export const PRESETS = [
  { value: '7d', label: 'Last 7 days', days: 7 },
  { value: '30d', label: 'Last 30 days', days: 30 },
  { value: '90d', label: 'Last 90 days', days: 90 },
  { value: 'all', label: 'All time' },
  { value: 'custom', label: 'Custom range' },
]

const utcDay = (date) => date.toISOString().slice(0, 10)

export const DEFAULT_RANGE = { preset: '30d', from: '', to: '', groupBy: '' }

/** Turns the date-range filter state into API query parameters (UTC days, matching the backend). */
export function rangeToParams({ preset, from, to, groupBy }) {
  const params = { group_by: groupBy || undefined }
  const selected = PRESETS.find((candidate) => candidate.value === preset)
  if (selected?.days) {
    const start = new Date()
    start.setUTCDate(start.getUTCDate() - (selected.days - 1))
    params.date_from = utcDay(start)
  } else if (preset === 'custom') {
    if (from && to && from > to) return params // invalid range: the inline message explains it
    params.date_from = from || undefined
    params.date_to = to || undefined
  }
  return params
}
