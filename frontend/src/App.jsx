import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import DecideView from './components/DecideView.jsx'
import ProfileView from './components/ProfileView.jsx'
import HistoryView from './components/HistoryView.jsx'

const TABS = [
  { id: 'decide', label: 'Decide' },
  { id: 'profile', label: 'Profile' },
  { id: 'history', label: 'History' },
]

export default function App() {
  const [users, setUsers] = useState([])
  const [userId, setUserId] = useState(null)
  const [tab, setTab] = useState('decide')
  const [apiError, setApiError] = useState(null)

  useEffect(() => {
    api.listUsers()
      .then((u) => { setUsers(u); setUserId(u[0]) })
      .catch((e) => setApiError(e.message))
  }, [])

  return (
    <div className="control-room">
      <header className="control-room-header">
        <div className="wordmark">
          AFFORD <span className="wordmark-accent">IQ</span>
        </div>
        <nav className="tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`tab ${tab === t.id ? 'active' : ''}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <div className="user-select">
          <label>USER</label>
          <select value={userId || ''} onChange={(e) => setUserId(e.target.value)}>
            {users.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>
      </header>

      <main className="control-room-main">
        {apiError && (
          <div className="form-error">
            <span>
              Could not reach the API ({apiError}). Is the backend running? See README for
              "python3 backend/api.py".
            </span>
            <button
              className="form-error-retry"
              onClick={() => {
                setApiError(null)
                api.listUsers().then((u) => { setUsers(u); setUserId(u[0]) }).catch((e) => setApiError(e.message))
              }}
            >
              Retry
            </button>
          </div>
        )}
        {!apiError && userId && tab === 'decide' && <DecideView userId={userId} />}
        {!apiError && userId && tab === 'profile' && <ProfileView userId={userId} />}
        {!apiError && tab === 'history' && <HistoryView />}
      </main>

      <footer className="control-room-footer">
        Deterministic financial-decision engine · no LLM calls at runtime · demo data is synthetic
      </footer>
    </div>
  )
}
