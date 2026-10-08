const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/

export const PASSWORD_MIN_LENGTH = 8

export const passwordChecks = (password) => [
  { id: 'length', label: `At least ${PASSWORD_MIN_LENGTH} characters`, met: password.length >= PASSWORD_MIN_LENGTH },
  { id: 'letter', label: 'Includes a letter', met: /[A-Za-z]/.test(password) },
  { id: 'number', label: 'Includes a number', met: /\d/.test(password) },
]

export function validateEmail(email) {
  const value = email.trim()
  if (!value) return 'Email is required.'
  if (!EMAIL_PATTERN.test(value)) return 'Enter a valid email address.'
  return ''
}

export function validateFullName(name) {
  const value = name.trim()
  if (!value) return 'Full name is required.'
  if (value.length < 2) return 'Please enter your full name.'
  return ''
}

export function validateNewPassword(password) {
  if (!password) return 'Password is required.'
  if (password.length < PASSWORD_MIN_LENGTH) {
    return `Password must be at least ${PASSWORD_MIN_LENGTH} characters.`
  }
  if (/^\d+$/.test(password)) return "Password can't be entirely numeric."
  if (!/[A-Za-z]/.test(password) || !/\d/.test(password)) {
    return 'Use a mix of letters and numbers.'
  }
  return ''
}

export function validateConfirmPassword(password, confirmPassword) {
  if (!confirmPassword) return 'Please confirm your password.'
  if (password !== confirmPassword) return 'Passwords do not match.'
  return ''
}

export function validateCurrentPassword(password) {
  return password ? '' : 'Enter your current password.'
}

export function validateLoginPassword(password) {
  return password ? '' : 'Password is required.'
}

/** Turns a failed API call into { fieldErrors, formError } for the forms. */
export function parseApiError(error, fieldMap = {}) {
  if (error.isNetworkError) {
    return { fieldErrors: {}, formError: "We can't reach PaySafe right now. Check your connection and try again." }
  }
  if (error.status === 429) {
    return { fieldErrors: {}, formError: 'Too many attempts. Please wait a moment and try again.' }
  }
  if (error.status === 403) {
    return { fieldErrors: {}, formError: 'Your session has expired or the request was blocked. Please refresh the page and try again.' }
  }
  if (error.isServerError) {
    return { fieldErrors: {}, formError: 'Something went wrong on our side. Please try again shortly.' }
  }

  const fieldErrors = {}
  let formError = ''
  const { data } = error
  if (error.status === 400 && data && typeof data === 'object') {
    for (const [key, messages] of Object.entries(data)) {
      const text = Array.isArray(messages) ? messages.join(' ') : String(messages)
      const field = fieldMap[key]
      if (field) fieldErrors[field] = text
      else formError = formError ? `${formError} ${text}` : text
    }
  }
  if (!Object.keys(fieldErrors).length && !formError) {
    formError = error.data?.detail || 'Request failed. Please try again.'
  }
  return { fieldErrors, formError }
}

// ---------- Payments ----------

export const DESCRIPTION_MAX_LENGTH = 255
const UPI_PATTERN = /^[A-Za-z0-9._-]{2,64}@[A-Za-z][A-Za-z0-9]{1,31}$/

export function validateAmount(raw) {
  const value = raw.trim()
  if (!value) return 'Amount is required.'
  if (value.startsWith('-')) return 'Amount must be greater than zero.'
  if (!/^\d+(\.\d+)?$/.test(value)) return 'Enter a valid amount using numbers only.'
  if (!/^\d+(\.\d{1,2})?$/.test(value)) return 'Amount can have at most 2 decimal places.'
  if (Number(value) <= 0) return 'Amount must be greater than zero.'
  if (value.split('.')[0].replace(/^0+/, '').length > 10) return 'Amount is too large.'
  return ''
}

export function validateRecipientName(name) {
  const value = name.trim()
  if (!value) return 'Recipient name is required.'
  if (value.length < 2) return "Enter the recipient's full name."
  return ''
}

export function validateRecipientEmail(email) {
  const value = email.trim()
  if (!value) return 'Recipient email is required.'
  return EMAIL_PATTERN.test(value) ? '' : 'Enter a valid email address.'
}

export function validateRequiredChoice(value, message) {
  return value ? '' : message
}

export function validateUpiId(upiId) {
  const value = upiId.trim()
  if (!value) return 'UPI ID is required.'
  return UPI_PATTERN.test(value) ? '' : 'Enter a valid UPI ID, like name@bank.'
}

export function validateDescription(description) {
  return description.length > DESCRIPTION_MAX_LENGTH
    ? `Note can be at most ${DESCRIPTION_MAX_LENGTH} characters.`
    : ''
}
