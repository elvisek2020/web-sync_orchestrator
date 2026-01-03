import React, { useState, useEffect } from 'react'
import { useMountStatus } from '../hooks/useMountStatus'
import axios from 'axios'
import './Dashboard.css'

function Dashboard() {
  const mountStatus = useMountStatus()
  const [datasets, setDatasets] = useState([])
  const [connectionStatus, setConnectionStatus] = useState({}) // { datasetId: { connected, error, message } }
  const [testingConnections, setTestingConnections] = useState(new Set())
  const [phase, setPhase] = useState(localStorage.getItem('sync_phase') || 'planning')
  
  useEffect(() => {
    loadDatasets()
    // Poslouchat změny fáze
    const handlePhaseChange = (e) => {
      setPhase(e.detail)
      loadDatasets() // Znovu načíst datasety při změně fáze
    }
    window.addEventListener('syncPhaseChanged', handlePhaseChange)
    return () => window.removeEventListener('syncPhaseChanged', handlePhaseChange)
  }, [])
  
  const loadDatasets = async () => {
    try {
      const response = await axios.get('/api/datasets/')
      const loadedDatasets = Array.isArray(response.data) ? response.data : []
      setDatasets(loadedDatasets)
      
      // Otestovat připojení pro SSH datasety
      loadedDatasets.forEach(ds => {
        if (ds.scan_adapter_type === 'ssh' && !connectionStatus[ds.id] && !testingConnections.has(ds.id)) {
          setTimeout(() => testConnection(ds.id), 500)
        }
      })
    } catch (error) {
      console.error('Failed to load datasets:', error)
      setDatasets([])
    }
  }
  
  const testConnection = async (datasetId) => {
    if (testingConnections.has(datasetId)) {
      return
    }
    
    setTestingConnections(prev => new Set(prev).add(datasetId))
    
    try {
      const response = await axios.get(`/api/datasets/${datasetId}/test-connection`)
      setConnectionStatus(prev => ({
        ...prev,
        [datasetId]: {
          connected: response.data.connected,
          error: response.data.error,
          message: response.data.message
        }
      }))
    } catch (error) {
      setConnectionStatus(prev => ({
        ...prev,
        [datasetId]: {
          connected: false,
          error: error.response?.data?.detail || error.message || "Connection test failed"
        }
      }))
    } finally {
      setTestingConnections(prev => {
        const newSet = new Set(prev)
        newSet.delete(datasetId)
        return newSet
      })
    }
  }
  
  const formatBytes = (bytes) => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
  }
  
  const formatPercent = (used, total) => {
    if (total === 0) return '0%'
    return Math.round((used / total) * 100) + '%'
  }
  
  // Určení, které mounty jsou potřeba pro aktuální fázi
  const getRequiredMounts = () => {
    if (phase === 'planning') {
      return { nas1: true, nas2: true, usb: false }
    } else if (phase === 'copy-nas-hdd') {
      return { nas1: true, nas2: false, usb: true }
    } else if (phase === 'copy-hdd-nas') {
      return { nas1: false, nas2: true, usb: true }
    }
    return { nas1: false, nas2: false, usb: false }
  }
  
  // Kontrola, které lokace mají definované datasety a jaký typ adapteru používají
  const getDatasetsByLocation = () => {
    const byLocation = {
      NAS1: { hasDataset: false, usesLocal: false, usesSSH: false },
      USB: { hasDataset: false, usesLocal: false, usesSSH: false },
      NAS2: { hasDataset: false, usesLocal: false, usesSSH: false }
    }
    datasets.forEach(ds => {
      if (ds.location === 'NAS1') {
        byLocation.NAS1.hasDataset = true
        if (ds.scan_adapter_type === 'local') byLocation.NAS1.usesLocal = true
        if (ds.scan_adapter_type === 'ssh') byLocation.NAS1.usesSSH = true
      }
      if (ds.location === 'USB') {
        byLocation.USB.hasDataset = true
        if (ds.scan_adapter_type === 'local') byLocation.USB.usesLocal = true
        if (ds.scan_adapter_type === 'ssh') byLocation.USB.usesSSH = true
      }
      if (ds.location === 'NAS2') {
        byLocation.NAS2.hasDataset = true
        if (ds.scan_adapter_type === 'local') byLocation.NAS2.usesLocal = true
        if (ds.scan_adapter_type === 'ssh') byLocation.NAS2.usesSSH = true
      }
    })
    return byLocation
  }
  
  const requiredMounts = getRequiredMounts()
  const datasetsByLocation = getDatasetsByLocation()
  
  // Zobrazit mount pouze pokud je potřeba pro fázi A má definovaný dataset
  // A pokud používá lokální adapter, zobrazit stav lokálního mountu
  // Pokud používá SSH adapter, nezobrazovat lokální mount (SSH nepotřebuje lokální mount)
  const shouldShowMount = (mountName) => {
    if (mountName === 'nas1') {
      const dsInfo = datasetsByLocation.NAS1
      if (!requiredMounts.nas1 || !dsInfo.hasDataset) return false
      // Zobrazit pouze pokud používá lokální adapter (SSH nepotřebuje lokální mount)
      return dsInfo.usesLocal
    } else if (mountName === 'usb') {
      const dsInfo = datasetsByLocation.USB
      if (!requiredMounts.usb || !dsInfo.hasDataset) return false
      // USB vždy používá lokální mount
      return dsInfo.usesLocal
    } else if (mountName === 'nas2') {
      const dsInfo = datasetsByLocation.NAS2
      if (!requiredMounts.nas2 || !dsInfo.hasDataset) return false
      // Zobrazit pouze pokud používá lokální adapter (SSH nepotřebuje lokální mount)
      return dsInfo.usesLocal
    }
    return false
  }
  
  return (
    <div className="dashboard">
      {phase === 'planning' && (
        <div className="box box-compact" style={{ marginBottom: '1.25rem' }}>
          <h2>Fáze 1: Plánování</h2>
          <div style={{ marginTop: '0.75rem', textAlign: 'center' }}>
            <img src="/images/faze1-planovani.png" alt="Fáze 1: Plánování" style={{ maxWidth: '75%', height: 'auto', borderRadius: '8px', boxShadow: '0 2px 8px rgba(0,0,0,0.1)' }} />
          </div>
        </div>
      )}
      {phase === 'copy-nas-hdd' && (
        <div className="box box-compact" style={{ marginBottom: '1.25rem' }}>
          <h2>Fáze 2: Kopírování NAS → HDD</h2>
          <div style={{ marginTop: '0.75rem', textAlign: 'center' }}>
            <img src="/images/faze2a-nas-to-hdd.png" alt="Fáze 2: NAS → HDD" style={{ maxWidth: '56.25%', height: 'auto', borderRadius: '8px', boxShadow: '0 2px 8px rgba(0,0,0,0.1)' }} />
          </div>
        </div>
      )}
      {phase === 'copy-hdd-nas' && (
        <div className="box box-compact" style={{ marginBottom: '1.25rem' }}>
          <h2>Fáze 3: Kopírování HDD → NAS</h2>
          <div style={{ marginTop: '0.75rem', textAlign: 'center' }}>
            <img src="/images/faze2b-hdd-to-nas.png" alt="Fáze 3: HDD → NAS" style={{ maxWidth: '56.25%', height: 'auto', borderRadius: '8px', boxShadow: '0 2px 8px rgba(0,0,0,0.1)' }} />
          </div>
        </div>
      )}
      <div className="box box-compact">
        <h2>Stav mountů</h2>
        <div style={{ marginBottom: '1rem', padding: '0.75rem', background: '#e7f3ff', borderRadius: '4px', fontSize: '0.875rem' }}>
          <strong>Aktuální fáze:</strong> {
            phase === 'planning' ? 'Fáze 1: Plánování (potřebuje NAS1 + NAS2)' :
            phase === 'copy-nas-hdd' ? 'Fáze 2: Kopírování NAS → HDD (potřebuje NAS1 + HDD)' :
            phase === 'copy-hdd-nas' ? 'Fáze 3: Kopírování HDD → NAS (potřebuje HDD + NAS2)' :
            'Neznámá fáze'
          }
        </div>
        <div className="mount-status-grid">
          {requiredMounts.nas1 && datasetsByLocation.NAS1.hasDataset && (
            datasetsByLocation.NAS1.usesSSH ? (
              // SSH adapter - zobrazit stav připojení
              (() => {
                const sshDataset = datasets.find(ds => ds.location === 'NAS1' && ds.scan_adapter_type === 'ssh')
                const status = sshDataset ? connectionStatus[sshDataset.id] : null
                const isTesting = sshDataset ? testingConnections.has(sshDataset.id) : false
                
                return (
                  <div className={`mount-status ${status?.connected ? 'available' : 'unavailable'}`}>
                    <h3>NAS1 (SSH) {status?.connected ? '✓ Připojeno' : status ? '✗ Nepřipojeno' : '⏳ Testuji...'}</h3>
                    {sshDataset && (
                      <p className="mount-path">
                        {sshDataset.scan_adapter_config?.host || 'N/A'}:{sshDataset.scan_adapter_config?.port || 22}
                        {sshDataset.scan_adapter_config?.base_path && ` (${sshDataset.scan_adapter_config.base_path})`}
                      </p>
                    )}
                    {status?.connected && status?.message && (
                      <p style={{ fontSize: '0.875rem', color: '#28a745', marginTop: '0.5rem' }}>{status.message}</p>
                    )}
                    {status?.error && (
                      <p className="mount-error" style={{ fontSize: '0.875rem' }}>{status.error}</p>
                    )}
                    {sshDataset && (
                      <button
                        className="button"
                        onClick={() => testConnection(sshDataset.id)}
                        disabled={isTesting}
                        style={{ 
                          marginTop: '0.5rem',
                          fontSize: '0.75rem', 
                          padding: '0.2rem 0.4rem',
                          background: '#6c757d'
                        }}
                        title="Otestovat připojení"
                      >
                        🔄 Otestovat
                      </button>
                    )}
                  </div>
                )
              })()
            ) : (
              // Lokální mount
              shouldShowMount('nas1') && (
                <div className={`mount-status ${mountStatus.nas1.available ? 'available' : 'unavailable'}`}>
                  <h3>NAS1 {mountStatus.nas1.available ? '✓ Dostupné' : '✗ Nedostupné'}</h3>
                  <p className="mount-path">{mountStatus.nas1.path}</p>
                  {mountStatus.nas1.available && mountStatus.nas1.total_size > 0 && (
                    <div className="mount-stats">
                      <p><strong>Velikost:</strong> {formatBytes(mountStatus.nas1.total_size)}</p>
                      <p><strong>Využito:</strong> {formatBytes(mountStatus.nas1.used_size)} ({formatPercent(mountStatus.nas1.used_size, mountStatus.nas1.total_size)})</p>
                      <p><strong>Volné:</strong> {formatBytes(mountStatus.nas1.free_size)}</p>
                    </div>
                  )}
                  {mountStatus.nas1.error && <p className="mount-error">{mountStatus.nas1.error}</p>}
                </div>
              )
            )
          )}
          
          {shouldShowMount('usb') && (
            <div className={`mount-status ${mountStatus.usb.available ? 'available' : 'unavailable'}`}>
              <h3>USB {mountStatus.usb.available ? '✓ Dostupné' : '✗ Nedostupné'}{mountStatus.usb.writable && ' (Zapisovatelné)'}</h3>
              <p className="mount-path">{mountStatus.usb.path}</p>
              {mountStatus.usb.available && mountStatus.usb.total_size > 0 && (
                <div className="mount-stats">
                  <p><strong>Velikost:</strong> {formatBytes(mountStatus.usb.total_size)}</p>
                  <p><strong>Využito:</strong> {formatBytes(mountStatus.usb.used_size)} ({formatPercent(mountStatus.usb.used_size, mountStatus.usb.total_size)})</p>
                  <p><strong>Volné:</strong> {formatBytes(mountStatus.usb.free_size)}</p>
                </div>
              )}
              {mountStatus.usb.error && <p className="mount-error">{mountStatus.usb.error}</p>}
            </div>
          )}
          
          {requiredMounts.nas2 && datasetsByLocation.NAS2.hasDataset && (
            datasetsByLocation.NAS2.usesSSH ? (
              // SSH adapter - zobrazit stav připojení
              (() => {
                const sshDataset = datasets.find(ds => ds.location === 'NAS2' && ds.scan_adapter_type === 'ssh')
                const status = sshDataset ? connectionStatus[sshDataset.id] : null
                const isTesting = sshDataset ? testingConnections.has(sshDataset.id) : false
                
                return (
                  <div className={`mount-status ${status?.connected ? 'available' : 'unavailable'}`}>
                    <h3>NAS2 (SSH) {status?.connected ? '✓ Připojeno' : status ? '✗ Nepřipojeno' : '⏳ Testuji...'}</h3>
                    {sshDataset && (
                      <p className="mount-path">
                        {sshDataset.scan_adapter_config?.host || 'N/A'}:{sshDataset.scan_adapter_config?.port || 22}
                        {sshDataset.scan_adapter_config?.base_path && ` (${sshDataset.scan_adapter_config.base_path})`}
                      </p>
                    )}
                    {status?.connected && status?.message && (
                      <p style={{ fontSize: '0.875rem', color: '#28a745', marginTop: '0.5rem' }}>{status.message}</p>
                    )}
                    {status?.error && (
                      <p className="mount-error" style={{ fontSize: '0.875rem' }}>{status.error}</p>
                    )}
                    {sshDataset && (
                      <button
                        className="button"
                        onClick={() => testConnection(sshDataset.id)}
                        disabled={isTesting}
                        style={{ 
                          marginTop: '0.5rem',
                          fontSize: '0.75rem', 
                          padding: '0.2rem 0.4rem',
                          background: '#6c757d'
                        }}
                        title="Otestovat připojení"
                      >
                        🔄 Otestovat
                      </button>
                    )}
                  </div>
                )
              })()
            ) : (
              // Lokální mount
              shouldShowMount('nas2') && (
                <div className={`mount-status ${mountStatus.nas2.available ? 'available' : 'unavailable'}`}>
                  <h3>NAS2 {mountStatus.nas2.available ? '✓ Dostupné' : '✗ Nedostupné'}{mountStatus.nas2.writable && ' (Zapisovatelné)'}</h3>
                  <p className="mount-path">{mountStatus.nas2.path}</p>
                  {mountStatus.nas2.available && mountStatus.nas2.total_size > 0 && (
                    <div className="mount-stats">
                      <p><strong>Velikost:</strong> {formatBytes(mountStatus.nas2.total_size)}</p>
                      <p><strong>Využito:</strong> {formatBytes(mountStatus.nas2.used_size)} ({formatPercent(mountStatus.nas2.used_size, mountStatus.nas2.total_size)})</p>
                      <p><strong>Volné:</strong> {formatBytes(mountStatus.nas2.free_size)}</p>
                    </div>
                  )}
                  {mountStatus.nas2.error && <p className="mount-error">{mountStatus.nas2.error}</p>}
                </div>
              )
            )
          )}
        </div>
        
        {(!shouldShowMount('nas1') || !shouldShowMount('usb') || !shouldShowMount('nas2')) && (
          <div style={{ marginTop: '1rem', padding: '0.75rem', background: '#fff3cd', borderRadius: '4px', fontSize: '0.875rem' }}>
            <strong>ℹ️ Informace:</strong> Zobrazují se pouze mounty, pro které jsou definované datasety. Vytvořte datasety na záložce "Datasety" pro zobrazení stavu mountů.
          </div>
        )}
        
        {mountStatus.safe_mode && (
          <div className="safe-mode-banner">
            <strong>⚠ SAFE MODE</strong>
            <p>USB nebo databáze není dostupná. Operace vyžadující zápis jsou zakázány.</p>
          </div>
        )}
      </div>
      
    </div>
  )
}

export default Dashboard

