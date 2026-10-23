import { apiRequest } from './api'

export function createIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}

export const paymentService = {
  /** The Idempotency-Key makes retries of the same submission safe (no double payment). */
  create: (payment, idempotencyKey) =>
    apiRequest('/api/payments/', {
      method: 'POST',
      body: payment,
      headers: { 'Idempotency-Key': idempotencyKey },
    }),

  list: (page = 1) => apiRequest(`/api/payments/?page=${page}`),

  get: (transactionId) => apiRequest(`/api/payments/${encodeURIComponent(transactionId)}/`),

  // Fraud-response actions. The backend decides everything; these only report what the user chose.
  continueWithOtp: (transactionId) => action(transactionId, 'continue'),
  cancel: (transactionId) => action(transactionId, 'cancel'),
  resendOtp: (transactionId) => action(transactionId, 'resend-otp'),
  verifyOtp: (transactionId, code) => action(transactionId, 'verify-otp', { code }),
}

function action(transactionId, name, body) {
  return apiRequest(`/api/payments/${encodeURIComponent(transactionId)}/${name}/`, { method: 'POST', body: body ?? {} })
}
