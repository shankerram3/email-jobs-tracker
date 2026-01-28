import React, { useState, useEffect, useCallback, useRef } from 'react'
import axios from 'axios'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
const API_URL = import.meta.env.VITE_API_URL || ''

function api() {
  const token = localStorage.getItem('token')
  const headers = token ? { Authorization: `Bearer ${token}` } : {}
  return axios.create({ baseURL: API_URL, headers })
}

function useAuth() {
  const [token, setToken] = useState(() => localStorage.getItem('token'))
  const [user, setUser] = useState(null)

  useEffect(() => {
    const hash = window.location.hash
    if (hash.startsWith('#token=')) {
      const t = hash.slice(7).split('&')[0]
      if (t) {
        localStorage.setItem('token', t)
        setToken(t)
        window.history.replaceState(null, '', '/')
      }
    }
  }, [])

  useEffect(() => {
    if (!token) {
      setUser(null)
      return
    }
    api()
      .get('/api/me')
      .then((r) => setUser(r.data))
      .catch(() => {
        localStorage.removeItem('token')
        setToken(null)
        setUser(null)
      })
  }, [token])

  const login = (newToken) => {
    localStorage.setItem('token', newToken)
    setToken(newToken)
  }
  const logout = () => {
    localStorage.removeItem('token')
    setToken(null)
    setUser(null)
  }
  return { token, user, login, logout, setToken }
}

function LoginPage({ onLogin }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const urlError = new URLSearchParams(window.location.search).get('error')

  useEffect(() => {
    if (urlError === 'access_denied') setError('Sign-in was cancelled or denied.')
  }, [urlError])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const { data } = await axios.post(API_URL + '/api/login', { email, password })
      onLogin(data.access_token)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  const googleUrl = API_URL + '/api/auth/google'

  return (
    <div className="login-page">
      <div className="login-card">
        <h1>Job Application Tracker</h1>
        <p className="login-subtitle">Sign in to continue</p>
        {error && <div className="error-msg">{error}</div>}
        <a href={googleUrl} className="google-btn">
          <span className="google-icon">G</span>
          Sign in with Google
        </a>
        <div className="login-divider">or</div>
        <form onSubmit={handleSubmit}>
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="login-input"
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="login-input"
          />
          <button type="submit" className="login-btn" disabled={loading}>
            {loading ? 'Signing in…' : 'Sign in with email'}
          </button>
        </form>
      </div>
    </div>
  )
}

function ProfileModal({ user, onClose }) {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)

  const handleChangePassword = async (e) => {
    e.preventDefault()
    setError('')
    setSuccess('')
    if (newPassword !== confirmPassword) {
      setError('New password and confirmation do not match')
      return
    }
    if (newPassword.length < 6) {
      setError('New password must be at least 6 characters')
      return
    }
    setLoading(true)
    try {
      await api().post('/api/me/change-password', {
        current_password: currentPassword,
        new_password: newPassword,
      })
      setSuccess('Password updated successfully.')
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to change password')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal profile-modal" onClick={(e) => e.stopPropagation()}>
        <h2>Profile</h2>
        <dl className="profile-dl">
          <dt>Email</dt>
          <dd>{user?.email || '—'}</dd>
          {user?.name && (
            <>
              <dt>Name</dt>
              <dd>{user.name}</dd>
            </>
          )}
        </dl>
        {user?.has_password && (
          <div className="profile-change-password">
            <h3>Change password</h3>
            {error && <div className="error-msg">{error}</div>}
            {success && <div className="success-msg">{success}</div>}
            <form onSubmit={handleChangePassword}>
              <input
                type="password"
                placeholder="Current password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                required
                className="login-input"
                autoComplete="current-password"
              />
              <input
                type="password"
                placeholder="New password (min 6 characters)"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                minLength={6}
                className="login-input"
                autoComplete="new-password"
              />
              <input
                type="password"
                placeholder="Confirm new password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                className="login-input"
                autoComplete="new-password"
              />
              <button type="submit" className="login-btn" disabled={loading}>
                {loading ? 'Updating…' : 'Update password'}
              </button>
            </form>
          </div>
        )}
        {user && !user.has_password && (
          <p className="profile-google-only">Signed in with Google. Password change is not available for this account.</p>
        )}
        <div className="modal-actions" style={{ marginTop: '1rem' }}>
          <button className="filter-btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  )
}

function TrackerApp({ logout, user }) {
  const [stats, setStats] = useState(null)
  const [showProfile, setShowProfile] = useState(false)
  const [applications, setApplications] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const limit = 50
  const [filter, setFilter] = useState('ALL')
  const [syncing, setSyncing] = useState(false)
  const [syncMode, setSyncMode] = useState('auto')
  const [syncFromDate, setSyncFromDate] = useState('')
  const [syncProgress, setSyncProgress] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [analytics, setAnalytics] = useState({ funnel: null, responseRate: null, timeToEvent: null, prediction: null })
  const [showAnalytics, setShowAnalytics] = useState(false)
  const [selectedApp, setSelectedApp] = useState(null)
  const eventSourceRef = useRef(null)

  const fetchStats = useCallback(async () => {
    try {
      const { data } = await api().get('/api/stats')
      setStats(data)
      setError(null)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to load stats')
    }
  }, [])

  const fetchApplications = useCallback(async () => {
    try {
      const params = { offset, limit }
      if (filter !== 'ALL') params.status = filter
      const { data } = await api().get('/api/applications', { params })
      setApplications(data.items || data)
      setTotal(data.total ?? (data.items || data).length)
      setError(null)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to load applications')
    }
  }, [filter, offset, limit])

  const fetchAnalytics = useCallback(async () => {
    try {
      const [funnel, responseRate, timeRejection, timeInterview, prediction] = await Promise.all([
        api().get('/api/analytics/funnel').then(r => r.data),
        api().get('/api/analytics/response-rate?group_by=company').then(r => r.data),
        api().get('/api/analytics/time-to-event?event=rejection').then(r => r.data),
        api().get('/api/analytics/time-to-event?event=interview').then(r => r.data),
        api().get('/api/analytics/prediction?limit=20').then(r => r.data),
      ])
      setAnalytics({
        funnel,
        responseRate,
        timeToEvent: { rejection: timeRejection, interview: timeInterview },
        prediction,
      })
    } catch {
      setAnalytics(a => ({ ...a }))
    }
  }, [])

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      await Promise.all([fetchStats(), fetchApplications()])
      setLoading(false)
    }
    load()
  }, [fetchStats, fetchApplications])

  const syncEmails = async () => {
    setSyncing(true)
    setError(null)
    setSyncProgress({ status: 'syncing', message: 'Starting…', processed: 0, total: 0 })
    try {
      const params = new URLSearchParams({ mode: syncMode })
      if (syncFromDate) params.set('after_date', syncFromDate)
      await api().post(`/api/sync-emails?${params.toString()}`)
      const t = localStorage.getItem('token')
      const es = new EventSource(`${API_URL}/api/sync-events${t ? `?token=${encodeURIComponent(t)}` : ''}`)
      eventSourceRef.current = es
      es.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data)
          setSyncProgress(data)
          if (data.status === 'idle') {
            es.close()
            eventSourceRef.current = null
            setSyncing(false)
            fetchStats()
            fetchApplications()
            if (data.error) setError(data.error)
          }
        } catch (_) {}
      }
      es.onerror = () => {
        es.close()
        eventSourceRef.current = null
        if (syncing) setSyncing(false)
      }
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Sync failed')
      setSyncing(false)
      setSyncProgress(null)
    }
  }

  useEffect(() => {
    if (!syncing) return
    const fallback = setInterval(async () => {
      try {
        const { data } = await api().get('/api/sync-status')
        setSyncProgress(data)
        if (data.status === 'idle') {
          setSyncing(false)
          await fetchStats()
          await fetchApplications()
          if (data.error) setError(data.error)
        }
      } catch (_) {}
    }, 1500)
    return () => clearInterval(fallback)
  }, [syncing, fetchStats, fetchApplications])

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) eventSourceRef.current.close()
    }
  }, [])

  if (loading && !stats) {
    return (
      <div className="app">
        <div className="loading">Loading…</div>
      </div>
    )
  }

  const chartData = stats
    ? [
        { name: 'Applied', count: stats.total_applications },
        { name: 'Interviews', count: stats.interviews },
        { name: 'Assessments', count: stats.assessments },
        { name: 'Rejections', count: stats.rejections },
        { name: 'Offers', count: stats.offers },
      ]
    : []

  return (
    <div className="app">
      <header>
        <h1>Job Application Tracker</h1>
        <div className="header-actions">
          <button className="filter-btn" onClick={() => setShowProfile(true)} title="Profile">
            Profile
          </button>
          <button className="filter-btn" onClick={logout} title="Sign out">
            Sign out
          </button>
          <select
            className="sync-mode-select"
            value={syncMode}
            onChange={(e) => setSyncMode(e.target.value)}
            disabled={syncing}
          >
            <option value="auto">Auto (full once, then incremental)</option>
            <option value="full">Full sync</option>
            <option value="incremental">Incremental only</option>
          </select>
          <input
            type="date"
            className="sync-from-date"
            value={syncFromDate}
            onChange={(e) => setSyncFromDate(e.target.value)}
            disabled={syncing}
            title="Sync from date (optional, for full sync)"
          />
          <button
            className="sync-btn"
            onClick={syncEmails}
            disabled={syncing}
          >
            {syncing ? 'Syncing…' : 'Sync Emails'}
          </button>
        </div>
      </header>

      {error && (
        <div className="error-msg">
          {error}
          {error.toLowerCase().includes('gmail') && error.toLowerCase().includes('auth') && (
            <div style={{ marginTop: '0.5rem' }}>
              <a href={`${API_URL}/api/gmail/auth`} className="link-btn" style={{ color: 'var(--accent)' }}>
                Authorize Gmail in browser →
              </a>
            </div>
          )}
        </div>
      )}

      {syncing && syncProgress && (
        <div className="sync-progress">
          <div className="sync-progress-header">
            <span className="sync-progress-message">{syncProgress.message}</span>
            {syncProgress.total > 0 && (
              <span className="sync-progress-count">
                {syncProgress.processed} / {syncProgress.total}
              </span>
            )}
          </div>
          <div className="sync-progress-bar-wrap">
            <div
              className="sync-progress-bar-fill"
              style={{
                width: syncProgress.total > 0
                  ? `${Math.round((syncProgress.processed / syncProgress.total) * 100)}%`
                  : '30%',
                animation: syncProgress.total === 0 ? 'sync-indeterminate 1.2s ease-in-out infinite' : 'none',
              }}
            />
          </div>
          {syncProgress.status === 'idle' && syncProgress.processed > 0 && (
            <div className="sync-progress-summary">
              Done: {syncProgress.created} new, {syncProgress.skipped} skipped, {syncProgress.errors} errors
            </div>
          )}
        </div>
      )}

      {stats && (
        <>
          <div className="stats-grid">
            <StatCard label="Total Applications" value={stats.total_applications} />
            <StatCard label="Interviews" value={stats.interviews} color="green" />
            <StatCard label="Assessments" value={stats.assessments} color="blue" />
            <StatCard label="Rejections" value={stats.rejections} color="red" />
            <StatCard label="Offers" value={stats.offers} color="amber" />
          </div>

          <div className="chart">
            <h2>Application breakdown</h2>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={chartData} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="name" stroke="var(--text-muted)" fontSize={12} />
                <YAxis stroke="var(--text-muted)" fontSize={12} />
                <Tooltip
                  contentStyle={{
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)',
                  }}
                  labelStyle={{ color: 'var(--text)' }}
                />
                <Legend />
                <Bar dataKey="count" fill="var(--accent)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      )}

      <div className="analytics-section">
        <button
          className="filter-btn"
          onClick={() => { setShowAnalytics(!showAnalytics); if (!analytics.funnel) fetchAnalytics(); }}
        >
          {showAnalytics ? 'Hide' : 'Show'} Analytics
        </button>
        {showAnalytics && analytics.funnel && (
          <div className="analytics-panels">
            <div className="analytics-panel">
              <h3>Funnel</h3>
              <ul>
                {analytics.funnel.funnel?.map((s) => (
                  <li key={s.stage}>{s.stage}: {s.count} ({s.pct}%)</li>
                ))}
              </ul>
            </div>
            <div className="analytics-panel">
              <h3>Response rate (top companies)</h3>
              <ul className="compact">
                {analytics.responseRate?.items?.slice(0, 10).map((r) => (
                  <li key={r.name}>{r.name}: {r.responded}/{r.applied} ({r.rate * 100}%)</li>
                ))}
              </ul>
            </div>
            <div className="analytics-panel">
              <h3>Time to event</h3>
              <p>Rejection: median {analytics.timeToEvent?.rejection?.median_days ?? '—'} days, avg {analytics.timeToEvent?.rejection?.avg_days ?? '—'} (n={analytics.timeToEvent?.rejection?.sample_size ?? 0})</p>
              <p>Interview: median {analytics.timeToEvent?.interview?.median_days ?? '—'} days, avg {analytics.timeToEvent?.interview?.avg_days ?? '—'} (n={analytics.timeToEvent?.interview?.sample_size ?? 0})</p>
            </div>
            <div className="analytics-panel">
              <h3>Success prediction (MVP)</h3>
              <ul className="compact">
                {analytics.prediction?.items?.slice(0, 10).map((a) => (
                  <li key={a.application_id}>{a.company_name}: {(a.probability * 100).toFixed(1)}%</li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </div>

      <div className="filters">
        <button
          className={`filter-btn ${filter === 'ALL' ? 'active' : ''}`}
          onClick={() => setFilter('ALL')}
        >
          All
        </button>
        <button
          className={`filter-btn ${filter === 'INTERVIEW_REQUEST' ? 'active' : ''}`}
          onClick={() => setFilter('INTERVIEW_REQUEST')}
        >
          Interviews
        </button>
        <button
          className={`filter-btn ${filter === 'ASSESSMENT' ? 'active' : ''}`}
          onClick={() => setFilter('ASSESSMENT')}
        >
          Assessments
        </button>
        <button
          className={`filter-btn ${filter === 'REJECTION' ? 'active' : ''}`}
          onClick={() => setFilter('REJECTION')}
        >
          Rejections
        </button>
        <button
          className={`filter-btn ${filter === 'OFFER' ? 'active' : ''}`}
          onClick={() => setFilter('OFFER')}
        >
          Offers
        </button>
      </div>

      <div className="applications-list">
        <h2>Applications</h2>
        <div className="pagination-bar">
          <button
            className="filter-btn"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - limit))}
          >
            Previous
          </button>
          <span className="pagination-info">
            {offset + 1}–{Math.min(offset + limit, total)} of {total}
          </span>
          <button
            className="filter-btn"
            disabled={offset + limit >= total}
            onClick={() => setOffset(offset + limit)}
          >
            Next
          </button>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Company</th>
                <th>Job title</th>
                <th>Location</th>
                <th>Status</th>
                <th>Date</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {applications.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ color: 'var(--text-muted)', padding: '2rem' }}>
                    No applications yet. Click “Sync Emails” to pull from Gmail.
                  </td>
                </tr>
              ) : (
                applications.map((app) => (
                  <tr key={app.id}>
                    <td>{app.company_name}</td>
                    <td>{app.job_title || app.position || '—'}</td>
                    <td>{app.location || '—'}</td>
                    <td>
                      <span className={`badge ${(app.category || 'other').toLowerCase()}`}>
                        {app.category || 'Other'}
                      </span>
                    </td>
                    <td>
                      {app.received_date
                        ? new Date(app.received_date).toLocaleDateString()
                        : '—'}
                    </td>
                    <td>
                      <button
                        className="link-btn"
                        onClick={() => setSelectedApp(app)}
                      >
                        Details
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {selectedApp && (
        <div className="modal-overlay" onClick={() => setSelectedApp(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Application details</h2>
            <dl>
              <dt>Company</dt><dd>{selectedApp.company_name}</dd>
              <dt>Job title</dt><dd>{selectedApp.job_title || selectedApp.position || '—'}</dd>
              <dt>Location</dt><dd>{selectedApp.location || '—'}</dd>
              <dt>Salary</dt><dd>{selectedApp.salary_min != null || selectedApp.salary_max != null
                ? [selectedApp.salary_min, selectedApp.salary_max].filter(Boolean).map((n) => `$${n}`).join(' – ')
                : '—'}</dd>
              <dt>Category</dt><dd>{selectedApp.category}</dd>
              <dt>Subject</dt><dd>{selectedApp.email_subject}</dd>
              <dt>Received</dt><dd>{selectedApp.received_date ? new Date(selectedApp.received_date).toLocaleString() : '—'}</dd>
            </dl>
            <div className="modal-actions">
              <button className="filter-btn" onClick={() => api().post(`/api/applications/${selectedApp.id}/schedule`, {}).then(() => setSelectedApp(null))}>
                Schedule
              </button>
              <button className="filter-btn" onClick={() => api().post(`/api/applications/${selectedApp.id}/respond`, {}).then(() => setSelectedApp(null))}>
                Respond
              </button>
              <button className="filter-btn" onClick={() => setSelectedApp(null)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {showProfile && (
        <ProfileModal
          user={user}
          onClose={() => setShowProfile(false)}
        />
      )}
    </div>
  )
}

function StatCard({ label, value, color = 'blue' }) {
  return (
    <div className={`stat-card ${color}`}>
      <h3>{label}</h3>
      <div className="value">{value}</div>
    </div>
  )
}

function App() {
  const { token, user, login, logout } = useAuth()
  if (!token && !user) {
    return <LoginPage onLogin={login} />
  }
  if (!user) {
    return (
      <div className="app">
        <div className="loading">Checking sign-in…</div>
      </div>
    )
  }
  return <TrackerApp logout={logout} user={user} />
}

export default App
