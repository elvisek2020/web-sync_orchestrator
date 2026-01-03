import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { useMountStatus } from '../hooks/useMountStatus'
import { useWebSocket } from '../hooks/useWebSocket'
import './PlanCopy.css'
import './Datasets.css'

function CopyHddToNas() {
  const mountStatus = useMountStatus()
  const { messages } = useWebSocket()
  const [batches, setBatches] = useState([])
  const [expandedBatches, setExpandedBatches] = useState(new Set())
  const [batchItems, setBatchItems] = useState({})
  const [runningJobs, setRunningJobs] = useState({})
  const [copyProgress, setCopyProgress] = useState({})
  const [recentJobs, setRecentJobs] = useState([])
  
  useEffect(() => {
    loadBatches()
    loadRecentJobs()
    loadRunningJobs()
    
    const interval = setInterval(() => {
      loadBatches()
      loadRecentJobs()
      loadRunningJobs()
    }, 2000)
    return () => clearInterval(interval)
  }, [])
  
  const loadRunningJobs = async () => {
    try {
      const response = await axios.get('/api/copy/jobs')
      const allJobs = Array.isArray(response.data) ? response.data : []
      // Najít běžící copy joby a obnovit jejich progress
      const runningCopyJobs = allJobs.filter(job => job.type === 'copy' && job.status === 'running')
      runningCopyJobs.forEach(job => {
        const batchId = job.job_metadata?.batch_id
        if (batchId) {
          setRunningJobs(prev => ({
            ...prev,
            [job.id]: { type: job.type, status: 'running' },
            [batchId]: { type: job.type, status: 'running', job_id: job.id }
          }))
          // Načíst detail jobu pro získání progress informací
          axios.get(`/api/copy/jobs/${job.id}`).then(jobDetail => {
            // Progress se bude aktualizovat přes WebSocket, ale můžeme nastavit základní stav
            if (!copyProgress[batchId]) {
              setCopyProgress(prev => ({
                ...prev,
                [batchId]: {
                  currentFile: '',
                  currentFileNum: 0,
                  totalFiles: 0,
                  currentFileSize: 0,
                  totalSize: 0,
                  copiedSize: 0
                }
              }))
            }
          }).catch(err => console.error('Failed to load job detail:', err))
        }
      })
    } catch (error) {
      console.error('Failed to load running jobs:', error)
    }
  }
  
  useEffect(() => {
    messages.forEach(msg => {
      if (msg.type === 'job.started') {
        if (msg.data.type === 'copy' && msg.data.batch_id) {
          setRunningJobs(prev => ({
            ...prev,
            [msg.data.job_id]: { type: msg.data.type, status: 'running' },
            [msg.data.batch_id]: { type: msg.data.type, status: 'running', job_id: msg.data.job_id }
          }))
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
        if (msg.data.batch_id) {
          // Počkat chvíli před smazáním progress baru, aby uživatel viděl 100%
          setTimeout(() => {
            setRunningJobs(prev => {
              const newState = { ...prev }
              delete newState[msg.data.batch_id]
              delete newState[msg.data.job_id]
              return newState
            })
            setCopyProgress(prev => {
              const newState = { ...prev }
              delete newState[msg.data.batch_id]
              return newState
            })
          }, 2000)
        }
        loadBatches()
      }
    })
  }, [messages])
  
  const loadBatches = async () => {
    try {
      const response = await axios.get('/api/batches/')
      setBatches(Array.isArray(response.data) ? response.data : [])
    } catch (error) {
      console.error('Failed to load batches:', error)
      setBatches([])
    }
  }
  
  const loadRecentJobs = async () => {
    try {
      const response = await axios.get('/api/copy/jobs')
      const jobs = Array.isArray(response.data) ? response.data.slice(0, 5) : []
      setRecentJobs(jobs)
    } catch (error) {
      console.error('Failed to load jobs:', error)
      setRecentJobs([])
    }
  }
  
  const handleCopy = async (batchId) => {
    try {
      await axios.post('/api/copy/usb-nas2', { batch_id: batchId, dry_run: false })
    } catch (error) {
      console.error('Failed to start copy:', error)
      const errorMessage = error.response?.data?.detail || error.message || 'Neznámá chyba'
      alert(`Chyba při spuštění kopírování: ${errorMessage}`)
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
  
  const canCopy = mountStatus.usb?.available && mountStatus.nas2?.available && !mountStatus.safe_mode
  
  return (
    <div className="plan-copy-page">
      <div className="box box-compact help-box">
        <h3>📖 Nápověda: Kopírování HDD → NAS</h3>
        <p><strong>Účel:</strong> Zkopírovat data z USB HDD na NAS2 podle stejného plánu z fáze 1.</p>
        <p><strong>Požadavky:</strong> USB HDD (s daty z fáze 2) a NAS2 musí být dostupné.</p>
        <ol>
          <li><strong>Připojte USB HDD:</strong> Připojte USB HDD s daty zkopírovanými ve fázi 2.</li>
          <li><strong>Vyberte plán:</strong> Zvolte stejný plán, který byl použit ve fázi 2 (plán je uložen na HDD v databázi).</li>
          <li><strong>Kopírování:</strong> Spusťte kopírování USB HDD → NAS2. Systém použije rsync pro efektivní přenos.</li>
        </ol>
        <p><strong>Výsledek:</strong> Data zkopírovaná na cílový NAS2.</p>
      </div>
      
      <div className="box box-compact">
        <h2>Plány</h2>
        {batches.length === 0 ? (
          <p>Žádné plány</p>
        ) : (
          <table className="batches-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Diff ID</th>
                <th>Status</th>
                <th>Kopírování</th>
                <th>Akce</th>
              </tr>
            </thead>
            <tbody>
              {Array.isArray(batches) && batches.map(batch => {
                const running = runningJobs[batch.id]
                const progress = copyProgress[batch.id]
                const isExpanded = expandedBatches.has(batch.id)
                const allItems = batchItems[batch.id] || []
                // Ve fázi 3 zobrazit pouze vybrané (enabled) soubory
                const items = allItems.filter(item => item.enabled !== false)
                return (
                  <React.Fragment key={batch.id}>
                    <tr>
                      <td>{batch.id}</td>
                      <td>{batch.diff_id}</td>
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
                          title={
                            !canCopy ? 'USB nebo NAS2 není dostupné' :
                            batch.status !== 'ready' ? `Plán není připraven (status: ${batch.status})` :
                            running ? 'Kopírování již probíhá' :
                            'Spustit kopírování USB → NAS'
                          }
                        >
                          Copy USB → NAS
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
                        </div>
                      </td>
                    </tr>
                    {running && progress && (
                      <tr>
                        <td colSpan="5" style={{ padding: '1rem', background: '#f0f7ff', borderTop: '2px solid #007bff' }}>
                          <div style={{ marginBottom: '1rem' }}>
                            <h4 style={{ marginBottom: '0.75rem', fontSize: '0.9375rem', fontWeight: 'bold' }}>
                              Průběh kopírování
                            </h4>
                            <div style={{ marginBottom: '1rem' }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem', fontSize: '0.875rem' }}>
                                <span><strong>Celkový průběh:</strong> {progress.currentFileNum || 0} / {progress.totalFiles || 0} souborů</span>
                                <span>{progress.totalSize > 0 ? `${((progress.copiedSize || 0) / 1024 / 1024).toFixed(2)} MB / ${(progress.totalSize / 1024 / 1024).toFixed(2)} MB` : ''}</span>
                              </div>
                              <div style={{ width: '100%', height: '24px', background: '#e0e0e0', borderRadius: '4px', overflow: 'hidden', position: 'relative' }}>
                                <div
                                  style={{
                                    height: '100%',
                                    width: `${progress.totalFiles > 0 ? Math.min(100, ((progress.currentFileNum || 0) / progress.totalFiles * 100)) : 0}%`,
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
                                  {progress.totalFiles > 0 ? `${Math.min(100, Math.round((progress.currentFileNum || 0) / progress.totalFiles * 100))}%` : '0%'}
                                </div>
                              </div>
                              {progress.currentFileNum >= progress.totalFiles && progress.totalFiles > 0 && (
                                <div style={{ marginTop: '0.5rem', fontSize: '0.875rem', color: '#28a745', fontStyle: 'italic' }}>
                                  Dokončování kopírování...
                                </div>
                              )}
                            </div>
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
                        <td colSpan="5" style={{ padding: '1rem', background: '#f8f9fa' }}>
                          <div style={{ maxHeight: '400px', overflowY: 'auto' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                              <h4 style={{ margin: 0, fontSize: '0.9375rem' }}>
                                Seznam souborů k kopírování ({items.length} souborů)
                              </h4>
                            </div>
                            {items.length === 0 ? (
                              <p style={{ color: '#666', fontSize: '0.875rem' }}>Načítání souborů...</p>
                            ) : (
                              <table style={{ width: '100%', fontSize: '0.875rem', borderCollapse: 'collapse' }}>
                                <thead>
                                  <tr style={{ background: '#e9ecef', position: 'sticky', top: 0 }}>
                                    <th style={{ padding: '0.5rem', textAlign: 'left', borderBottom: '2px solid #dee2e6' }}>Cesta</th>
                                    <th style={{ padding: '0.5rem', textAlign: 'right', borderBottom: '2px solid #dee2e6' }}>Velikost</th>
                                    <th style={{ padding: '0.5rem', textAlign: 'left', borderBottom: '2px solid #dee2e6' }}>Kategorie</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {items.map(item => (
                                    <tr key={item.id} style={{ borderBottom: '1px solid #e9ecef' }}>
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
      
      <div className="box box-compact">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h2 style={{ margin: 0 }}>Poslední joby</h2>
          {recentJobs.length > 0 && (
            <button
              className="button"
              onClick={async () => {
                try {
                  await axios.delete('/api/copy/jobs')
                  loadRecentJobs()
                } catch (error) {
                  console.error('Failed to delete jobs:', error)
                  alert('Chyba při mazání jobů: ' + (error.response?.data?.detail || error.message))
                }
              }}
              style={{ background: '#dc3545', fontSize: '0.875rem', padding: '0.25rem 0.5rem' }}
            >
              Smazat všechny
            </button>
          )}
        </div>
        {recentJobs.length === 0 ? (
          <p>Žádné nedávné joby</p>
        ) : (
          <table className="jobs-table">
            <thead>
              <tr>
                <th>Typ</th>
                <th>Status</th>
                <th>Začátek</th>
                <th>Konec</th>
                <th>Akce</th>
              </tr>
            </thead>
            <tbody>
              {recentJobs.map(job => (
                <tr key={job.id}>
                  <td>{job.type}</td>
                  <td>
                    <span className={`status-badge ${job.status}`}>
                      {job.status}
                    </span>
                  </td>
                  <td>{new Date(job.started_at).toLocaleString('cs-CZ')}</td>
                  <td>{job.finished_at ? new Date(job.finished_at).toLocaleString('cs-CZ') : '-'}</td>
                  <td>
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                      <button
                        className="button"
                        onClick={async () => {
                          try {
                            const [jobResponse, filesResponse] = await Promise.all([
                              axios.get(`/api/copy/jobs/${job.id}`),
                              axios.get(`/api/copy/jobs/${job.id}/files`).catch(() => ({ data: [] }))
                            ])
                            const jobDetail = jobResponse.data
                            const files = filesResponse.data || []
                            const metadata = jobDetail.job_metadata || {}
                            
                            const filesText = files.length > 0 ? `\n\nSoubory (${files.length}):\n${files.map((f, idx) => 
                              `${idx + 1}. ${f.file_path} (${(f.file_size / 1024 / 1024).toFixed(2)} MB) - ${f.status}${f.error_message ? ` - ${f.error_message}` : ''}`
                            ).join('\n')}` : '\n\nŽádné soubory'
                            
                            const logText = jobDetail.job_log ? `\n\nLog:\n${jobDetail.job_log}` : ''
                            const detailText = `
Detail jobu #${job.id}:
Typ: ${jobDetail.type}
Status: ${jobDetail.status}
Začátek: ${new Date(jobDetail.started_at).toLocaleString('cs-CZ')}
Konec: ${jobDetail.finished_at ? new Date(jobDetail.finished_at).toLocaleString('cs-CZ') : 'Probíhá'}
${jobDetail.error_message ? `Chyba: ${jobDetail.error_message}` : ''}
${metadata.batch_id ? `Batch ID: ${metadata.batch_id}` : ''}
${metadata.direction ? `Směr: ${metadata.direction}` : ''}
${metadata.dry_run !== undefined ? `Dry run: ${metadata.dry_run}` : ''}${filesText}${logText}
                            `.trim()
                            alert(detailText)
                          } catch (error) {
                            console.error('Failed to load job detail:', error)
                            alert('Chyba při načítání detailu jobu: ' + (error.response?.data?.detail || error.message))
                          }
                        }}
                        style={{ fontSize: '0.875rem', padding: '0.25rem 0.5rem' }}
                      >
                        Detail
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

export default CopyHddToNas

