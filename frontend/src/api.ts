// Typed API client for the codingdude server.
// Auth: the server sets an HttpOnly session cookie at /login; all requests
// send it automatically (same-origin).

export interface SessionInfo {
  session_id: string
  workdir: string
  created_at: string
  updated_at: string
  title: string | null
}

export interface TraceEvent {
  ts?: string
  type: string
  [key: string]: unknown
}

export interface UsageTotals {
  requests: number
  input_tokens: number
  output_tokens: number
  cost_usd: number | null
}

export interface ModelsInfo {
  default: string
  models: Record<string, string | null>
}

export interface Project {
  id: number
  name: string
  workdir: string
}

export interface McpServer {
  name: string
  config: { command: string; args?: string[] }
  disabled: boolean
}

export interface MemoryEntry {
  id: number
  scope: 'global' | 'workdir'
  workdir: string | null
  content: string
  created_at: string
}

export type ApprovalDecision = 'approve' | 'pattern' | 'deny'

export async function call<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (res.status === 401) {
    window.dispatchEvent(new Event('cd-unauthorized'))
    throw new Error('not logged in')
  }
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${await res.text()}`)
  return res.json()
}

export async function login(password: string): Promise<void> {
  const res = await fetch('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  })
  if (!res.ok) throw new Error('wrong password')
}

// Passwordless: the server grants a session when the browser proves the page
// is local and same-origin (Sec-Fetch-Site + Host checks server-side).
export async function authLocal(): Promise<boolean> {
  try {
    const res = await fetch('/api/auth/local', { method: 'POST' })
    return res.ok
  } catch {
    return false
  }
}

export async function checkAuth(): Promise<boolean> {
  try {
    const res = await fetch('/api/auth/check')
    return res.ok
  } catch {
    return false
  }
}

export function getToken(): string {
  return (localStorage.getItem('codingdude-token') || '').trim()
}

export const api = {
  createSession: (workdir: string, title: string | null = null): Promise<{ session_id: string }> =>
    call<{ session_id: string }>('/sessions', { method: 'POST', body: JSON.stringify({ workdir, title }) }),
  listProjects: (): Promise<Project[]> => call('/projects') as Promise<Project[]>,
  addProject: (name: string, workdir: string): Promise<Project> =>
    call('/projects', { method: 'POST', body: JSON.stringify({ name, workdir }) }) as Promise<Project>,
  deleteProject: (id: number): Promise<unknown> =>
    call(`/projects/${id}`, { method: 'DELETE' }),
  listSessions: (workdir: string): Promise<SessionInfo[]> =>
    call<SessionInfo[]>(`/sessions?workdir=${encodeURIComponent(workdir)}`),
  getMessages: (sessionId: string) => call(`/sessions/${sessionId}/messages`),
  listModels: (): Promise<ModelsInfo> => call<ModelsInfo>('/models'),
  startRun: (
    sessionId: string,
    prompt: string,
    model: string | null = null,
    fixLoop = false,
    imageB64: string | null = null,
    yolo = false,
  ): Promise<{ run_id: string }> =>
    call<{ run_id: string }>(`/sessions/${sessionId}/runs`, {
      method: 'POST',
      body: JSON.stringify({ prompt, model, fix_loop: fixLoop, image_b64: imageB64, yolo }),
    }),
  cancelRun: (runId: string): Promise<unknown> => call(`/runs/${runId}`, { method: 'DELETE' }),
  approve: (runId: string, decision: ApprovalDecision): Promise<unknown> =>
    call(`/runs/${runId}/approve`, { method: 'POST', body: JSON.stringify({ decision }) }),
  listMcp: (sessionId: string): Promise<McpServer[]> =>
    call<McpServer[]>(`/mcp?session_id=${sessionId}`),
  toggleMcp: (sessionId: string, name: string, disabled: boolean): Promise<unknown> =>
    call(`/mcp/${encodeURIComponent(name)}/toggle?session_id=${sessionId}`, {
      method: 'POST',
      body: JSON.stringify({ disabled }),
    }),
  activeRuns: (): Promise<{ run_id: string; session_id: string }[]> =>
    call('/runs/active') as Promise<{ run_id: string; session_id: string }[]>,
  eventStreamUrl: (runId: string) =>
    `/api/runs/${runId}/events?token=${encodeURIComponent(getToken())}`,
}
