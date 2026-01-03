import React, { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Link, useLocation, useNavigate } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Datasets from './pages/Datasets'
import Scan from './pages/Scan'
import Compare from './pages/Compare'
import PlanTransfer from './pages/PlanTransfer'
import CopyNasToHdd from './pages/CopyNasToHdd'
import CopyHddToNas from './pages/CopyHddToNas'
import { useWebSocket } from './hooks/useWebSocket'
import { useMountStatus } from './hooks/useMountStatus'
import './App.css'

function Navigation() {
  const location = useLocation()
  const navigate = useNavigate()
  const [phase, setPhase] = useState(localStorage.getItem('sync_phase') || 'planning')
  
  useEffect(() => {
    const handlePhaseChange = (e) => {
      setPhase(e.detail)
      // Pokud je aktuální stránka nedostupná v nové fázi, přesměruj na Dashboard
      const allowedPaths = getAllowedPaths(e.detail)
      if (!allowedPaths.includes(location.pathname)) {
        navigate('/')
      }
    }
    window.addEventListener('syncPhaseChanged', handlePhaseChange)
    return () => window.removeEventListener('syncPhaseChanged', handlePhaseChange)
  }, [location.pathname, navigate])
  
  // Definice povolených cest podle fáze
  const getAllowedPaths = (currentPhase) => {
    const navItems = [
      { path: '/', phases: ['planning', 'copy-nas-hdd', 'copy-hdd-nas'] },
      { path: '/datasets', phases: ['planning'] },
      { path: '/scan', phases: ['planning'] },
      { path: '/compare', phases: ['planning'] },
      { path: '/plan-transfer', phases: ['planning'] },
      { path: '/copy-nas-hdd', phases: ['copy-nas-hdd'] },
      { path: '/copy-hdd-nas', phases: ['copy-hdd-nas'] },
    ]
    return navItems.filter(item => item.phases.includes(currentPhase)).map(item => item.path)
  }
  
  // Vždy stejné záložky, ale některé mohou být skryté nebo neaktivní podle fáze
  const navItems = [
    { path: '/', label: 'Dashboard', phases: ['planning', 'copy-nas-hdd', 'copy-hdd-nas'] },
    { path: '/datasets', label: 'Datasety', phases: ['planning'] },
    { path: '/scan', label: 'Scan', phases: ['planning'] },
    { path: '/compare', label: 'Porovnání', phases: ['planning'] },
    { path: '/plan-transfer', label: 'Plán přenosu', phases: ['planning'] },
    { path: '/copy-nas-hdd', label: 'Kopírování NAS → HDD', phases: ['copy-nas-hdd'] },
    { path: '/copy-hdd-nas', label: 'Kopírování HDD → NAS', phases: ['copy-hdd-nas'] }
  ]
  
  // Filtrovat záložky podle aktuální fáze
  const visibleNavItems = navItems.filter(item => item.phases.includes(phase))
  
  return (
    <nav className="navigation">
      {visibleNavItems.map(item => (
        <Link
          key={item.path}
          to={item.path}
          className={`nav-button ${location.pathname === item.path ? 'active' : ''}`}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  )
}

function PhaseRouter({ phase, children }) {
  const location = useLocation()
  const navigate = useNavigate()
  
  useEffect(() => {
    // Kontrola, zda je aktuální stránka dostupná v aktuální fázi
    const navItems = [
      { path: '/', phases: ['planning', 'copy-nas-hdd', 'copy-hdd-nas'] },
      { path: '/datasets', phases: ['planning'] },
      { path: '/scan', phases: ['planning'] },
      { path: '/compare', phases: ['planning'] },
      { path: '/plan-transfer', phases: ['planning'] },
      { path: '/copy-nas-hdd', phases: ['copy-nas-hdd'] },
      { path: '/copy-hdd-nas', phases: ['copy-hdd-nas'] }
    ]
    const allowedPaths = navItems.filter(item => item.phases.includes(phase)).map(item => item.path)
    
    if (!allowedPaths.includes(location.pathname)) {
      navigate('/')
    }
  }, [phase, location.pathname, navigate])
  
  return <>{children}</>
}

function App() {
  const { connected } = useWebSocket()
  const { safeMode, refresh } = useMountStatus()
  const [phase, setPhase] = useState(localStorage.getItem('sync_phase') || 'planning')
  const [version, setVersion] = useState('')
  
  useEffect(() => {
    // Poslouchat změny fáze z jiných komponent
    const handlePhaseChange = (e) => {
      setPhase(e.detail)
    }
    window.addEventListener('syncPhaseChanged', handlePhaseChange)
    return () => window.removeEventListener('syncPhaseChanged', handlePhaseChange)
  }, [])
  
  useEffect(() => {
    // Načtení verze z version.json
    fetch('/static/version.json')
      .then(res => res.json())
      .then(data => setVersion(data.version || ''))
      .catch(err => {
        console.error('Failed to load version:', err)
        setVersion('')
      })
  }, [])
  
  const handleRefresh = async () => {
    await refresh()
  }
  
  const handlePhaseChange = (newPhase) => {
    setPhase(newPhase)
    localStorage.setItem('sync_phase', newPhase)
    // Broadcast změny fáze pro aktualizaci ostatních komponent
    window.dispatchEvent(new CustomEvent('syncPhaseChanged', { detail: newPhase }))
  }
  
  return (
    <BrowserRouter>
      <div className="app">
        <header className="app-header">
          <h1 className="clickable-header" onClick={handleRefresh} title="Klikněte pro obnovení stavu mountů">
            Sync Orchestrator
          </h1>
          <div className="header-controls">
            <div className="phase-selector-header">
              <button
                className={`phase-button-header ${phase === 'planning' ? 'active' : ''}`}
                onClick={() => handlePhaseChange('planning')}
                title="Fáze 1: Plánování - potřebuje NAS1 + NAS2 (mohou být přes SSH)"
              >
                Fáze 1: Plánování
              </button>
              <button
                className={`phase-button-header ${phase === 'copy-nas-hdd' ? 'active' : ''}`}
                onClick={() => handlePhaseChange('copy-nas-hdd')}
                title="Fáze 2a: Kopírování NAS → HDD - potřebuje NAS1 + HDD"
              >
                Fáze 2a: NAS → HDD
              </button>
              <button
                className={`phase-button-header ${phase === 'copy-hdd-nas' ? 'active' : ''}`}
                onClick={() => handlePhaseChange('copy-hdd-nas')}
                title="Fáze 2b: Kopírování HDD → NAS - potřebuje HDD + NAS2"
              >
                Fáze 2b: HDD → NAS
              </button>
            </div>
            <div className="status-indicators">
              <span className={`status-badge ${connected ? 'connected' : 'disconnected'}`}>
                {connected ? '●' : '○'} WebSocket
              </span>
              {safeMode && (
                <span className="status-badge safe-mode">
                  ⚠ SAFE MODE
                </span>
              )}
            </div>
          </div>
        </header>
        
        <Navigation />
        
        <main className="app-main">
          <PhaseRouter phase={phase}>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/datasets" element={<Datasets />} />
              <Route path="/scan" element={<Scan />} />
              <Route path="/compare" element={<Compare />} />
              <Route path="/plan-transfer" element={<PlanTransfer />} />
              <Route path="/copy-nas-hdd" element={<CopyNasToHdd />} />
              <Route path="/copy-hdd-nas" element={<CopyHddToNas />} />
            </Routes>
          </PhaseRouter>
        </main>
        
        {version && (
          <footer className="app-footer">
            <span>Verze: {version}</span>
          </footer>
        )}
      </div>
    </BrowserRouter>
  )
}

export default App

