const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''
const SAFE_METHODS = ['GET', 'HEAD', 'OPTIONS']

/** Error raised for any failed API call. `status` is 0 for network failures. */
export class ApiError extends Error {
  constructor(status, data = {}) {
    super(data.detail || 'Request failed')
    this.name = 'ApiError'
    this.status = status
    this.data = data
  }

  get isNetworkError() {
    return this.status === 0
  }

  get isServerError() {
    return this.status >= 500
  }
}

function readCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : null
}

async function send(path, options) {
  try {
    return await fetch(`${API_BASE_URL}${path}`, {
      credentials: 'include',
      ...options,
    })
  } catch {
    throw new ApiError(0, { detail: 'Unable to reach the server.' })
  }
}

/** Makes sure the csrftoken cookie exists (Django sets it on this endpoint). */
export async function ensureCsrfCookie() {
  if (readCookie('csrftoken')) return
  await send('/api/auth/csrf/', { method: 'GET' })
}

export async function apiRequest(path, { method = 'GET', body, headers: extraHeaders } = {}) {
  const headers = { Accept: 'application/json', ...extraHeaders }
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  if (!SAFE_METHODS.includes(method)) {
    await ensureCsrfCookie()
    const token = readCookie('csrftoken')
    if (token) headers['X-CSRFToken'] = token
  }

  const response = await send(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  let data = null
  if (response.status !== 204) {
    try {
      data = await response.json()
    } catch {
      data = null
    }
  }

  if (!response.ok) throw new ApiError(response.status, data ?? {})
  return data
}
