import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { useMountStatus } from '../hooks/useMountStatus'
import { useWebSocket } from '../hooks/useWebSocket'
import './PlanCopy.css'
import './Datasets.css'

function BatchPlan() {
  const mountStatus = useMountStatus()
  const { messages } = useWebSocket()
  const [diffs, setDiffs] = useState([])
  const [batches, setBatches] = useState([])
  const [scans, setScans] = useState([])
  const [datasets, setDatasets] = useState([])
  const [phase, setPhase] = useState(localStorage.getItem('sync_phase') || 'planning')
  const [expandedBatches, setExpandedBatches] = useState(new Set())
  const [batchItems, setBatchItems] = useState({})
  const [batchFormData, setBatchFormData] = useState({ diff_id: '', include_conflicts: false, exclude_patterns: '' })
  const [runningJobs, setRunningJobs] = useState({})
  const [copyProgress, setCopyProgress] = useState({}) // { batchId: { currentFile: '', currentFileNum: 0, totalFiles: 0, currentFileSize: 0, totalSize: 0, copiedSize: 0 } }
  
  useEffect(() => {
    const handlePhaseChange = (e) => {
      setPhase(e.detail)
    }
    window.addEventListener('syncPhaseChanged', handlePhaseChange)
    return () => window.removeEventListener('syncPhaseChanged', handlePhaseChange)
  }, [])
  
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
  
  const loadDatasets = async () => {
    try {
      const response = await axios.get('/api/datasets/')
      setDatasets(response.data)
    } catch (error) {
      console.error('Failed to load datasets:', error)
    }
  }
  
  useEffect(() => {
    messages.forEach(msg => {
      if (msg.type === 'job.started') {
        setRunningJobs(prev => ({ ...prev, [msg.data.job_id]: { type: msg.data.type, status: 'running' } }))
        // Reset progress pro nový job
        if (msg.data.type === 'copy' && msg.data.batch_id) {
          setCopyProgress(prev => ({
            ...prev,
            [msg.data.batch_id]: {
              currentFile: '',
              currentFileNum: 0,
              totalFiles: msg.data.total_files || 0,
              currentFileSize: 0,
              totalSize: msg.data.total_size || 0,
              copiedSize: 0
            }
          }))
        }
      } else if (msg.type === 'job.progress' && msg.data.type === 'copy') {
        // Aktualizace progressu
        const batchId = msg.data.batch_id
        if (batchId) {
          setCopyProgress(prev => ({
            ...prev,
            [batchId]: {
              ...prev[batchId],
              currentFile: msg.data.current_file || prev[batchId]?.currentFile || '',
              currentFileNum: msg.data.count || 0,
              currentFileSize: msg.data.current_file_size || 0,
              copiedSize: msg.data.copied_size || 0
            }
          }))
        }
      } else if (msg.type === 'job.finished') {
        setRunningJobs(prev => {
          const newState = { ...prev }
          delete newState[msg.data.job_id]
          return newState
        })
        // Smazat progress po dokončení
        if (msg.data.batch_id) {
          setCopyProgress(prev => {
            const newState = { ...prev }
            delete newState[msg.data.batch_id]
            return newState
          })
        }
        loadDiffs()
        loadBatches()
      }
    })
  }, [messages])
  
  const loadDiffs = async () => {
    try {
      const response = await axios.get('/api/diffs/')
      setDiffs(response.data)
    } catch (error) {
      console.error('Failed to load diffs:', error)
    }
  }
  
  const loadBatches = async () => {
    try {
      const response = await axios.get('/api/batches/')
      setBatches(response.data)
    } catch (error) {
      console.error('Failed to load batches:', error)
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
  
  const handleCreateBatch = async () => {
    if (!batchFormData.diff_id) {
      return
    }
    
    try {
      const exclude_patterns = batchFormData.exclude_patterns
        ? batchFormData.exclude_patterns.split('\n')
            .map(p => p.trim())
            .filter(p => p.length > 0)
        : []
      
      await axios.post('/api/batches/', {
        diff_id: parseInt(batchFormData.diff_id),
        usb_limit_pct: 100.0,
        include_conflicts: batchFormData.include_conflicts,
        exclude_patterns: exclude_patterns
      })
      setBatchFormData({ diff_id: '', include_conflicts: false, exclude_patterns: '' })
      loadBatches()
    } catch (error) {
      console.error('Failed to create batch:', error)
      alert('Chyba při vytváření batchu: ' + (error.response?.data?.detail || error.message))
    }
  }
  
  const handleDeleteBatch = async (batchId) => {
    try {
      await axios.delete(`/api/batches/${batchId}`)
      loadBatches()
      const newExpanded = new Set(expandedBatches)
      newExpanded.delete(batchId)
      setExpandedBatches(newExpanded)
      setBatchItems(prev => {
        const newItems = { ...prev }
        delete newItems[batchId]
        return newItems
      })
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
      // Aktualizovat všechny soubory najednou
      const promises = items.map(item => 
        axios.put(`/api/batches/${batchId}/items/${item.id}/enabled?enabled=${enabled}`)
      )
      await Promise.all(promises)
      
      // Aktualizovat lokální stav
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
  
  const handleCopy = async (batchId) => {
    try {
      if (phase === 'copy-nas-hdd') {
        await axios.post('/api/copy/nas1-usb', { batch_id: batchId, dry_run: false })
      } else if (phase === 'copy-hdd-nas') {
        await axios.post('/api/copy/usb-nas2', { batch_id: batchId, dry_run: false })
      } else {
        alert('Kopírování je dostupné pouze ve fázi 2a nebo 2b')
        return
      }
      // Dialog odstraněn - progress se zobrazí v progress barech
    } catch (error) {
      console.error('Failed to start copy:', error)
      const errorMessage = error.response?.data?.detail || error.message || 'Neznámá chyba'
      alert(`Chyba při spuštění kopírování: ${errorMessage}`)
    }
  }
  
  const handleExportToCSV = (batchId, items) => {
    const enabledItems = items.filter(item => item.enabled !== false)
    const csvHeader = 'Cesta,Velikost (MB)\n'
    const csvRows = enabledItems.map(item => {
      const path = item.full_rel_path.replace(/"/g, '""')
      const sizeMB = ((item.size || 0) / 1024 / 1024).toFixed(2)
      return `"${path}",${sizeMB}`
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
  
  const canPlan = phase === 'planning' ? true : false
  const canCopy = (phase === 'copy-nas-hdd' && mountStatus.usb?.available && mountStatus.nas1?.available) ||
                 (phase === 'copy-hdd-nas' && mountStatus.usb?.available && mountStatus.nas2?.available)
  
  return (
    <div className="plan-copy-page">
      {phase === 'planning' && (
        <div className="box box-compact help-box">
          <h3>📖 Plán přenosu</h3>
          <p><strong>Účel:</strong> Vytvořit plán kopírování založený na diffu.</p>
          <p><strong>Požadavky:</strong> Dokončený diff z porovnání.</p>
          <ol>
            <li><strong>Vytvořte batch:</strong> Z diffu vytvořte plán kopírování s respektováním limitu USB kapacity.</li>
            <li><strong>Upravte batch:</strong> Můžete vybrat, které soubory se zkopírují pomocí checkboxů.</li>
          </ol>
          <p><strong>Výsledek:</strong> Batch, který se použije ve fázi 2 pro kopírování na HDD a následně na cílový NAS2.</p>
        </div>
      )}
      
      {phase === 'copy-nas-hdd' && (
        <div className="box box-compact help-box">
          <h3>📖 Fáze 2a: Kopírování NAS → HDD</h3>
          <p><strong>Účel:</strong> Zkopírovat data z NAS1 na USB HDD podle batchu vytvořeného ve fázi 1.</p>
          <p><strong>Požadavky:</strong> NAS1 a USB HDD musí být dostupné.</p>
          <ol>
            <li><strong>Vyberte batch:</strong> Zvolte batch vytvořený ve fázi 1.</li>
            <li><strong>Kopírování:</strong> Spusťte kopírování NAS1 → USB HDD. Systém použije rsync pro efektivní přenos.</li>
          </ol>
          <p><strong>Výsledek:</strong> Data zkopírovaná na USB HDD, připravená k přenosu na cílový systém.</p>
        </div>
      )}
      
      {phase === 'copy-hdd-nas' && (
        <div className="box box-compact help-box">
          <h3>📖 Fáze 2b: Kopírování HDD → NAS</h3>
          <p><strong>Účel:</strong> Zkopírovat data z USB HDD na NAS2 podle stejného batchu z fáze 1.</p>
          <p><strong>Požadavky:</strong> USB HDD (s daty z fáze 2a) a NAS2 musí být dostupné.</p>
          <ol>
            <li><strong>Připojte HDD:</strong> Připojte USB HDD s daty zkopírovanými ve fázi 2a.</li>
            <li><strong>Vyberte batch:</strong> Zvolte stejný batch, který byl použit ve fázi 2a (batch je uložen na HDD v databázi).</li>
            <li><strong>Kopírování:</strong> Spusťte kopírování USB HDD → NAS2. Systém použije rsync (může být přes SSH).</li>
          </ol>
          <p><strong>Výsledek:</strong> Data zkopírovaná na cílový NAS2.</p>
        </div>
      )}
      
      {phase === 'planning' && (
        <div className="box box-compact">
          <h2>Vytvořit batch</h2>
          <p>Plán přenosu založený na diffu.</p>
          
          <div style={{ marginTop: '1rem' }}>
          <div className="form-group">
            <label className="label">Diff</label>
            <select
              className="input"
              value={batchFormData.diff_id}
              onChange={(e) => setBatchFormData({ ...batchFormData, diff_id: e.target.value })}
            >
              <option value="">-- Vyberte diff --</option>
              {Array.isArray(diffs) && diffs.filter(d => d.status === 'completed').map(diff => {
                const sourceScan = scans.find(s => s.id === diff.source_scan_id)
                const targetScan = scans.find(s => s.id === diff.target_scan_id)
                const sourceDataset = sourceScan ? datasets.find(d => d.id === sourceScan.dataset_id) : null
                const targetDataset = targetScan ? datasets.find(d => d.id === targetScan.dataset_id) : null
                const sourceName = sourceDataset ? sourceDataset.name : `Scan #${diff.source_scan_id}`
                const targetName = targetDataset ? targetDataset.name : `Scan #${diff.target_scan_id}`
                return (
                  <option key={diff.id} value={diff.id}>
                    Diff #{diff.id}: {sourceName} → {targetName}
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
            <textarea
              className="input"
              value={batchFormData.exclude_patterns}
              onChange={(e) => setBatchFormData({ ...batchFormData, exclude_patterns: e.target.value })}
              placeholder=".DS_Store&#10;Thumbs.db&#10;*.tmp"
              rows={4}
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
              Vytvořit batch
            </button>
          </div>
        </div>
      </div>
      )}
      
      <div className="box box-compact">
        <h2>Batchy</h2>
        {batches.length === 0 ? (
          <p>Žádné batchy</p>
        ) : (
          <table className="batches-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Diff ID</th>
                <th>USB Limit %</th>
                <th>Status</th>
                <th>Kopírování</th>
                <th>Akce</th>
              </tr>
            </thead>
            <tbody>
              {Array.isArray(batches) && batches.map(batch => {
                const running = runningJobs[batch.id]
                const isExpanded = expandedBatches.has(batch.id)
                const items = batchItems[batch.id] || []
                return (
                  <React.Fragment key={batch.id}>
                    <tr>
                      <td>{batch.id}</td>
                      <td>{batch.diff_id}</td>
                      <td>{batch.usb_limit_pct || 80}%</td>
                      <td>
                        <span className={`status-badge ${running ? 'running' : (batch.status || 'unknown')}`}>
                          {running ? 'running' : (batch.status || 'unknown')}
                        </span>
                      </td>
                      <td>
                        <button
                          className="button"
                          onClick={() => handleCopy(batch.id)}
                          disabled={!canCopy || batch.status !== 'ready' || running}
                        >
                          {phase === 'copy-nas-hdd' ? 'Copy NAS → USB' : phase === 'copy-hdd-nas' ? 'Copy USB → NAS' : 'Kopírovat'}
                        </button>
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
                                alert(`Batch #${batch.id}:\nSoubory: ${data.total_files || 0}\nVelikost: ${((data.total_size || 0) / 1024 / 1024).toFixed(2)} MB\nUSB dostupné: ${((data.usb_available || 0) / 1024 / 1024 / 1024).toFixed(2)} GB\nUSB limit: ${((data.usb_limit || 0) / 1024 / 1024 / 1024).toFixed(2)} GB`)
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
                            disabled={mountStatus.safe_mode || running}
                            style={{ background: '#dc3545', fontSize: '0.875rem', padding: '0.25rem 0.5rem', flexShrink: 0 }}
                            title={running ? 'Nelze smazat batch během kopírování' : 'Smazat batch'}
                          >
                            Smazat
                          </button>
                        </div>
                      </td>
                    </tr>
                    {running && progress && (
                      <tr>
                        <td colSpan="6" style={{ padding: '1rem', background: '#f0f7ff', borderTop: '2px solid #007bff' }}>
                          <div style={{ marginBottom: '1rem' }}>
                            <h4 style={{ marginBottom: '0.75rem', fontSize: '0.9375rem', fontWeight: 'bold' }}>
                              Průběh kopírování
                            </h4>
                            {/* Celkový progress bar */}
                            <div style={{ marginBottom: '1rem' }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem', fontSize: '0.875rem' }}>
                                <span><strong>Celkový průběh:</strong> {progress.currentFileNum || 0} / {progress.totalFiles || 0} souborů</span>
                                <span>{progress.totalSize > 0 ? `${((progress.copiedSize || 0) / 1024 / 1024).toFixed(2)} MB / ${(progress.totalSize / 1024 / 1024).toFixed(2)} MB` : ''}</span>
                              </div>
                              <div style={{ width: '100%', height: '24px', background: '#e0e0e0', borderRadius: '4px', overflow: 'hidden', position: 'relative' }}>
                                <div
                                  style={{
                                    height: '100%',
                                    width: `${progress.totalFiles > 0 ? ((progress.currentFileNum || 0) / progress.totalFiles * 100) : 0}%`,
                                    background: 'linear-gradient(90deg, #007bff 0%, #0056b3 100%)',
                                    transition: 'width 0.3s ease',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    color: 'white',
                                    fontSize: '0.75rem',
                                    fontWeight: 'bold'
                                  }}
                                >
                                  {progress.totalFiles > 0 ? `${Math.round((progress.currentFileNum || 0) / progress.totalFiles * 100)}%` : '0%'}
                                </div>
                              </div>
                            </div>
                            {/* Progress bar pro aktuální soubor */}
                            {progress.currentFile && (
                              <div>
                                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem', fontSize: '0.875rem' }}>
                                  <span><strong>Aktuální soubor:</strong> <code style={{ fontSize: '0.8rem', wordBreak: 'break-all' }}>{progress.currentFile}</code></span>
                                  {progress.currentFileSize > 0 && (
                                    <span>{(progress.currentFileSize / 1024 / 1024).toFixed(2)} MB</span>
                                  )}
                                </div>
                                <div style={{ width: '100%', height: '20px', background: '#e0e0e0', borderRadius: '4px', overflow: 'hidden', position: 'relative' }}>
                                  <div
                                    style={{
                                      height: '100%',
                                      width: '100%',
                                      background: 'linear-gradient(90deg, #28a745 0%, #20c997 50%, #28a745 100%)',
                                      backgroundSize: '200% 100%',
                                      animation: 'progress-animation 2s linear infinite',
                                      transition: 'width 0.3s ease'
                                    }}
                                  />
                                </div>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                    {isExpanded && (
                      <tr>
                        <td colSpan="6" style={{ padding: '1rem', background: '#f8f9fa' }}>
                          <div style={{ maxHeight: '400px', overflowY: 'auto' }}>
                            <h4 style={{ marginBottom: '0.75rem', fontSize: '0.9375rem' }}>
                              Seznam souborů k kopírování ({items.length} souborů)
                            </h4>
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
                                      <td style={{ padding: '0.5rem', textAlign: 'right' }}>
                                        {((item.size || 0) / 1024 / 1024).toFixed(2)} MB
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
                              </div>
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

export default BatchPlan

