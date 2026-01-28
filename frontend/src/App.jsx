import React, { useState, useEffect, useCallback } from 'react'
import axios from 'axios'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'

const API_URL = import.meta.env.VITE_API_URL || ''

function App() {
  const [stats, setStats] = useState(null)
  const [applications, setApplications] = useState([])
  const [filter, setFilter] = useState('ALL')
  const [syncing, setSyncing] = useState(false)
  const [syncProgress, setSyncProgress] = useState(null) // { status, message, processed, total, created, skipped, errors, error }
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const fetchStats = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API_URL}/api/stats`)
      setStats(data)
      setError(null)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to load stats')
    }
  }, [])

  const fetchApplications = useCallback(async () => {
    try {
      const params = filter !== 'ALL' ? { status: filter } : {}
      const { data } = await axios.get(`${API_URL}/api/applications`, { params })
      setApplications(data)
      setError(null)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to load applications')
    }
  }, [filter])

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
      await axios.post(`${API_URL}/api/sync-emails`)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Sync failed')
      setSyncing(false)
      setSyncProgress(null)
    }
  }

  // Poll sync status while syncing
  useEffect(() => {
    if (!syncing) return
    const interval = setInterval(async () => {
      try {
        const { data } = await axios.get(`${API_URL}/api/sync-status`)
        setSyncProgress(data)
        if (data.status === 'idle') {
          setSyncing(false)
          await fetchStats()
          await fetchApplications()
          if (data.error) setError(data.error)
        }
      } catch {
        // ignore
      }
    }, 800)
    return () => clearInterval(interval)
  }, [syncing, fetchStats, fetchApplications])

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
        <button
          className="sync-btn"
          onClick={syncEmails}
          disabled={syncing}
        >
          {syncing ? 'Syncing…' : 'Sync Emails'}
        </button>
      </header>

      {error && <div className="error-msg">{error}</div>}

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
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>Position</th>
              <th>Status</th>
              <th>Date</th>
            </tr>
          </thead>
          <tbody>
            {applications.length === 0 ? (
              <tr>
                <td colSpan={4} style={{ color: 'var(--text-muted)', padding: '2rem' }}>
                  No applications yet. Click “Sync Emails” to pull from Gmail (requires Gmail + Anthropic API setup).
                </td>
              </tr>
            ) : (
              applications.map((app) => (
                <tr key={app.id}>
                  <td>{app.company_name}</td>
                  <td>{app.position || '—'}</td>
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
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
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

export default App
