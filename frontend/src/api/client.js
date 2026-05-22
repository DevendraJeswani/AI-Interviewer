const BASE = '/session'

async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  startSession: (payload) =>
    request(`${BASE}/start`, { method: 'POST', body: JSON.stringify(payload) }),

  submitAnswer: (session_id, answer) =>
    request(`${BASE}/answer`, { method: 'POST', body: JSON.stringify({ session_id, answer }) }),

  getReport: (session_id) =>
    request(`${BASE}/report?session_id=${session_id}`),

  health: () => fetch('/health').then(r => r.json()),
}
