// Thin API client for the codingdude server. Token lives in localStorage.

export function getToken() {
  return localStorage.getItem('codingdude-token') || ''
}

export function setToken(token) {
  localStorage.setItem('codingdude-token', token)
}

function headers() {
  return { Authorization: `Bearer ${getToken()}`, 'Content-Type': 'application/json' }
}

async function call(path, options = {}) {
  const res = await fetch(`/api${path}`, { headers: headers(), ...options })
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
  // EventSource cannot send headers; the server accepts the token as a query param.
  eventStreamUrl: (runId) => `/api/runs/${runId}/events?token=${encodeURIComponent(getToken())}`,
}
