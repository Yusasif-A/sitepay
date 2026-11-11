const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5001'

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

/** Fetch wrapper (from Avalio). Throws ApiError with the backend's `detail`.
 *  Pass a FormData body for file uploads. */
async function request(path, { method = 'GET', token, body } = {}) {
  const headers = {}
  const isForm = body instanceof FormData
  if (!isForm && body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers.Authorization = `Bearer ${token}`

  let response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
    })
  } catch {
    throw new ApiError('Could not reach the SitePay server. Is the backend running?', 0)
  }

  const isJson = response.headers.get('content-type')?.includes('application/json')
  const data = isJson ? await response.json().catch(() => null) : null
  if (!response.ok) {
    let message = data?.detail || `Request failed (${response.status})`
    if (Array.isArray(message)) message = message.map((m) => m.msg).join('; ')
    throw new ApiError(typeof message === 'string' ? message : JSON.stringify(message), response.status)
  }
  return data
}

/** Images need the bearer token, so they're fetched and turned into object URLs. */
export async function fetchImageUrl(path, token) {
  const r = await fetch(`${API_BASE}${path}`, { headers: { Authorization: `Bearer ${token}` } })
  if (!r.ok) throw new ApiError('Photo unavailable', r.status)
  return URL.createObjectURL(await r.blob())
}

export const api = {
  get: (path, token) => request(path, { method: 'GET', token }),
  post: (path, body, token) => request(path, { method: 'POST', body, token }),
  put: (path, body, token) => request(path, { method: 'PUT', body, token }),
  patch: (path, body, token) => request(path, { method: 'PATCH', body, token }),
}

export { API_BASE }
