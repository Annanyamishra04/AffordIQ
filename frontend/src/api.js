const BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')

async function handle(res) {
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.error || `Request failed (${res.status})`)
  }
  return data
}

export const api = {
  listUsers: () => fetch(`${BASE}/users`).then(handle),
  getProfile: (userId) => fetch(`${BASE}/profile/${userId}`).then(handle),
  getForecast: (userId) => fetch(`${BASE}/forecast/${userId}`).then(handle),
  getHistory: () => fetch(`${BASE}/history`).then(handle),
  postDecision: (payload) =>
    fetch(`${BASE}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(handle),
  postWhatIf: (payload) =>
    fetch(`${BASE}/what-if`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(handle),
}
