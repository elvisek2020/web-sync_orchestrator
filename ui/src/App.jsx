import React, { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Link, useLocation, useNavigate } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Datasets from './pages/Datasets'
import Scan from './pages/Scan'
import Compare from './pages/Compare'
import PlanTransfer from './pages/PlanTransfer'
import CopyPage from './pages/CopyPage'
import DebugPage from './pages/DebugPage'
import { useWebSocket } from './hooks/useWebSocket'
import { useMountStatus } from './hooks/useMountStatus'

const NAV_ITEMS = [
  { path: '/', label: 'Dashboard', icon: '\u2302', phases: ['planning', 'copy-nas-hdd', 'copy-hdd-nas'] },
  { path: '/datasets', label: 'Datasety', icon: '\u{1F4BE}', phases: ['planning'] },
  { path: '/scan', label: 'Scan', icon: '\u{1F50D}', phases: ['planning'] },
  { path: '/compare', label: 'Porovnání', icon: '\u2194', phases: ['planning'] },
  { path: '/plan-transfer', label: 'Plán', icon: '\u{1F4CB}', phases: ['planning'] },
  { path: '/copy', label: 'Kopírování', icon: '\u{1F4E6}', phases: ['copy-nas-hdd', 'copy-hdd-nas'] },
  { path: '/debug', label: 'Debug', icon: '\u{1F41B}', phases: ['planning', 'copy-nas-hdd', 'copy-hdd-nas'] },
]

function AppContent() {
  const location = useLocation()
  const navigate = useNavigate()
  const { connected } = useWebSocket()
  const mountStatus = useMountStatus()
  const [phase, setPhase] = useState(localStorage.getItem('sync_phase') || 'planning')
  const [version, setVersion] = useState('')

  useEffect(() => {
    fetch('/static/version.json')
      .then(res => res.json())
      .then(data => setVersion(data.version || ''))
      .catch(() => setVersion(''))
  }, [])

  useEffect(() => {
    const handler = (e) => setPhase(e.detail)
    window.addEventListener('syncPhaseChanged', handler)
    return () => window.removeEventListener('syncPhaseChanged', handler)
  }, [])

  useEffect(() => {
    const allowed = NAV_ITEMS.filter(i => i.phases.includes(phase)).map(i => i.path)
    if (!allowed.includes(location.pathname)) {
      if (phase === 'copy-nas-hdd' || phase === 'copy-hdd-nas') {
        navigate('/copy')
      } else {
        navigate('/')
      }
    }
  }, [phase, location.pathname, navigate])

  const handlePhaseChange = (newPhase) => {
    setPhase(newPhase)
    localStorage.setItem('sync_phase', newPhase)
    window.dispatchEvent(new CustomEvent('syncPhaseChanged', { detail: newPhase }))
    if (newPhase === 'copy-nas-hdd' || newPhase === 'copy-hdd-nas') {
      navigate('/copy')
    } else {
      navigate('/')
    }
  }

  const visibleNav = NAV_ITEMS.filter(i => i.phases.includes(phase))

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <div className="header-left">
            <Link to="/" className="logo">
              <div className="logo-icon">S</div>
              Sync Orchestrator
            </Link>
            <nav className="nav">
              {visibleNav.map(item => (
                <Link
                  key={item.path}
                  to={item.path}
                  className={`nav-item ${location.pathname === item.path ? 'active' : ''}`}
                >
                  <span>{item.icon}</span>
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
          <div className="header-right">
            <div className="phase-selector">
              <button
                className={`phase-btn ${phase === 'planning' ? 'active' : ''}`}
                onClick={() => handlePhaseChange('planning')}
                title="Fáze 1: Plánování"
              >
                1: Plánování
              </button>
              <button
                className={`phase-btn ${phase === 'copy-nas-hdd' ? 'active' : ''}`}
                onClick={() => handlePhaseChange('copy-nas-hdd')}
                title="Fáze 2: NAS → HDD"
              >
                2: NAS→HDD
              </button>
              <button
                className={`phase-btn ${phase === 'copy-hdd-nas' ? 'active' : ''}`}
                onClick={() => handlePhaseChange('copy-hdd-nas')}
                title="Fáze 3: HDD → NAS"
              >
                3: HDD→NAS
              </button>
            </div>
            <span className={`status-dot ${connected ? 'connected' : 'disconnected'}`}>
              {connected ? '\u25CF' : '\u25CB'} WS
            </span>
            {mountStatus.safe_mode && (
              <span className="status-dot safe-mode">SAFE</span>
            )}
          </div>
        </div>
      </header>

      <main className="container">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/datasets" element={<Datasets />} />
          <Route path="/scan" element={<Scan />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/plan-transfer" element={<PlanTransfer />} />
          <Route path="/copy" element={<CopyPage />} />
          <Route path="/debug" element={<DebugPage />} />
        </Routes>
      </main>

      <footer className="footer">
        {version && <span>Verze {version}</span>}
      </footer>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AppContent />
    </BrowserRouter>
  )
}
