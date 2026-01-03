import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { useMountStatus } from '../hooks/useMountStatus'
import { useWebSocket } from '../hooks/useWebSocket'
import './PlanCopy.css'
import './Datasets.css'

function PlanTransfer() {
  const mountStatus = useMountStatus()
  const { messages } = useWebSocket()
  const [diffs, setDiffs] = useState([])
  const [batches, setBatches] = useState([])
  const [scans, setScans] = useState([])
  const [datasets, setDatasets] = useState([])
  const [expandedBatches, setExpandedBatches] = useState(new Set())
  const [batchItems, setBatchItems] = useState({})
  const [batchFormData, setBatchFormData] = useState({ diff_id: '', include_conflicts: false, exclude_patterns: '' })
  const [batchProgress, setBatchProgress] = useState({}) // { batch_id: { count, total, message } }
  
  useEffect(() => {
    loadDiffs()
    loadBatches()
    loadScans()
    loadDatasets()
    
    const interval = setInterval(() => {
      loadDiffs()
      loadBatches()
    }, 2000)
    return () => clearInterval(interval)
  }, [])
  
  useEffect(() => {
    // Zpracování WebSocket zpráv
    messages.forEach(msg => {
      if (msg.type === 'job.started' && msg.data.type === 'batch') {
        setBatchProgress(prev => ({
          ...prev,
          [msg.data.job_id]: { count: 0, total: msg.data.total || 0, message: msg.data.message || '' }
        }))
      } else if (msg.type === 'job.progress' && msg.data.type === 'batch') {
        setBatchProgress(prev => ({
          ...prev,
          [msg.data.job_id]: {
            count: msg.data.count || 0,
            total: msg.data.total || prev[msg.data.job_id]?.total || 0,
            message: msg.data.message || prev[msg.data.job_id]?.message || ''
          }
        }))
      } else if (msg.type === 'job.finished' && msg.data.type === 'batch') {
        setBatchProgress(prev => {
          const newState = { ...prev }
          delete newState[msg.data.job_id]
          return newState
        })
        loadBatches()
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages])
  
  const loadDatasets = async () => {
    try {
      const response = await axios.get('/api/datasets/')
      setDatasets(Array.isArray(response.data) ? response.data : [])
    } catch (error) {
      console.error('Failed to load datasets:', error)
      setDatasets([])
    }
  }
  
  const loadScans = async () => {
    try {
      const response = await axios.get('/api/scans/')
      setScans(Array.isArray(response.data) ? response.data : [])
    } catch (error) {
      console.error('Failed to load scans:', error)
      setScans([])
    }
  }
  
  const loadDiffs = async () => {
    try {
      const response = await axios.get('/api/diffs/')
      setDiffs(Array.isArray(response.data) ? response.data : [])
    } catch (error) {
      console.error('Failed to load diffs:', error)
      setDiffs([])
    }
  }
  
  const loadBatches = async () => {
    try {
      const response = await axios.get('/api/batches/')
      setBatches(Array.isArray(response.data) ? response.data : [])
    } catch (error) {
      console.error('Failed to load batches:', error)
      setBatches([])
    }
  }
  
  const handleCreateBatch = async () => {
    try {
      // Převést exclude_patterns z stringu na seznam (podporuje čárky i nové řádky)
      const excludePatternsList = batchFormData.exclude_patterns
        ? batchFormData.exclude_patterns.split(/[,\n]/).map(line => line.trim()).filter(line => line.length > 0)
        : null
      
      const payload = {
        diff_id: parseInt(batchFormData.diff_id),
        include_conflicts: batchFormData.include_conflicts,
        exclude_patterns: excludePatternsList
      }
      
      await axios.post('/api/batches/', payload)
      setBatchFormData({ diff_id: '', include_conflicts: false, exclude_patterns: '' })
      loadBatches()
    } catch (error) {
      console.error('Failed to create batch:', error)
      let errorMessage = 'Neznámá chyba'
      if (error.response?.data) {
        if (typeof error.response.data.detail === 'string') {
          errorMessage = error.response.data.detail
        } else if (typeof error.response.data.detail === 'object') {
          errorMessage = JSON.stringify(error.response.data.detail)
        } else {
          errorMessage = String(error.response.data.detail)
        }
      } else if (error.message) {
        errorMessage = error.message
      }
      alert(`Chyba při vytváření batchu: ${errorMessage}`)
    }
  }
  
  const handleDeleteBatch = async (batchId) => {
    if (!confirm(`Opravdu chcete smazat batch #${batchId}?`)) {
      return
    }
    try {
      await axios.delete(`/api/batches/${batchId}`)
      loadBatches()
    } catch (error) {
      console.error('Failed to delete batch:', error)
      alert('Chyba při mazání batchu: ' + (error.response?.data?.detail || error.message))
    }
  }
  
  const handleToggleItemEnabled = async (batchId, itemId, enabled) => {
    try {
      await axios.put(`/api/batches/${batchId}/items/${itemId}/enabled?enabled=${enabled}`)
      setBatchItems(prev => {
        const items = prev[batchId] || []
        return {
          ...prev,
          [batchId]: items.map(item => 
            item.id === itemId ? { ...item, enabled } : item
          )
        }
      })
    } catch (error) {
      console.error('Failed to toggle item enabled:', error)
      alert('Chyba při změně stavu souboru: ' + (error.response?.data?.detail || error.message))
    }
  }
  
  const handleToggleAllItems = async (batchId, enabled) => {
    const items = batchItems[batchId] || []
    if (items.length === 0) return
    
    try {
      // Použít nový endpoint pro hromadné označení
      await axios.put(`/api/batches/${batchId}/items/toggle-all?enabled=${enabled}`)
      
      setBatchItems(prev => ({
        ...prev,
        [batchId]: items.map(item => ({ ...item, enabled }))
      }))
    } catch (error) {
      console.error('Failed to toggle all items:', error)
      alert('Chyba při změně stavu souborů: ' + (error.response?.data?.detail || error.message))
    }
  }
  
  const loadBatchItems = async (batchId) => {
    try {
      const response = await axios.get(`/api/batches/${batchId}/items?limit=1000`)
      setBatchItems(prev => ({ ...prev, [batchId]: response.data }))
    } catch (error) {
      console.error(`Failed to load batch items for batch ${batchId}:`, error)
      setBatchItems(prev => ({ ...prev, [batchId]: [] }))
    }
  }
  
  const toggleBatchExpanded = (batchId) => {
    const newExpanded = new Set(expandedBatches)
    if (newExpanded.has(batchId)) {
      newExpanded.delete(batchId)
    } else {
      newExpanded.add(batchId)
      if (!batchItems[batchId]) {
        loadBatchItems(batchId)
      }
    }
    setExpandedBatches(newExpanded)
  }
  
  const handleExportToCSV = (batchId, items) => {
    const enabledItems = items.filter(item => item.enabled !== false)
    const csvHeader = 'Cesta,Velikost (GB)\n'
    const csvRows = enabledItems.map(item => {
      const path = item.full_rel_path.replace(/"/g, '""')
      const sizeGB = ((item.size || 0) / 1024 / 1024 / 1024).toFixed(1)
      return `"${path}",${sizeGB}`
    }).join('\n')
    const csvContent = csvHeader + csvRows
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const link = document.createElement('a')
    const url = URL.createObjectURL(blob)
    link.setAttribute('href', url)
    link.setAttribute('download', `batch_${batchId}_export.csv`)
    link.style.visibility = 'hidden'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }
  
  const canPlan = !mountStatus.safe_mode
  
  return (
    <div className="plan-copy-page">
      <div className="box box-compact help-box">
        <h3>📖 Nápověda: Plán přenosu</h3>
        <p><strong>Účel:</strong> Vytvořit plán kopírování založený na porovnání.</p>
        <p><strong>Požadavky:</strong> Dokončené porovnání.</p>
        <ol>
          <li><strong>Vytvořte plán:</strong> Z porovnání vytvořte plán kopírování s respektováním limitu USB kapacity.</li>
          <li><strong>Upravte plán:</strong> Můžete vybrat, které soubory se zkopírují pomocí checkboxů.</li>
        </ol>
        <p><strong>Výsledek:</strong> Plán, který se použije ve fázi 2 pro kopírování na HDD a následně na cílový NAS2.</p>
      </div>
      
      <div className="box box-compact">
        <h2>Vytvořit plán</h2>
        <p>Plán přenosu založený na porovnání.</p>
        
        <div style={{ marginTop: '1rem' }}>
          <div className="form-group">
            <label className="label">Porovnání</label>
            <select
              className="input"
              value={batchFormData.diff_id}
              onChange={(e) => setBatchFormData({ ...batchFormData, diff_id: e.target.value })}
            >
              <option value="">-- Vyberte porovnání --</option>
              {Array.isArray(diffs) && diffs.filter(d => d.status === 'completed').map(diff => {
                const sourceScan = scans.find(s => s.id === diff.source_scan_id)
                const targetScan = scans.find(s => s.id === diff.target_scan_id)
                const sourceDataset = sourceScan ? datasets.find(d => d.id === sourceScan.dataset_id) : null
                const targetDataset = targetScan ? datasets.find(d => d.id === targetScan.dataset_id) : null
                const sourceName = sourceDataset ? sourceDataset.name : `Scan #${diff.source_scan_id}`
                const targetName = targetDataset ? targetDataset.name : `Scan #${diff.target_scan_id}`
                return (
                  <option key={diff.id} value={diff.id}>
                    Porovnání #{diff.id}: {sourceName} → {targetName}
                  </option>
                )
              })}
            </select>
          </div>
          <div className="form-group">
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <input
                type="checkbox"
                checked={batchFormData.include_conflicts}
                onChange={(e) => setBatchFormData({ ...batchFormData, include_conflicts: e.target.checked })}
              />
              Zahrnout konflikty
            </label>
            <small style={{ color: '#666', fontSize: '0.875rem', display: 'block', marginTop: '0.25rem' }}>
              Pokud je zaškrtnuto, batch zahrne i soubory s konfliktem (stejný název, ale jiná velikost na source a target). 
              Tyto soubory budou zkopírovány z NAS1 na USB a následně na NAS2, čímž přepíšou verzi na NAS2.
            </small>
          </div>
          <div className="form-group">
            <label className="label">Výjimky (exclude patterns)</label>
            <input
              type="text"
              className="input"
              value={batchFormData.exclude_patterns}
              onChange={(e) => setBatchFormData({ ...batchFormData, exclude_patterns: e.target.value })}
              placeholder=".DS_Store, Thumbs.db, *.tmp (oddělené čárkou)"
              style={{ fontFamily: 'monospace', fontSize: '0.875rem' }}
            />
            <small style={{ color: '#666', fontSize: '0.875rem', display: 'block', marginTop: '0.25rem' }}>
              Seznam patternů pro soubory, které se nebudou kopírovat (jeden pattern na řádek). 
              Podporuje glob patterns: <code>.DS_Store</code>, <code>*.tmp</code>, <code>Thumbs.db</code>, atd.
              <br />
              <strong>Výchozí výjimky:</strong> .DS_Store, ._*, .AppleDouble, Thumbs.db, desktop.ini, .Trash*, *.tmp, *.swp, *.bak, .git, .svn, .hg, @eaDir, *@SynoEAStream, *@SynoResource, *@SynoStream
            </small>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              className="button"
              onClick={handleCreateBatch}
              disabled={!canPlan || !batchFormData.diff_id}
            >
              Vytvořit plán
            </button>
          </div>
        </div>
      </div>
      
      <div className="box box-compact">
        <h2>Seznam plánů</h2>
        {batches.length === 0 ? (
          <p>Žádné plány</p>
        ) : (
          <table className="batches-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Porovnání</th>
                <th>Status</th>
                <th>Akce</th>
              </tr>
            </thead>
            <tbody>
              {Array.isArray(batches) && batches.map(batch => {
                const isExpanded = expandedBatches.has(batch.id)
                const items = batchItems[batch.id] || []
                const progress = batchProgress[batch.id]
                const isRunning = batch.status === 'running' || batch.status === 'pending'
                return (
                  <React.Fragment key={batch.id}>
                    <tr>
                      <td>{batch.id}</td>
                      <td>
                        {(() => {
                          const diff = diffs.find(d => d.id === batch.diff_id)
                          if (!diff) return `Porovnání #${batch.diff_id}`
                          const sourceScan = scans.find(s => s.id === diff.source_scan_id)
                          const targetScan = scans.find(s => s.id === diff.target_scan_id)
                          const sourceDataset = sourceScan ? datasets.find(d => d.id === sourceScan.dataset_id) : null
                          const targetDataset = targetScan ? datasets.find(d => d.id === targetScan.dataset_id) : null
                          const sourceName = sourceDataset ? sourceDataset.name : `Scan #${diff.source_scan_id}`
                          const targetName = targetDataset ? targetDataset.name : `Scan #${diff.target_scan_id}`
                          return `Porovnání #${diff.id}: ${sourceName} → ${targetName}`
                        })()}
                      </td>
                      <td>
                        <div>
                          <span className={`status-badge ${batch.status || 'unknown'}`}>
                            {batch.status || 'unknown'}
                          </span>
                          {progress && isRunning && (
                            <span style={{ marginLeft: '0.5rem', fontSize: '0.875rem', color: '#666' }}>
                              ({progress.count || 0} / {progress.total || 0} položek)
                            </span>
                          )}
                        </div>
                      </td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'flex-end', gap: '0.5rem', whiteSpace: 'nowrap' }}>
                          <button
                            className="button"
                            onClick={() => toggleBatchExpanded(batch.id)}
                            style={{ fontSize: '0.875rem', padding: '0.25rem 0.5rem', flexShrink: 0 }}
                          >
                            {isExpanded ? '▼ Skrýt soubory' : '▶ Zobrazit soubory'}
                          </button>
                          <button
                            className="button"
                            onClick={() => handleExportToCSV(batch.id, items)}
                            disabled={items.length === 0}
                            style={{ fontSize: '0.875rem', padding: '0.25rem 0.5rem', flexShrink: 0 }}
                            title="Exportovat seznam souborů do CSV"
                          >
                            Export
                          </button>
                          <button
                            className="button"
                            onClick={async () => {
                              try {
                                const response = await axios.get(`/api/batches/${batch.id}/summary`)
                                const data = response.data
                                alert(`Batch #${batch.id}:\nSoubory: ${data.total_files || 0}\nVelikost: ${((data.total_size || 0) / 1024 / 1024 / 1024).toFixed(1)} GB`)
                              } catch (error) {
                                console.error('Failed to load batch summary:', error)
                                alert('Chyba při načítání shrnutí batchu')
                              }
                            }}
                            style={{ fontSize: '0.875rem', padding: '0.25rem 0.5rem', flexShrink: 0 }}
                          >
                            Shrnutí
                          </button>
                          <button
                            className="button"
                            onClick={() => handleDeleteBatch(batch.id)}
                            disabled={mountStatus.safe_mode}
                            style={{ background: '#dc3545', fontSize: '0.875rem', padding: '0.25rem 0.5rem', flexShrink: 0 }}
                            title="Smazat batch"
                          >
                            Smazat
                          </button>
                        </div>
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr>
                        <td colSpan="4" style={{ padding: '1rem', background: '#f8f9fa' }}>
                          <div style={{ maxHeight: '400px', overflowY: 'auto' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                              <h4 style={{ margin: 0, fontSize: '0.9375rem' }}>
                                Seznam souborů k kopírování ({items.length} souborů)
                              </h4>
                              {items.length > 0 && (
                                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                  <button
                                    className="button"
                                    onClick={() => handleToggleAllItems(batch.id, true)}
                                    style={{ fontSize: '0.875rem', padding: '0.25rem 0.5rem' }}
                                    title="Označit všechny soubory"
                                  >
                                    ✓ Označit vše
                                  </button>
                                  <button
                                    className="button"
                                    onClick={() => handleToggleAllItems(batch.id, false)}
                                    style={{ fontSize: '0.875rem', padding: '0.25rem 0.5rem' }}
                                    title="Odznačit všechny soubory"
                                  >
                                    ✗ Odznačit vše
                                  </button>
                                  <span style={{ fontSize: '0.875rem', color: '#666', marginLeft: '0.5rem' }}>
                                    {items.filter(item => item.enabled !== false).length} / {items.length} označeno
                                  </span>
                                </div>
                              )}
                            </div>
                            {items.length === 0 ? (
                              <p style={{ color: '#666', fontSize: '0.875rem' }}>Načítání souborů...</p>
                            ) : (
                              <table style={{ width: '100%', fontSize: '0.875rem', borderCollapse: 'collapse' }}>
                                <thead>
                                  <tr style={{ background: '#e9ecef', position: 'sticky', top: 0 }}>
                                    <th style={{ padding: '0.5rem', textAlign: 'left', borderBottom: '2px solid #dee2e6', width: '40px' }}>✓</th>
                                    <th style={{ padding: '0.5rem', textAlign: 'left', borderBottom: '2px solid #dee2e6' }}>Cesta</th>
                                    <th style={{ padding: '0.5rem', textAlign: 'right', borderBottom: '2px solid #dee2e6' }}>Velikost</th>
                                    <th style={{ padding: '0.5rem', textAlign: 'left', borderBottom: '2px solid #dee2e6' }}>Kategorie</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {items.map(item => (
                                    <tr key={item.id} style={{ borderBottom: '1px solid #e9ecef', opacity: item.enabled !== false ? 1 : 0.5 }}>
                                      <td style={{ padding: '0.5rem', textAlign: 'center' }}>
                                        <input
                                          type="checkbox"
                                          checked={item.enabled !== false}
                                          onChange={(e) => handleToggleItemEnabled(batch.id, item.id, e.target.checked)}
                                          style={{ cursor: 'pointer' }}
                                        />
                                      </td>
                                      <td style={{ padding: '0.5rem', fontFamily: 'monospace', fontSize: '0.8rem' }}>
                                        {item.full_rel_path}
                                      </td>
                                      <td style={{ padding: '0.5rem', textAlign: 'right', whiteSpace: 'nowrap' }}>
                                        {((item.size || 0) / 1024 / 1024 / 1024).toFixed(1)} GB
                                      </td>
                                      <td style={{ padding: '0.5rem' }}>
                                        <span className={`status-badge ${item.category}`} style={{ fontSize: '0.75rem' }}>
                                          {item.category}
                                        </span>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

export default PlanTransfer

