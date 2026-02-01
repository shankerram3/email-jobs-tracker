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
    if (urlError === 'invalid_state' || urlError === 'missing_state') {
      setError('This sign-in link was used or expired. Please try "Continue with Google" again.')
    }
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

  const MailIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>
  )
  const ChromeIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="4"/><line x1="21.17" x2="12" y1="8" y2="12"/><line x1="3.95" x2="6.88" y1="6.06" y2="14"/><line x1="10.88" x2="17.05" y1="21.94" y2="14"/></svg>
  )

  return (
    <div className="login-page">
      <div className="login-wrap">
        <div className="login-brand">
          <div className="login-logo">
            <MailIcon />
          </div>
          <h1>Job Application Tracker</h1>
          <p className="login-subtitle">Track your job applications from your inbox</p>
        </div>
        <div className="login-card">
          {error && <div className="error-msg">{error}</div>}
          <a href={googleUrl} className="google-btn">
            <ChromeIcon />
            <span>Continue with Google</span>
          </a>
          <div className="login-divider"><span>Or continue with email</span></div>
          <form onSubmit={handleSubmit} className="login-form">
            <label htmlFor="login-email" className="login-form-label">Email address</label>
            <input
              id="login-email"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="login-input"
            />
            <label htmlFor="login-password" className="login-form-label">Password</label>
            <input
              id="login-password"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="login-input"
            />
            <button type="submit" className="login-btn" disabled={loading}>
              {loading ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        </div>
        <p className="login-footer-note">By signing in, you agree to sync your job application emails</p>
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
        <div className="profile-modal-header">
          <div className="profile-modal-header-left">
            <div className="profile-modal-icon-wrap">
              <IconUser />
            </div>
            <h2>Profile</h2>
          </div>
          <button type="button" className="profile-modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <div className="profile-info-block">
          <div className="profile-info-row">
            <span className="profile-info-label">Email</span>
            <span className="profile-info-value">{user?.email || '—'}</span>
          </div>
          {user?.name && (
            <div className="profile-info-row">
              <span className="profile-info-label">Name</span>
              <span className="profile-info-value">{user.name}</span>
            </div>
          )}
        </div>

        {user?.has_password && (
          <div className="profile-change-password">
            <h3 className="profile-change-password-title">Change password</h3>
            {error && <div className="error-msg">{error}</div>}
            {success && <div className="success-msg">{success}</div>}
            <form onSubmit={handleChangePassword} className="profile-change-password-form">
              <input
                type="password"
                placeholder="Current password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                required
                className="login-input profile-input"
                autoComplete="current-password"
              />
              <input
                type="password"
                placeholder="New password (min 6 characters)"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                minLength={6}
                className="login-input profile-input"
                autoComplete="new-password"
              />
              <input
                type="password"
                placeholder="Confirm new password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                className="login-input profile-input"
                autoComplete="new-password"
              />
              <button type="submit" className="login-btn profile-submit-btn" disabled={loading}>
                {loading ? 'Updating…' : 'Update password'}
              </button>
            </form>
          </div>
        )}
        {user && !user.has_password && (
          <p className="profile-google-only">
            Signed in with Google. Password change is not available for this account.
          </p>
        )}

        <div className="profile-modal-actions">
          <button type="button" className="filter-btn profile-close-btn" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

const IconDashboard = () => <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/></svg>
const IconBriefcase = () => <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect width="20" height="14" x="2" y="7" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>
const IconBarChart = () => <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" x2="12" y1="20" y2="10"/><line x1="18" x2="18" y1="20" y2="4"/><line x1="6" x2="6" y1="20" y2="16"/></svg>
const IconUser = () => <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
const IconLogOut = () => <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" x2="9" y1="12" y2="12"/></svg>
const IconMail = () => <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>
const IconAlertCircle = () => <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg>
const IconRefresh = () => <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 16h5v5"/></svg>

// Confidence Badge Component
function ConfidenceBadge({ confidence }) {
  if (confidence == null) return null
  const pct = Math.round(confidence * 100)
  let colorClass = 'low'
  if (pct >= 85) colorClass = 'high'
  else if (pct >= 70) colorClass = 'medium'
  return (
    <span className={`confidence-badge ${colorClass}`} title={`Classification confidence: ${pct}%`}>
      {pct}%
    </span>
  )
}

// Action Item Component
function ActionItem({ item }) {
  return (
    <li className="action-item">
      <IconAlertCircle />
      <span>{item}</span>
    </li>
  )
}

function TrackerApp({ logout, user }) {
  const [view, setView] = useState('dashboard')
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
  const [syncToDate, setSyncToDate] = useState('')
  const [syncProgress, setSyncProgress] = useState(null)

  const getSyncProgressDetail = (progress) => {
    if (!progress) return { headline: '', meta: '', hint: '' }
    const baseMessage = progress.message || 'Syncing inbox'
    const hasTotal = progress.total > 0
    const percent = hasTotal
      ? Math.min(100, Math.round((progress.processed / progress.total) * 100))
      : null
    const meta = hasTotal
      ? `${percent}% • ${progress.processed} of ${progress.total}`
      : 'Estimating inbox size…'
    let hint = 'Working through your latest updates.'
    if (baseMessage.toLowerCase().includes('connecting')) {
      hint = 'Warming up the connection and preparing the pipeline.'
    } else if (baseMessage.toLowerCase().includes('fetching')) {
      hint = 'Pulling new messages and deduplicating results.'
    } else if (baseMessage.toLowerCase().includes('classifying')) {
      hint = 'Sorting stages and extracting details.'
    }
    return {
      headline: baseMessage,
      meta,
      hint,
    }
  }
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [analytics, setAnalytics] = useState({ funnel: null, responseRate: null, timeToEvent: null, prediction: null })
  const [showAnalytics, setShowAnalytics] = useState(true)
  const [selectedApp, setSelectedApp] = useState(null)
  const [actionRequired, setActionRequired] = useState([])
  const [langgraphAnalytics, setLanggraphAnalytics] = useState(null)
  const [reprocessing, setReprocessing] = useState(false)
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

  const fetchActionRequired = useCallback(async () => {
    try {
      const { data } = await api().get('/api/langgraph/action-required?limit=10')
      setActionRequired(data || [])
    } catch {
      setActionRequired([])
    }
  }, [])

  const fetchLanggraphAnalytics = useCallback(async () => {
    try {
      const { data } = await api().get('/api/langgraph/analytics')
      setLanggraphAnalytics(data)
    } catch {
      setLanggraphAnalytics(null)
    }
  }, [])

  const reprocessApplication = async (appId) => {
    setReprocessing(true)
    try {
      const { data } = await api().post(`/api/langgraph/reprocess/${appId}`)
      setSelectedApp(data)
      // Refresh lists
      await Promise.all([fetchApplications(), fetchActionRequired()])
    } catch (err) {
      setError(err.response?.data?.detail || 'Reprocess failed')
    } finally {
      setReprocessing(false)
    }
  }

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      await Promise.all([fetchStats(), fetchApplications(), fetchActionRequired()])
      setLoading(false)
    }
    load()
  }, [fetchStats, fetchApplications, fetchActionRequired])

  const syncEmails = async () => {
    setSyncing(true)
    setError(null)
    setSyncProgress({ status: 'syncing', message: 'Starting…', processed: 0, total: 0 })
    try {
      const params = new URLSearchParams({ mode: syncMode })
      if (syncFromDate) params.set('after_date', syncFromDate)
      if (syncToDate) params.set('before_date', syncToDate)
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
      <div className="app-layout">
        <aside className="app-sidebar">
          <div className="app-sidebar-header">
            <div className="app-sidebar-logo">
              <div className="app-sidebar-logo-icon"><IconMail /></div>
              <div className="app-sidebar-logo-text">
                <h1>Job Tracker</h1>
                <p>Track your applications</p>
              </div>
            </div>
          </div>
        </aside>
        <main className="app-main">
          <div className="loading">Loading…</div>
        </main>
      </div>
    )
  }

  const chartData = stats
    ? (() => {
        const total = stats.total_applications || 0
        const raw = [
          { name: 'Applied', count: stats.total_applications },
          { name: 'Interviews', count: stats.interviews },
          { name: 'Screening', count: stats.screening_requests ?? 0 },
          { name: 'Assessments', count: stats.assessments },
          { name: 'Rejections', count: stats.rejections },
          { name: 'Offers', count: stats.offers },
        ]
        return raw.map((d) => ({
          ...d,
          pct: total > 0 ? Math.round((d.count / total) * 1000) / 10 : 0,
        }))
      })()
    : []

  const recentApplications = applications.slice(0, 5)

  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: IconDashboard },
    { id: 'applications', label: 'Applications', icon: IconBriefcase },
    { id: 'analytics', label: 'Analytics', icon: IconBarChart },
  ]

  return (
    <div className="app-layout">
      <aside className="app-sidebar">
        <div className="app-sidebar-header">
          <div className="app-sidebar-logo">
            <div className="app-sidebar-logo-icon"><IconMail /></div>
            <div className="app-sidebar-logo-text">
              <h1>Job Tracker</h1>
              <p>Track your applications</p>
            </div>
          </div>
        </div>
        <nav className="app-sidebar-nav">
          {navItems.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              className={`app-sidebar-nav-btn ${view === id ? 'active' : ''}`}
              onClick={() => { setView(id); if (id === 'analytics' && !analytics.funnel) { fetchAnalytics(); fetchLanggraphAnalytics(); } }}
            >
              <Icon />
              {label}
            </button>
          ))}
          <button
            type="button"
            className="app-sidebar-nav-btn"
            onClick={() => setShowProfile(true)}
          >
            <IconUser />
            Profile
          </button>
        </nav>
        <div className="app-sidebar-user">
          <div className="app-sidebar-user-info">
            <div className="app-sidebar-user-avatar"><IconUser /></div>
            <div className="app-sidebar-user-details">
              <p className="app-sidebar-user-name">{user?.name || user?.email || 'User'}</p>
              <p className="app-sidebar-user-email">{user?.email}</p>
            </div>
          </div>
          <button type="button" className="app-sidebar-signout" onClick={logout}>
            <IconLogOut />
            Sign out
          </button>
        </div>
      </aside>

      <main className="app-main">
        <div className="app-main-header">
          <h1>{view === 'dashboard' ? 'Dashboard' : view === 'applications' ? 'Applications' : 'Analytics'}</h1>
          <p>{view === 'dashboard' ? 'Overview of your job applications' : view === 'applications' ? 'Browse and filter your applications' : 'Funnel, response rates and predictions'}</p>
        </div>

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
        (() => {
          const details = getSyncProgressDetail(syncProgress)
          return (
        <div className="sync-progress">
          <div className="sync-progress-header">
            <span className="sync-progress-message">{details.headline}</span>
            {syncProgress.total > 0 && (
              <span className="sync-progress-count">
                {syncProgress.processed} / {syncProgress.total}
              </span>
            )}
          </div>
          <div className="sync-progress-meta">{details.meta}</div>
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
          <div className="sync-progress-hint">{details.hint}</div>
          {syncProgress.status === 'idle' && syncProgress.processed > 0 && (
            <div className="sync-progress-summary">
              Done: {syncProgress.created} new, {syncProgress.skipped} skipped, {syncProgress.errors} errors
            </div>
          )}
        </div>
          )
        })()
        )}

        {view === 'dashboard' && (
          <>
            <div className="header-actions" style={{ marginBottom: '1.5rem', flexWrap: 'wrap', gap: '0.75rem' }}>
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
              <label htmlFor="sync-from-date" className="sync-date-label">From</label>
              <input
                id="sync-from-date"
                type="date"
                className="sync-from-date"
                value={syncFromDate}
                onChange={(e) => setSyncFromDate(e.target.value)}
                disabled={syncing}
              />
              <span className="sync-date-sep">–</span>
              <label htmlFor="sync-to-date" className="sync-date-label">To</label>
              <input
                id="sync-to-date"
                type="date"
                className="sync-to-date"
                value={syncToDate}
                onChange={(e) => setSyncToDate(e.target.value)}
                disabled={syncing}
              />
              <button className="sync-btn" onClick={syncEmails} disabled={syncing}>
                {syncing ? 'Syncing…' : 'Sync Emails'}
              </button>
            </div>
            {stats && (
        <section className="dashboard-section" aria-label="Overview">
          <div className="stats-grid">
            <StatCard
              label="Total Applications"
              value={stats.total_applications}
              onClick={() => { setView('applications'); setFilter('ALL'); setOffset(0); }}
              active={filter === 'ALL'}
            />
            <StatCard
              label="Interviews"
              value={stats.interviews}
              color="green"
              onClick={() => { setView('applications'); setFilter('INTERVIEW_OR_SCREENING'); setOffset(0); }}
              active={filter === 'INTERVIEW_OR_SCREENING'}
            />
            <StatCard
              label="Screening"
              value={stats.screening_requests ?? 0}
              color="green"
              onClick={() => { setView('applications'); setFilter('SCREENING'); setOffset(0); }}
              active={filter === 'SCREENING'}
            />
            <StatCard
              label="Assessments"
              value={stats.assessments}
              color="purple"
              onClick={() => { setView('applications'); setFilter('ASSESSMENT'); setOffset(0); }}
              active={filter === 'ASSESSMENT'}
            />
            <StatCard
              label="Rejections"
              value={stats.rejections}
              color="red"
              onClick={() => { setView('applications'); setFilter('REJECTED'); setOffset(0); }}
              active={filter === 'REJECTED'}
            />
            <StatCard
              label="Offers"
              value={stats.offers}
              color="amber"
              onClick={() => { setView('applications'); setFilter('OFFER'); setOffset(0); }}
              active={filter === 'OFFER'}
            />
          </div>

          <div className="chart">
            <h2>Application breakdown (normalized %)</h2>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={chartData} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="name" stroke="var(--text-muted)" fontSize={12} />
                <YAxis
                  stroke="var(--text-muted)"
                  fontSize={12}
                  domain={[0, 100]}
                  tickFormatter={(v) => `${v}%`}
                />
                <Tooltip
                  contentStyle={{
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-lg)',
                    padding: 'var(--space-3) var(--space-4)',
                  }}
                  labelStyle={{ color: 'var(--text)' }}
                  formatter={(value, name, props) => [`${props.payload.count} (${value}%)`, props.payload.name]}
                  labelFormatter={() => ''}
                />
                <Legend />
                <Bar
                  dataKey="pct"
                  fill="var(--accent)"
                  radius={[4, 4, 0, 0]}
                  name="% of total"
                  onClick={(data) => {
                    const category = NAME_TO_CATEGORY[data.name]
                    if (category != null) {
                      setView('applications')
                      setFilter(category)
                      setOffset(0)
                    }
                  }}
                  cursor="pointer"
                />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Action Required Section */}
          {actionRequired.length > 0 && (
            <section className="action-required-section" aria-label="Action required">
              <div className="action-required-header">
                <div className="action-required-title">
                  <IconAlertCircle />
                  <h2>Action Required</h2>
                  <span className="action-required-count">{actionRequired.length}</span>
                </div>
              </div>
              <div className="action-required-list">
                {actionRequired.slice(0, 5).map((app) => (
                  <button
                    key={app.id}
                    type="button"
                    className="action-required-item"
                    onClick={() => setSelectedApp(app)}
                  >
                    <div className="action-required-main">
                      <div className="action-required-company">{app.company_name}</div>
                      <div className="action-required-position">
                        {app.position || 'Untitled role'}
                        {app.position_level && <span className="position-level">{app.position_level}</span>}
                      </div>
                      <div className="action-required-stage">
                        <span className={`stage-badge ${(app.application_stage || 'other').toLowerCase()}`}>
                          {app.application_stage || 'Other'}
                        </span>
                        <ConfidenceBadge confidence={app.confidence} />
                      </div>
                    </div>
                    <div className="action-required-actions">
                      {app.action_items && app.action_items.length > 0 && (
                        <ul className="action-items-preview">
                          {app.action_items.slice(0, 2).map((item, i) => (
                            <li key={i}>{item}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            </section>
          )}

          <section className="recent-applications" aria-label="Recent applications">
            <div className="recent-applications-header">
              <h2>Recent Applications</h2>
              <button
                type="button"
                className="link-btn"
                onClick={() => setView('applications')}
              >
                View all
              </button>
            </div>
            <div className="recent-applications-list">
              {recentApplications.length === 0 ? (
                <p className="recent-applications-empty">No applications yet. Sync emails to load applications.</p>
              ) : (
                recentApplications.map((app) => (
                  <button
                    key={app.id}
                    type="button"
                    className="recent-applications-item"
                    onClick={() => setSelectedApp(app)}
                  >
                    <div className="recent-applications-main">
                      <div className="recent-applications-title">
                        {app.job_title || app.position || 'Untitled role'}
                        {app.requires_action && (
                          <span className="requires-action-indicator" title="Requires action">!</span>
                        )}
                      </div>
                      <div className="recent-applications-meta">
                        {app.company_name}
                        {app.location ? ` · ${app.location}` : ''}
                      </div>
                      <div className="recent-applications-badges">
                        <span className={`badge ${(app.category || 'other').toLowerCase().replace(/_/g, '-')}`}>
                          {categoryLabel(app.category)}
                        </span>
                        <ConfidenceBadge confidence={app.confidence} />
                      </div>
                    </div>
                    <div className="recent-applications-side">
                      <div className="recent-applications-date">
                        {app.received_date
                          ? new Date(app.received_date).toLocaleDateString()
                          : '—'}
                      </div>
                    </div>
                  </button>
                ))
              )}
            </div>
          </section>
        </section>
            )}
          </>
        )}

        {view === 'analytics' && (
          <div className="analytics-section">
            {!analytics.funnel && !langgraphAnalytics && (
              <button className="filter-btn" onClick={() => { fetchAnalytics(); fetchLanggraphAnalytics(); }}>Load Analytics</button>
            )}

            {/* LangGraph Classification Analytics */}
            {langgraphAnalytics && (
              <div className="langgraph-analytics">
                <h2 className="analytics-section-title">AI Classification Analytics</h2>
                <div className="langgraph-stats-row">
                  <div className="langgraph-stat">
                    <div className="langgraph-stat-value">{langgraphAnalytics.total_processed}</div>
                    <div className="langgraph-stat-label">Total Processed</div>
                  </div>
                  <div className="langgraph-stat">
                    <div className="langgraph-stat-value action">{langgraphAnalytics.action_required_count}</div>
                    <div className="langgraph-stat-label">Action Required</div>
                  </div>
                  <div className="langgraph-stat">
                    <div className="langgraph-stat-value">{langgraphAnalytics.avg_confidence != null ? `${Math.round(langgraphAnalytics.avg_confidence * 100)}%` : '—'}</div>
                    <div className="langgraph-stat-label">Avg Confidence</div>
                  </div>
                </div>

                <div className="analytics-panels">
                  <div className="analytics-panel">
                    <h3>By Category</h3>
                    <ul className="compact">
                      {langgraphAnalytics.by_category?.slice(0, 10).map((cat) => (
                        <li key={cat.category}>
                          {categoryLabel(cat.category)}: {cat.count}
                          {cat.avg_confidence != null && <span className="cat-confidence"> ({Math.round(cat.avg_confidence * 100)}%)</span>}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="analytics-panel">
                    <h3>By Stage</h3>
                    <ul className="compact">
                      {Object.entries(langgraphAnalytics.by_stage || {}).map(([stage, count]) => (
                        <li key={stage}>{stage}: {count}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            )}

            {analytics.funnel && (
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
              <p>Interview / screening: median {analytics.timeToEvent?.interview?.median_days ?? '—'} days, avg {analytics.timeToEvent?.interview?.avg_days ?? '—'} (n={analytics.timeToEvent?.interview?.sample_size ?? 0})</p>
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
        )}

        {view === 'applications' && (
          <>
      <div className="filters">
        <button
          className={`filter-btn ${filter === 'ALL' ? 'active' : ''}`}
          onClick={() => setFilter('ALL')}
        >
          All
        </button>
        <button
          className={`filter-btn ${filter === 'INTERVIEW_OR_SCREENING' ? 'active' : ''}`}
          onClick={() => setFilter('INTERVIEW_OR_SCREENING')}
        >
          Interview / screening
        </button>
        <button
          className={`filter-btn ${filter === 'SCREENING' ? 'active' : ''}`}
          onClick={() => setFilter('SCREENING')}
        >
          Screening
        </button>
        <button
          className={`filter-btn ${filter === 'ASSESSMENT' ? 'active' : ''}`}
          onClick={() => setFilter('ASSESSMENT')}
        >
          Assessments
        </button>
        <button
          className={`filter-btn ${filter === 'REJECTED' ? 'active' : ''}`}
          onClick={() => setFilter('REJECTED')}
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

      <section className="applications-list" aria-label="Applications">
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
                <th>Stage</th>
                <th>Category</th>
                <th>Confidence</th>
                <th>Date & time</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {applications.length === 0 ? (
                <tr>
                  <td colSpan={7} style={{ color: 'var(--text-muted)', padding: '2rem' }}>
                    No applications yet. Click "Sync Emails" to pull from Gmail.
                  </td>
                </tr>
              ) : (
                applications.map((app) => (
                  <tr key={app.id} className={app.requires_action ? 'requires-action-row' : ''}>
                    <td>{app.company_name}</td>
                    <td>
                      {app.job_title || app.position || '—'}
                      {app.position_level && <span className="position-level-inline">{app.position_level}</span>}
                    </td>
                    <td>
                      <span className={`stage-badge ${(app.application_stage || 'other').toLowerCase()}`}>
                        {app.application_stage || 'Other'}
                      </span>
                    </td>
                    <td>
                      <span className={`badge ${(app.category || 'other').toLowerCase().replace(/_/g, '-')}`}>
                        {categoryLabel(app.category)}
                      </span>
                    </td>
                    <td>
                      <ConfidenceBadge confidence={app.confidence} />
                    </td>
                    <td>
                      {app.received_date
                        ? new Date(app.received_date).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })
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
      </section>
          </>
        )}

      </main>

      {selectedApp && (
        <div className="modal-overlay" onClick={() => setSelectedApp(null)}>
          <div className="modal modal-details" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-row">
              <h2>Application details</h2>
              {selectedApp.requires_action && (
                <span className="modal-action-badge">Action Required</span>
              )}
            </div>

            <dl>
              <dt>Company</dt><dd>{selectedApp.company_name}</dd>
              <dt>Job title</dt><dd>
                {selectedApp.job_title || selectedApp.position || '—'}
                {selectedApp.position_level && <span className="position-level-inline">{selectedApp.position_level}</span>}
              </dd>
              <dt>Location</dt><dd>{selectedApp.location || '—'}</dd>
              <dt>Salary</dt><dd>{selectedApp.salary_min != null || selectedApp.salary_max != null
                ? [selectedApp.salary_min, selectedApp.salary_max].filter(Boolean).map((n) => `$${n}`).join(' – ')
                : '—'}</dd>
            </dl>

            {/* LangGraph Classification Section */}
            <h3 className="modal-section-heading">Classification</h3>
            <dl>
              <dt>Category</dt>
              <dd>
                <span className={`badge ${(selectedApp.category || 'other').toLowerCase().replace(/_/g, '-')}`}>
                  {categoryLabel(selectedApp.category)}
                </span>
              </dd>
              <dt>Stage</dt>
              <dd>
                <span className={`stage-badge ${(selectedApp.application_stage || 'other').toLowerCase()}`}>
                  {selectedApp.application_stage || 'Other'}
                </span>
              </dd>
              <dt>Confidence</dt>
              <dd>
                <ConfidenceBadge confidence={selectedApp.confidence} />
                {selectedApp.confidence != null && (
                  <span className="confidence-text"> ({Math.round(selectedApp.confidence * 100)}%)</span>
                )}
              </dd>
              {selectedApp.classification_reasoning && (
                <>
                  <dt>Reasoning</dt>
                  <dd className="reasoning-text">{selectedApp.classification_reasoning}</dd>
                </>
              )}
            </dl>

            {/* Action Items Section */}
            {selectedApp.action_items && selectedApp.action_items.length > 0 && (
              <>
                <h3 className="modal-section-heading action-items-heading">
                  <IconAlertCircle />
                  Action Items
                </h3>
                <ul className="action-items-list">
                  {selectedApp.action_items.map((item, i) => (
                    <ActionItem key={i} item={item} />
                  ))}
                </ul>
              </>
            )}

            <h3 className="modal-email-heading">Email</h3>
            <dl>
              <dt>Subject</dt><dd>{selectedApp.email_subject || '—'}</dd>
              <dt>From</dt><dd>{selectedApp.email_from || '—'}</dd>
              <dt>Received</dt><dd>{selectedApp.received_date ? new Date(selectedApp.received_date).toLocaleString() : '—'}</dd>
              <dt>Body</dt>
              <dd className="email-body-wrap">
                {selectedApp.email_body ? (
                  <div
                    className="email-body email-body-html"
                    dangerouslySetInnerHTML={{ __html: selectedApp.email_body }}
                  />
                ) : (
                  '—'
                )}
              </dd>
            </dl>
            <div className="modal-actions">
              <button
                className="filter-btn reprocess-btn"
                onClick={() => reprocessApplication(selectedApp.id)}
                disabled={reprocessing}
                title="Re-run AI classification"
              >
                <IconRefresh />
                {reprocessing ? 'Processing…' : 'Reprocess'}
              </button>
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

const NAME_TO_CATEGORY = {
  'Applied': 'ALL',
  'Interviews': 'INTERVIEW_OR_SCREENING',
  'Screening': 'SCREENING',
  'Assessments': 'ASSESSMENT',
  'Rejections': 'REJECTED',
  'Offers': 'OFFER',
}

function categoryLabel(cat) {
  if (!cat) return 'Other'
  const labels = {
    job_application_confirmation: 'Application confirmation',
    job_rejection: 'Rejection',
    interview_assessment: 'Interview / assessment',
    application_followup: 'Application follow-up',
    recruiter_outreach: 'Recruiter outreach',
    talent_community: 'Talent community',
    linkedin_connection_request: 'LinkedIn connection request',
    linkedin_message: 'LinkedIn message',
    linkedin_job_recommendations: 'LinkedIn job recommendations',
    linkedin_profile_activity: 'LinkedIn profile activity',
    job_alerts: 'Job alerts',
    verification_security: 'Verification / security',
    promotional_marketing: 'Promotional / marketing',
    receipts_invoices: 'Receipts / invoices',
  }
  return labels[cat] || cat.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase())
}

function StatCard({ label, value, color = 'blue', onClick, active }) {
  const content = (
    <>
      <h3>{label}</h3>
      <div className="value">{value}</div>
    </>
  )
  const classes = `stat-card ${onClick ? 'stat-card-clickable ' : ''}${color}${active ? ' active' : ''}`
  if (onClick) {
    return (
      <button type="button" className={classes} onClick={onClick} title={`Show ${label}`}>
        {content}
      </button>
    )
  }
  return <div className={classes}>{content}</div>
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
