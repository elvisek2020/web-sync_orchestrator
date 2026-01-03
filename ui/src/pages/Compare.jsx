import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { useMountStatus } from '../hooks/useMountStatus'
import { useWebSocket } from '../hooks/useWebSocket'
import './PlanCopy.css'
import './Datasets.css'

function Compare() {
  const mountStatus = useMountStatus()
  const { messages } = useWebSocket()
  const [diffs, setDiffs] = useState([])
  const [scans, setScans] = useState([])
  const [datasets, setDatasets] = useState([])
  const [phase, setPhase] = useState(localStorage.getItem('sync_phase') || 'planning')
  const [diffFormData, setDiffFormData] = useState({ source_scan_id: '', target_scan_id: '' })
  const [runningJobs, setRunningJobs] = useState({})
  const [diffProgress, setDiffProgress] = useState({}) // { diff_id: { count, total, message } }
  const [selectedDiff, setSelectedDiff] = useState(null)
  
  useEffect(() => {
    // Poslouchat změny fáze z hlavičky
    const handlePhaseChange = (e) => {
      setPhase(e.detail)
    }
    window.addEventListener('syncPhaseChanged', handlePhaseChange)
    return () => window.removeEventListener('syncPhaseChanged', handlePhaseChange)
  }, [])
  
  useEffect(() => {
    loadDiffs()
    loadScans()
    loadDatasets()
    
    // Polling pro aktualizaci
    const interval = setInterval(() => {
      loadDiffs()
    }, 2000)
    return () => clearInterval(interval)
  }, [])
  
  const loadDatasets = async () => {
    try {
      const response = await axios.get('/api/datasets/')
      setDatasets(response.data)
    } catch (error) {
      console.error('Failed to load datasets:', error)
    }
  }
  
  useEffect(() => {
    // Zpracování WebSocket zpráv
    messages.forEach(msg => {
      if (msg.type === 'job.started' && msg.data.type === 'diff') {
        setRunningJobs(prev => ({ ...prev, [msg.data.job_id]: { type: msg.data.type, status: 'running' } }))
        setDiffProgress(prev => ({
          ...prev,
          [msg.data.job_id]: { count: 0, total: msg.data.total || 0, message: msg.data.message || '' }
        }))
      } else if (msg.type === 'job.progress' && msg.data.type === 'diff') {
        setDiffProgress(prev => ({
          ...prev,
          [msg.data.job_id]: {
            count: msg.data.count || 0,
            total: msg.data.total || prev[msg.data.job_id]?.total || 0,
            message: msg.data.message || prev[msg.data.job_id]?.message || ''
          }
        }))
      } else if (msg.type === 'job.finished' && msg.data.type === 'diff') {
        setRunningJobs(prev => {
          const newState = { ...prev }
          delete newState[msg.data.job_id]
          return newState
        })
        setDiffProgress(prev => {
          const newState = { ...prev }
          delete newState[msg.data.job_id]
          return newState
        })
        loadDiffs()
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages])
  
  const loadDiffs = async () => {
    try {
      const response = await axios.get('/api/diffs/')
      setDiffs(response.data)
    } catch (error) {
      console.error('Failed to load diffs:', error)
    }
  }
  
  const loadScans = async () => {
    try {
      const response = await axios.get('/api/scans/')
      setScans(response.data.filter(s => s.status === 'completed'))
    } catch (error) {
      console.error('Failed to load scans:', error)
    }
  }
  
  const handleCreateDiff = async () => {
    if (!diffFormData.source_scan_id || !diffFormData.target_scan_id) {
      return
    }
    
    try {
      await axios.post('/api/diffs/', {
        source_scan_id: parseInt(diffFormData.source_scan_id),
        target_scan_id: parseInt(diffFormData.target_scan_id)
      })
      setDiffFormData({ source_scan_id: '', target_scan_id: '' })
      loadDiffs()
    } catch (error) {
      console.error('Failed to create diff:', error)
      alert('Chyba při vytváření diffu: ' + (error.response?.data?.detail || error.message))
    }
  }
  
  const handleDeleteDiff = async (diffId) => {
    try {
      await axios.delete(`/api/diffs/${diffId}`)
      loadDiffs()
    } catch (error) {
      console.error('Failed to delete diff:', error)
      alert('Chyba při mazání diffu: ' + (error.response?.data?.detail || error.message))
    }
  }
  
  // Fáze 1 (Plánování) potřebuje NAS1 + NAS2 (mohou být přes SSH, takže mount nemusí být dostupný)
  const canPlan = phase === 'planning' ? true : false
  
  return (
    <div className="plan-copy-page">
      {phase === 'planning' && (
        <div className="box box-compact help-box">
          <h3>📖 Nápověda: Porovnání</h3>
          <p><strong>Účel:</strong> Porovnat obsah NAS1 a NAS2 pro identifikaci rozdílů.</p>
          <p><strong>Požadavky:</strong> NAS1 a NAS2 musí být dostupné (mohou být přes SSH).</p>
          <ol>
            <li><strong>Vytvořte dataset pro NAS1:</strong> Na záložce "Datasety" vytvořte dataset s lokací NAS1 a spusťte scan.</li>
            <li><strong>Vytvořte dataset pro NAS2:</strong> Vytvořte dataset s lokací NAS2 a spusťte scan.</li>
            <li><strong>Vytvořte diff:</strong> Porovnejte scan NAS1 (source) s scanem NAS2 (target) - identifikuje, co je na NAS1 a chybí na NAS2.</li>
          </ol>
          <p><strong>Výsledek:</strong> Diff, který se použije pro vytvoření plánu přenosu.</p>
        </div>
      )}
      
      <div className="box box-compact">
        <h2>Vytvořit porovnání</h2>
        <p>Porovnání dvou scanů pro identifikaci změn.</p>
        
        {!canPlan && (
          <div className="warning-box">
            <strong>⚠ Porovnání není dostupné</strong>
            <p>Porovnání je dostupné pouze ve fázi 1 (Plánování).</p>
          </div>
        )}
        
        <div style={{ marginTop: '1rem' }}>
          <div className="form-group">
            <label className="label">NAS1 scan (zdroj)</label>
            <select
              className="input"
              value={diffFormData.source_scan_id}
              onChange={(e) => setDiffFormData({ ...diffFormData, source_scan_id: e.target.value })}
            >
              <option value="">-- Vyberte NAS1 scan --</option>
              {Array.isArray(scans) && scans
                .filter(scan => {
                  const dataset = datasets.find(d => d.id === scan.dataset_id)
                  return dataset && dataset.location === 'NAS1'
                })
                .map(scan => {
                  const dataset = datasets.find(d => d.id === scan.dataset_id)
                  return (
                    <option key={scan.id} value={scan.id}>
                      Scan #{scan.id} - {dataset ? `${dataset.name} (ID: ${dataset.id})` : `Dataset ID: ${scan.dataset_id}`} ({scan.total_files || 0} souborů)
                    </option>
                  )
                })}
            </select>
          </div>
          <div className="form-group">
            <label className="label">NAS2 scan (cíl)</label>
            <select
              className="input"
              value={diffFormData.target_scan_id}
              onChange={(e) => setDiffFormData({ ...diffFormData, target_scan_id: e.target.value })}
            >
              <option value="">-- Vyberte NAS2 scan --</option>
              {Array.isArray(scans) && scans
                .filter(scan => {
                  const dataset = datasets.find(d => d.id === scan.dataset_id)
                  return dataset && dataset.location === 'NAS2'
                })
                .map(scan => {
                  const dataset = datasets.find(d => d.id === scan.dataset_id)
                  return (
                    <option key={scan.id} value={scan.id}>
                      Scan #{scan.id} - {dataset ? `${dataset.name} (ID: ${dataset.id})` : `Dataset ID: ${scan.dataset_id}`} ({scan.total_files || 0} souborů)
                    </option>
                  )
                })}
            </select>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              className="button"
              onClick={handleCreateDiff}
              disabled={!canPlan || !diffFormData.source_scan_id || !diffFormData.target_scan_id}
            >
              Vytvořit porovnání
            </button>
          </div>
        </div>
      </div>
      
      <div className="box box-compact">
        <h2>Seznam porovnání</h2>
        {diffs.length === 0 ? (
          <p>Žádné diffy</p>
        ) : (
          <table className="diffs-table" style={{ width: '100%' }}>
            <thead>
              <tr>
                <th>ID</th>
                <th>Source Scan</th>
                <th>Target Scan</th>
                <th>Status</th>
                <th>Vytvořeno</th>
                <th>Akce</th>
              </tr>
            </thead>
            <tbody>
              {diffs.map(diff => {
                const running = runningJobs[diff.id]
                const progress = diffProgress[diff.id]
                const sourceScan = scans.find(s => s.id === diff.source_scan_id)
                const targetScan = scans.find(s => s.id === diff.target_scan_id)
                const sourceDataset = sourceScan ? datasets.find(d => d.id === sourceScan.dataset_id) : null
                const targetDataset = targetScan ? datasets.find(d => d.id === targetScan.dataset_id) : null
                
                return (
                  <tr key={diff.id}>
                    <td>{diff.id}</td>
                    <td>
                      {sourceDataset 
                        ? `${sourceDataset.name} (Dataset ID: ${sourceDataset.id}, Scan ID: ${diff.source_scan_id})` 
                        : `Scan #${diff.source_scan_id}`}
                    </td>
                    <td>
                      {targetDataset 
                        ? `${targetDataset.name} (Dataset ID: ${targetDataset.id}, Scan ID: ${diff.target_scan_id})` 
                        : `Scan #${diff.target_scan_id}`}
                    </td>
                    <td>
                      <div>
                        <span className={`status-badge ${running ? 'running' : diff.status}`}>
                          {running ? 'running' : diff.status}
                        </span>
                        {progress && (
                          <span style={{ marginLeft: '0.5rem', fontSize: '0.875rem', color: '#666' }}>
                            ({progress.count || 0} / {progress.total || 0} souborů)
                          </span>
                        )}
                      </div>
                    </td>
                    <td style={{ whiteSpace: 'nowrap' }}>{new Date(diff.created_at).toLocaleString('cs-CZ')}</td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', whiteSpace: 'nowrap', justifyContent: 'flex-end' }}>
                        <button
                          className="button"
                          onClick={() => setSelectedDiff(selectedDiff === diff.id ? null : diff.id)}
                          style={{ fontSize: '0.875rem', padding: '0.25rem 0.5rem', flexShrink: 0 }}
                        >
                          {selectedDiff === diff.id ? 'Skrýt' : 'Detail'}
                        </button>
                        <button
                          className="button"
                          onClick={() => handleDeleteDiff(diff.id)}
                          disabled={mountStatus.safe_mode || diff.status === 'running'}
                          style={{ background: '#dc3545', fontSize: '0.875rem', padding: '0.25rem 0.5rem', flexShrink: 0 }}
                          title={diff.status === 'running' ? 'Nelze smazat běžící diff' : 'Smazat diff'}
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
      
      {selectedDiff && (
        <div className="box">
          <h2>Detail porovnání #{selectedDiff}</h2>
          <DiffDetail diffId={selectedDiff} />
        </div>
      )}
    </div>
  )
}

function DiffDetail({ diffId }) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  
  useEffect(() => {
    loadItems()
  }, [diffId])
  
  const loadItems = async () => {
    setLoading(true)
    try {
      const response = await axios.get(`/api/diffs/${diffId}/items?limit=1000`)
      // Seřadit podle kategorie: chybí (missing), konflikt (conflict), stejné (same)
      const categoryOrder = { 'missing': 1, 'conflict': 2, 'same': 3 }
      const sortedItems = [...response.data].sort((a, b) => {
        const orderA = categoryOrder[a.category] || 999
        const orderB = categoryOrder[b.category] || 999
        if (orderA !== orderB) {
          return orderA - orderB
        }
        // Pokud je stejná kategorie, seřadit podle cesty
        const pathA = (a.full_rel_path || '').toLowerCase()
        const pathB = (b.full_rel_path || '').toLowerCase()
        return pathA.localeCompare(pathB)
      })
      setItems(sortedItems)
    } catch (error) {
      console.error('Failed to load diff items:', error)
    } finally {
      setLoading(false)
    }
  }
  
  if (loading) return <p>Načítání...</p>
  
  const getCategoryLabel = (category) => {
    switch(category) {
      case 'missing': return 'Chybí'
      case 'conflict': return 'Konflikt'
      case 'same': return 'Stejné'
      default: return category
    }
  }
  
  const getCategoryColor = (category) => {
    switch(category) {
      case 'missing': return '#ffc107'
      case 'conflict': return '#dc3545'
      case 'same': return '#28a745'
      default: return '#6c757d'
    }
  }
  
  return (
    <div>
      <p>Zobrazeno {items.length} souborů (max 1000)</p>
      <table className="scans-table" style={{ fontSize: '0.875rem' }}>
        <thead>
          <tr>
            <th>Kategorie</th>
            <th>Cesta</th>
            <th>Velikost</th>
          </tr>
        </thead>
        <tbody>
          {items.map(item => (
            <tr key={item.id}>
              <td>
                <span style={{ 
                  padding: '0.25rem 0.5rem', 
                  borderRadius: '4px', 
                  backgroundColor: getCategoryColor(item.category),
                  color: 'white',
                  fontSize: '0.75rem',
                  fontWeight: 'bold'
                }}>
                  {getCategoryLabel(item.category)}
                </span>
              </td>
              <td style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>{item.full_rel_path}</td>
              <td style={{ whiteSpace: 'nowrap' }}>{item.source_size ? (((item.source_size || 0) / 1024 / 1024 / 1024).toFixed(1) + ' GB') : (item.target_size ? (((item.target_size || 0) / 1024 / 1024 / 1024).toFixed(1) + ' GB') : '-')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default Compare

