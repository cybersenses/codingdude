// Thin API client for the codingdude server.
// Auth: the server sets an HttpOnly session cookie at /login; all requests
// send it automatically (same-origin).

export function getToken() {
  return (localStorage.getItem('codingdude-token') || '').trim()
}

export function setToken(token) {
  localStorage.setItem('codingdude-token', token.trim())
}

export async function login(password) {
  const res = await fetch('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  })
  if (!res.ok) throw new Error('wrong password')
}

export async function call(path, options = {}) {
  const res = await fetch(`/api${path}`, { headers: { 'Content-Type': 'application/json' }, ...options })
  if (res.status === 401) {
    window.dispatchEvent(new Event('cd-unauthorized'))
    throw new Error('not logged in')
  }
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${await res.text()}`)
  return res.json()
}

export const api = {
  createSession: (workdir, title = null) =>
    call('/sessions', { method: 'POST', body: JSON.stringify({ workdir, title }) }),
  listSessions: (workdir) => call(`/sessions?workdir=${encodeURIComponent(workdir)}`),
  getMessages: (sessionId) => call(`/sessions/${sessionId}/messages`),
  startRun: (sessionId, prompt, model = null, yolo = false) =>
    call(`/sessions/${sessionId}/runs`, {
      method: 'POST',
      body: JSON.stringify({ prompt, model, yolo }),
    }),
  cancelRun: (runId) => call(`/runs/${runId}`, { method: 'DELETE' }),
  approve: (runId, decision) =>
    call(`/runs/${runId}/approve`, { method: 'POST', body: JSON.stringify({ decision }) }),
  listMcp: (sessionId) => call(`/mcp?session_id=${sessionId}`),
  toggleMcp: (sessionId, name, disabled) =>
    call(`/mcp/${encodeURIComponent(name)}/toggle?session_id=${sessionId}`, {
      method: 'POST',
      body: JSON.stringify({ disabled }),
    }),
  eventStreamUrl: (runId) =>
    `/api/runs/${runId}/events?token=${encodeURIComponent(getToken())}`,
}
