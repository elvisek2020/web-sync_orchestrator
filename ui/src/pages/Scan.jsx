import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { useMountStatus } from '../hooks/useMountStatus'
import { useWebSocket } from '../hooks/useWebSocket'
import './Scan.css'

function Scan() {
  const mountStatus = useMountStatus()
  const { messages } = useWebSocket()
  const [scans, setScans] = useState([])
  const [datasets, setDatasets] = useState([])
  const [loading, setLoading] = useState(false)
  const [selectedDataset, setSelectedDataset] = useState('')
  const [selectedScan, setSelectedScan] = useState(null)
  const [runningScans, setRunningScans] = useState({})
  
  const loadScans = async () => {
    try {
      const response = await axios.get('/api/scans/')
      setScans(response.data)
    } catch (error) {
      console.error('Failed to load scans:', error)
    }
  }
  
  const loadDatasets = async () => {
    try {
      const response = await axios.get('/api/datasets/')
      setDatasets(response.data)
    } catch (error) {
      console.error('Failed to load datasets:', error)
    }
  }
  
  useEffect(() => {
    loadScans()
    loadDatasets()
    
    // Polling pro aktualizaci scanů
    const interval = setInterval(loadScans, 2000)
    return () => clearInterval(interval)
  }, [])
  
  useEffect(() => {
    // Zpracování WebSocket zpráv
    messages.forEach(msg => {
      if (msg.type === 'job.started' && msg.data.type === 'scan') {
        setRunningScans(prev => ({ ...prev, [msg.data.job_id]: { status: 'running', progress: 0 } }))
      } else if (msg.type === 'job.progress' && msg.data.type === 'scan') {
        setRunningScans(prev => ({
          ...prev,
          [msg.data.job_id]: { status: 'running', progress: msg.data.count || 0 }
        }))
      } else if (msg.type === 'job.finished' && msg.data.type === 'scan') {
        setRunningScans(prev => {
          const newState = { ...prev }
          delete newState[msg.data.job_id]
          return newState
        })
        loadScans()
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages])
  
  const [errorMessage, setErrorMessage] = useState('')
  
  const handleStartScan = async () => {
    if (!selectedDataset) {
      setErrorMessage('Vyberte dataset')
      return
    }
    
    setLoading(true)
    setErrorMessage('')
    
    try {
      const response = await axios.post('/api/scans/', { dataset_id: parseInt(selectedDataset) })
      console.log('Scan created:', response.data)
      setSelectedDataset('')
      loadScans()
    } catch (error) {
      console.error('Failed to start scan:', error)
      setErrorMessage('Chyba při spuštění scanu: ' + (error.response?.data?.detail || error.message))
    } finally {
      setLoading(false)
    }
  }
  
  const handleDeleteScan = async (scanId) => {
    try {
      await axios.delete(`/api/scans/${scanId}`)
      if (selectedScan === scanId) {
        setSelectedScan(null)
      }
      loadScans()
    } catch (error) {
      console.error('Failed to delete scan:', error)
      setErrorMessage('Chyba při mazání scanu: ' + (error.response?.data?.detail || error.message))
    }
  }
  
  const handleExportScan = async (scanId) => {
    try {
      const response = await axios.get(`/api/scans/${scanId}/export`, {
        responseType: 'blob'
      })
      
      // Vytvořit URL pro blob a stáhnout soubor
      const url = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `scan_${scanId}_export.csv`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (error) {
      console.error('Failed to export scan:', error)
      setErrorMessage('Chyba při exportu scanu: ' + (error.response?.data?.detail || error.message))
    }
  }
  
  const [phase, setPhase] = useState(localStorage.getItem('sync_phase') || 'planning')

  useEffect(() => {
    // Poslouchat změny fáze z hlavičky
    const handlePhaseChange = (e) => {
      setPhase(e.detail)
    }
    window.addEventListener('syncPhaseChanged', handlePhaseChange)
    return () => window.removeEventListener('syncPhaseChanged', handlePhaseChange)
  }, [])
  
  // Pro fázi 1 (Plánování) potřebujeme NAS1 nebo NAS2 (mohou být přes SSH, takže mount nemusí být dostupný)
  // Pro fázi 2a potřebujeme NAS1
  // Pro fázi 2b potřebujeme NAS2
  const canScan = !mountStatus.safe_mode && (
    phase === 'planning' ? true : // Ve fázi plánování můžeme scanovat i když mount není dostupný (SSH)
    phase === 'copy-nas-hdd' ? mountStatus.nas1.available :
    phase === 'copy-hdd-nas' ? mountStatus.nas2.available :
    false
  )
  
  return (
    <div className="scan-page">
      <div className="box box-compact">
        <h2>Spustit scan</h2>
        <p>Scan vytvoří snapshot souborů v zadaném datasetu.</p>
        
        {!canScan && (
          <div className="warning-box">
            <strong>⚠ Scan není dostupný</strong>
            <p>
              {mountStatus.safe_mode 
                ? 'SAFE MODE je aktivní - USB/DB není dostupná.'
                : 'Žádný mount (NAS1 nebo NAS2) není dostupný.'}
            </p>
          </div>
        )}
        
        {errorMessage && (
          <div style={{ marginTop: '1rem', padding: '0.75rem', background: '#f8d7da', border: '1px solid #f5c6cb', borderRadius: '4px', color: '#721c24' }}>
            <strong>✗ Chyba:</strong> {errorMessage}
            <button
              onClick={() => setErrorMessage('')}
              style={{ float: 'right', background: 'none', border: 'none', color: '#721c24', cursor: 'pointer', fontSize: '1.2rem' }}
              title="Zavřít"
            >
              ×
            </button>
          </div>
        )}
        
        <div style={{ marginTop: '1rem' }}>
          <div className="form-group">
            <label className="label">Vyberte dataset</label>
            <select
              className="input"
              value={selectedDataset}
              onChange={(e) => {
                setSelectedDataset(e.target.value)
                setErrorMessage('')
                setSuccessMessage('')
              }}
              disabled={!canScan || datasets.length === 0}
            >
              <option value="">-- Vyberte dataset --</option>
              {Array.isArray(datasets) && datasets
                .filter(ds => ds.location === 'NAS1' || ds.location === 'NAS2')
                .map(ds => (
                  <option key={ds.id} value={ds.id}>
                    {ds.name || 'Dataset'} ({ds.location || 'unknown'})
                  </option>
                ))}
            </select>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
            <button
              className="button"
              onClick={handleStartScan}
              disabled={!canScan || loading || !selectedDataset || datasets.length === 0}
            >
              {loading ? 'Spouštím...' : 'Spustit scan'}
            </button>
          </div>
        </div>
      </div>
      
      <div className="box box-compact">
        <h2>Historie scanů</h2>
        {scans.length === 0 ? (
          <p>Žádné scany</p>
        ) : (
          <table className="scans-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Dataset</th>
                <th>Status</th>
                <th>Vytvořeno</th>
                <th>Soubory</th>
                <th>Velikost</th>
                <th>Akce</th>
              </tr>
            </thead>
            <tbody>
              {Array.isArray(scans) && scans.map(scan => {
                const running = runningScans[scan.id]
                const dataset = datasets.find(d => d.id === scan.dataset_id)
                return (
                  <tr key={scan.id}>
                    <td>{scan.id}</td>
                    <td>{dataset ? `${dataset.name} (ID: ${dataset.id})` : `Dataset ID: ${scan.dataset_id}`}</td>
                    <td>
                      <div>
                        <span className={`status-badge ${scan.status || 'unknown'}`}>
                          {scan.status || 'unknown'}
                        </span>
                        {running && (
                          <span style={{ marginLeft: '0.5rem', fontSize: '0.875rem', color: '#666' }}>
                            ({running.progress || 0} souborů)
                          </span>
                        )}
                        {scan.status === 'failed' && scan.error_message && (
                          <div style={{ marginTop: '0.5rem', padding: '0.5rem', background: '#f8d7da', border: '1px solid #f5c6cb', borderRadius: '4px', fontSize: '0.875rem', color: '#721c24' }}>
                            <strong>Chyba:</strong> {scan.error_message}
                          </div>
                        )}
                      </div>
                    </td>
                    <td style={{ whiteSpace: 'nowrap' }}>{scan.created_at ? new Date(scan.created_at).toLocaleString('cs-CZ') : '-'}</td>
                    <td>{scan.total_files || (running ? running.progress : 0)}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>{scan.total_size ? ((scan.total_size / 1024 / 1024 / 1024).toFixed(1) + ' GB') : '0.0 GB'}</td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', whiteSpace: 'nowrap' }}>
                        <button
                          className="button"
                          onClick={() => setSelectedScan(scan.id === selectedScan ? null : scan.id)}
                          style={{ fontSize: '0.875rem', padding: '0.25rem 0.5rem', flexShrink: 0 }}
                        >
                          {selectedScan === scan.id ? 'Skrýt' : 'Detail'}
                        </button>
                        {scan.status === 'completed' && (
                          <button
                            className="button"
                            onClick={() => handleExportScan(scan.id)}
                            disabled={mountStatus.safe_mode}
                            style={{ background: '#28a745', fontSize: '0.875rem', padding: '0.25rem 0.5rem', flexShrink: 0 }}
                            title="Exportovat scan do CSV"
                          >
                            Export CSV
                          </button>
                        )}
                        <button
                          className="button"
                          onClick={() => handleDeleteScan(scan.id)}
                          disabled={mountStatus.safe_mode || scan.status === 'running'}
                          style={{ background: '#dc3545', fontSize: '0.875rem', padding: '0.25rem 0.5rem', flexShrink: 0 }}
                          title={scan.status === 'running' ? 'Nelze smazat běžící scan' : 'Smazat scan'}
                        >
                          Smazat
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
      
      {selectedScan && (
        <div className="box">
          <h2>Detail scanu #{selectedScan}</h2>
          <ScanDetail scanId={selectedScan} />
        </div>
      )}
      
      {phase === 'planning' && (
        <div className="box box-compact help-box">
          <h3>📖 Nápověda: Scan</h3>
          <p><strong>Účel:</strong> Vytvořit inventuru souborů na NAS1 a NAS2 pro porovnání a plánování synchronizace.</p>
          <ol>
            <li><strong>Vytvořte Dataset pro NAS1:</strong> Na záložce "Datasety" vytvořte dataset s lokací "NAS1" a zadejte "Root složky". Můžete použít SSH adapter, pokud NAS1 není lokálně namountovaný.</li>
            <li><strong>Vytvořte Dataset pro NAS2:</strong> Vytvořte dataset s lokací "NAS2" a zadejte "Root složky". Můžete použít SSH adapter.</li>
            <li><strong>Spustit scan NAS1:</strong> Vyberte dataset NAS1 a spusťte scan. Aplikace projde všechny soubory a uloží jejich metadata.</li>
            <li><strong>Spustit scan NAS2:</strong> Vyberte dataset NAS2 a spusťte scan.</li>
            <li><strong>Výsledek:</strong> Po dokončení obou scanů přejděte na záložku "Plan & Copy" a vytvořte diff (NAS1 jako source, NAS2 jako target).</li>
          </ol>
          <p style={{ marginTop: '0.75rem', padding: '0.75rem', background: 'rgba(255,255,255,0.5)', borderRadius: '4px' }}>
            <strong>💡 Tip:</strong> NAS1 a NAS2 mohou být dostupné přes SSH - mount nemusí být lokálně namountovaný.
          </p>
        </div>
      )}
      {(phase === 'copy-nas-hdd' || phase === 'copy-hdd-nas') && (
        <div className="box box-compact help-box">
          <h3>📖 Nápověda: Scan</h3>
          <p><strong>Účel:</strong> Ve fázi 2 obvykle nepotřebujete nové scany - použijete batch vytvořený ve fázi 1.</p>
          <p>Pokud potřebujete aktualizovat scan (např. po změnách na NAS), můžete vytvořit nový scan a následně nový diff a batch.</p>
        </div>
      )}
    </div>
  )
}

function ScanDetail({ scanId }) {
  const [files, setFiles] = useState([])
  const [loading, setLoading] = useState(true)
  
  useEffect(() => {
    loadFiles()
  }, [scanId])
  
  const loadFiles = async () => {
    setLoading(true)
    try {
      const response = await axios.get(`/api/scans/${scanId}/files?limit=100`)
      // Seřadit podle abecedy (podle full_rel_path)
      const sortedFiles = [...response.data].sort((a, b) => {
        const pathA = (a.full_rel_path || '').toLowerCase()
        const pathB = (b.full_rel_path || '').toLowerCase()
        return pathA.localeCompare(pathB)
      })
      setFiles(sortedFiles)
    } catch (error) {
      console.error('Failed to load files:', error)
    } finally {
      setLoading(false)
    }
  }
  
  if (loading) return <p>Načítání...</p>
  
  return (
    <div>
      <p>Zobrazeno {files.length} souborů (max 100)</p>
      <table className="scans-table" style={{ fontSize: '0.875rem' }}>
        <thead>
          <tr>
            <th>Cesta</th>
            <th>Velikost</th>
            <th>Datum změny</th>
          </tr>
        </thead>
        <tbody>
          {files.map(file => (
            <tr key={file.id}>
              <td style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>{file.full_rel_path}</td>
              <td style={{ whiteSpace: 'nowrap' }}>{((file.size || 0) / 1024 / 1024 / 1024).toFixed(1)} GB</td>
              <td style={{ whiteSpace: 'nowrap' }}>{new Date(file.mtime_epoch * 1000).toLocaleString('cs-CZ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default Scan

