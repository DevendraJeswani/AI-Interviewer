const API_BASE = import.meta.env.VITE_API_URL || ''
const BASE = `${API_BASE}/session`

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

  /** Retrieve a stored report by its share ID (for bookmark / share links). */
  getReportById: (report_id) =>
    request(`${API_BASE}/report/${report_id}`),

  endSession: (session_id) =>
    request(`${BASE}/end`, { method: 'POST', body: JSON.stringify({ session_id }) }),

  /**
   * Download the PDF for a session.
   * Returns a Blob so the caller can create an object URL.
   */
  downloadPdf: async (session_id) => {
    const res = await fetch(`${BASE}/report/pdf?session_id=${session_id}`)
    if (!res.ok) {
      const text = await res.text()
      throw new Error(text || `HTTP ${res.status}`)
    }
    return res.blob()
  },

  /**
   * Download the PDF by report_id (works even when session is gone).
   */
  downloadPdfById: async (report_id) => {
    const res = await fetch(`${API_BASE}/report/${report_id}/pdf`)
    if (!res.ok) {
      const text = await res.text()
      throw new Error(text || `HTTP ${res.status}`)
    }
    return res.blob()
  },

  health: () => fetch(`${API_BASE}/health`).then(r => r.json()),
}
