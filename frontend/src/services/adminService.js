import { apiDownload, apiRequest } from './api'

/** Builds ?a=1&b=2, skipping empty values. */
export function toQuery(params = {}) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, value)
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const adminService = {
  overview: (params) => apiRequest(`/api/admin/overview/${toQuery(params)}`),
  fraudStatistics: (params) => apiRequest(`/api/admin/fraud-statistics/${toQuery(params)}`),

  users: (params) => apiRequest(`/api/admin/users/${toQuery(params)}`),
  user: (id) => apiRequest(`/api/admin/users/${id}/`),
  userTransactions: (id, params) => apiRequest(`/api/admin/users/${id}/transactions/${toQuery(params)}`),
  setUserStatus: (id, isActive) =>
    apiRequest(`/api/admin/users/${id}/status/`, { method: 'PATCH', body: { is_active: isActive } }),

  transactions: (params) => apiRequest(`/api/admin/transactions/${toQuery(params)}`),
  transaction: (transactionId) => apiRequest(`/api/admin/transactions/${encodeURIComponent(transactionId)}/`),

  report: (kind, params) => apiRequest(`/api/admin/reports/${kind}/${toQuery(params)}`),
  downloadReport: (kind, params) =>
    apiDownload(`/api/admin/reports/${kind}/${toQuery({ ...params, export: 'csv' })}`),
}
