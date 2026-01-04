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
  const [diffs, setDiffs] = useState([])
  const [scans, setScans] = useState([])
  const [datasets, setDatasets] = useState([])
  const [expandedBatches, setExpandedBatches] = useState(new Set())
  const [batchItems, setBatchItems] = useState({})
  const [runningJobs, setRunningJobs] = useState({})
  const [copyProgress, setCopyProgress] = useState({})
  const [recentJobs, setRecentJobs] = useState([])
  const [fileStatuses, setFileStatuses] = useState({}) // { job_id: [file_statuses] }
  const [selectedJob, setSelectedJob] = useState(null) // ID vybraného jobu pro detail
  
  useEffect(() => {
    loadBatches()
    loadDiffs()
    loadScans()
    loadDatasets()
    loadRecentJobs()
    loadRunningJobs()
    
    const interval = setInterval(() => {
      loadBatches()
      loadDiffs()
      loadScans()
      loadDatasets()
      loadRecentJobs()
      loadRunningJobs()
    }, 2000)
    return () => clearInterval(interval)
  }, [])
  
  const loadDiffs = async () => {
    try {
      const response = await axios.get('/api/diffs/')
      setDiffs(Array.isArray(response.data) ? response.data : [])
    } catch (error) {
      console.error('Failed to load diffs:', error)
      setDiffs([])
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
  
  const loadDatasets = async () => {
    try {
      const response = await axios.get('/api/datasets/')
      setDatasets(Array.isArray(response.data) ? response.data : [])
    } catch (error) {
      console.error('Failed to load datasets:', error)
      setDatasets([])
    }
  }
  
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
          // Načíst file statuses pro získání totalFiles a progress
          axios.get(`/api/copy/jobs/${job.id}/files`).then(filesResponse => {
            const files = filesResponse.data || []
            // Spočítat totalFiles z batch items (enabled soubory)
            axios.get(`/api/batches/${batchId}/items`).then(itemsResponse => {
              const items = itemsResponse.data || []
              const enabledItems = items.filter(item => item.enabled !== false)
              const totalFiles = enabledItems.length
              const totalSize = enabledItems.reduce((sum, item) => sum + (item.size || 0), 0)
              const copiedCount = files.filter(f => f.status === 'copied').length
              const copiedSize = files.reduce((sum, f) => sum + (f.file_size || 0), 0)
              
              setCopyProgress(prev => ({
                ...prev,
                [batchId]: {
                  currentFile: '',
                  currentFileNum: copiedCount,
                  totalFiles: totalFiles,
                  currentFileSize: 0,
                  totalSize: totalSize,
                  copiedSize: copiedSize,
                  job_id: job.id
                }
              }))
              // Načíst file statuses
              setFileStatuses(prev => ({ ...prev, [job.id]: files }))
            }).catch(err => console.error('Failed to load batch items:', err))
          }).catch(err => console.error('Failed to load file statuses:', err))
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
              copiedSize: 0,
              job_id: msg.data.job_id
            }
          }))
          // Načíst file statuses pro běžící job
          if (msg.data.job_id) {
            loadFileStatuses(msg.data.job_id)
          }
        }
      } else if (msg.type === 'job.progress' && msg.data.type === 'copy') {
        const batchId = msg.data.batch_id
        if (batchId) {
          // Aktualizovat file statuses nejdřív, aby se progress aktualizoval z aktuálních dat
          if (msg.data.job_id) {
            loadFileStatuses(msg.data.job_id)
          }
          // Pak aktualizovat progress z WebSocket zprávy
          setCopyProgress(prev => ({
            ...prev,
            [batchId]: {
              ...prev[batchId],
              currentFile: msg.data.current_file || prev[batchId]?.currentFile || '',
              currentFileNum: msg.data.count || prev[batchId]?.currentFileNum || 0, // count je počet zkopírovaných souborů
              totalFiles: msg.data.total_files || prev[batchId]?.totalFiles || 0,
              currentFileSize: msg.data.current_file_size || 0,
              copiedSize: msg.data.copied_size || 0,
              totalSize: msg.data.total_size || prev[batchId]?.totalSize || 0,
              job_id: msg.data.job_id || prev[batchId]?.job_id
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
  
  const loadFileStatuses = async (jobId) => {
    try {
      const response = await axios.get(`/api/copy/jobs/${jobId}/files`)
      const files = response.data || []
      setFileStatuses(prev => ({ ...prev, [jobId]: files }))
      
      // Aktualizovat progress z file statuses
      const job = recentJobs.find(j => j.id === jobId) || Object.values(runningJobs).find(j => j.job_id === jobId)
      if (job) {
        const batchId = job.job_metadata?.batch_id || Object.keys(runningJobs).find(bId => runningJobs[bId]?.job_id === jobId)
        if (batchId) {
          const copiedCount = files.filter(f => f.status === 'copied').length
          setCopyProgress(prev => ({
            ...prev,
            [batchId]: {
              ...prev[batchId],
              currentFileNum: copiedCount
            }
          }))
        }
      }
    } catch (error) {
      console.error('Failed to load file statuses:', error)
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
  
  // Pro fázi 3 potřebujeme USB (vždy lokální) a NAS2 (může být lokální mount nebo SSH)
  // NAS2 je dostupná, pokud:
  // 1. Lokální mount je dostupný, NEBO
  // 2. Existuje dataset typu NAS2 s SSH adapterem
  const hasNas2Dataset = datasets.some(d => d.type === 'NAS2')
  const hasNas2Mount = mountStatus.nas2?.available
  const nas2Available = hasNas2Mount || hasNas2Dataset
  const canCopy = mountStatus.usb?.available && nas2Available && !mountStatus.safe_mode
  
  return (
    <div className="plan-copy-page">
      <div className="box box-compact">
        <h2>Plány</h2>
        {batches.length === 0 ? (
          <p>Žádné plány</p>
        ) : (
          <table className="batches-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Porovnání</th>
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
                // Načíst file statuses pro běžící job
                const jobId = progress?.job_id || running?.job_id
                const fileStatusesForJob = jobId ? (fileStatuses[jobId] || []) : []
                // Vytvořit mapu file statuses podle cesty
                const fileStatusMap = {}
                fileStatusesForJob.forEach(fs => {
                  fileStatusMap[fs.file_path] = fs
                })
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
                        <span className={`status-badge ${running ? 'running' : (batch.status || 'unknown')}`}>
                          {running ? 'running' : (batch.status || 'unknown')}
                        </span>
                      </td>
                      <td>
                        <button
                          className="button"
                          onClick={() => handleCopy(batch.id)}
                          disabled={!canCopy || batch.status !== 'ready_to_phase_3' || running}
                          title={
                            !canCopy ? 'USB nebo NAS2 není dostupné' :
                            batch.status !== 'ready_to_phase_3' ? `Plán není připraven (status: ${batch.status})` :
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
                              <div style={{ fontSize: '0.875rem' }}>
                                <span><strong>Kopírováno:</strong> {progress.currentFileNum || 0} / {progress.totalFiles || 0} souborů</span>
                              </div>
                            </div>
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
                                    {jobId && <th style={{ padding: '0.5rem', textAlign: 'left', borderBottom: '2px solid #dee2e6' }}>Stav</th>}
                                  </tr>
                                </thead>
                                <tbody>
                                  {items.map(item => {
                                    const fileStatus = fileStatusMap[item.full_rel_path]
                                    const status = fileStatus?.status || (jobId ? 'čeká' : null)
                                    return (
                                      <tr key={item.id} style={{ borderBottom: '1px solid #e9ecef', opacity: status === 'copied' ? 0.6 : 1 }}>
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
                                        {jobId && (
                                          <td style={{ padding: '0.5rem' }}>
                                            {status && (
                                              <span className={`status-badge ${status === 'copied' ? 'completed' : status === 'failed' ? 'failed' : 'running'}`} style={{ fontSize: '0.75rem' }}>
                                                {status === 'copied' ? 'Zkopírováno' : status === 'failed' ? 'Chyba' : 'Čeká'}
                                              </span>
                                            )}
                                          </td>
                                        )}
                                      </tr>
                                    )
                                  })}
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
        </div>
        {recentJobs.length === 0 ? (
          <p>Žádné nedávné joby</p>
        ) : (
          <table className="jobs-table">
            <thead>
              <tr>
                <th>Typ</th>
                <th>Porovnání</th>
                <th>Status</th>
                <th>Začátek</th>
                <th>Konec</th>
                <th>Akce</th>
              </tr>
            </thead>
            <tbody>
              {recentJobs.map(job => {
                const batchId = job.job_metadata?.batch_id
                const batch = batches.find(b => b.id === batchId)
                const diff = batch ? diffs.find(d => d.id === batch.diff_id) : null
                const diffName = diff ? (() => {
                  const sourceScan = scans.find(s => s.id === diff.source_scan_id)
                  const targetScan = scans.find(s => s.id === diff.target_scan_id)
                  const sourceDataset = sourceScan ? datasets.find(d => d.id === sourceScan.dataset_id) : null
                  const targetDataset = targetScan ? datasets.find(d => d.id === targetScan.dataset_id) : null
                  const sourceName = sourceDataset ? sourceDataset.name : `Scan #${diff.source_scan_id}`
                  const targetName = targetDataset ? targetDataset.name : `Scan #${diff.target_scan_id}`
                  return `Porovnání #${diff.id}: ${sourceName} → ${targetName}`
                })() : (batchId ? `Batch #${batchId}` : '-')
                
                return (
                  <tr key={job.id}>
                    <td>{job.type}</td>
                    <td>{diffName}</td>
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
                        onClick={() => setSelectedJob(selectedJob === job.id ? null : job.id)}
                        style={{ fontSize: '0.875rem', padding: '0.25rem 0.5rem' }}
                      >
                        {selectedJob === job.id ? 'Skrýt' : 'Detail'}
                      </button>
                      <button
                        className="button"
                        onClick={async () => {
                          try {
                            await axios.delete(`/api/copy/jobs/${job.id}`)
                            loadRecentJobs()
                          } catch (error) {
                            console.error('Failed to delete job:', error)
                            alert('Chyba při mazání jobu: ' + (error.response?.data?.detail || error.message))
                          }
                        }}
                        style={{ background: '#dc3545', fontSize: '0.875rem', padding: '0.25rem 0.5rem' }}
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
      
      {selectedJob && (
        <div className="box">
          <h2>Detail jobu #{selectedJob}</h2>
          <JobDetail jobId={selectedJob} />
        </div>
      )}
    </div>
  )
}

function JobDetail({ jobId }) {
  const [jobDetail, setJobDetail] = useState(null)
  const [files, setFiles] = useState([])
  const [loading, setLoading] = useState(true)
  
  useEffect(() => {
    loadDetail()
  }, [jobId])
  
  const loadDetail = async () => {
    setLoading(true)
    try {
      const [jobResponse, filesResponse] = await Promise.all([
        axios.get(`/api/copy/jobs/${jobId}`),
        axios.get(`/api/copy/jobs/${jobId}/files`)
      ])
      setJobDetail(jobResponse.data)
      setFiles(filesResponse.data || [])
    } catch (error) {
      console.error('Failed to load job detail:', error)
    } finally {
      setLoading(false)
    }
  }
  
  if (loading) return <p>Načítání...</p>
  if (!jobDetail) return <p>Job nenalezen</p>
  
  const getStatusLabel = (status) => {
    switch(status) {
      case 'copied': return 'Zkopírováno'
      case 'failed': return 'Chyba'
      default: return status
    }
  }
  
  const getStatusColor = (status) => {
    switch(status) {
      case 'copied': return '#28a745'
      case 'failed': return '#dc3545'
      default: return '#6c757d'
    }
  }
  
  return (
    <div>
      <div style={{ marginBottom: '1rem', padding: '0.75rem', background: '#f8f9fa', borderRadius: '4px' }}>
        <p><strong>Typ:</strong> {jobDetail.type}</p>
        <p><strong>Status:</strong> <span className={`status-badge ${jobDetail.status}`}>{jobDetail.status}</span></p>
        <p><strong>Začátek:</strong> {new Date(jobDetail.started_at).toLocaleString('cs-CZ')}</p>
        <p><strong>Konec:</strong> {jobDetail.finished_at ? new Date(jobDetail.finished_at).toLocaleString('cs-CZ') : 'Probíhá'}</p>
        {jobDetail.error_message && (
          <p><strong>Chyba:</strong> <span style={{ color: '#dc3545' }}>{jobDetail.error_message}</span></p>
        )}
        {jobDetail.job_metadata && (
          <>
            {jobDetail.job_metadata.batch_id && <p><strong>Batch ID:</strong> {jobDetail.job_metadata.batch_id}</p>}
            {jobDetail.job_metadata.direction && <p><strong>Směr:</strong> {jobDetail.job_metadata.direction}</p>}
          </>
        )}
      </div>
      
      {files.length > 0 && (
        <div>
          <p>Zobrazeno {files.length} souborů</p>
          <table className="scans-table" style={{ fontSize: '0.875rem' }}>
            <thead>
              <tr>
                <th>Stav</th>
                <th>Cesta</th>
                <th>Velikost</th>
                {files.some(f => f.error_message) && <th>Chyba</th>}
              </tr>
            </thead>
            <tbody>
              {files.map((file, idx) => (
                <tr key={idx}>
                  <td>
                    <span style={{ 
                      padding: '0.25rem 0.5rem', 
                      borderRadius: '4px', 
                      backgroundColor: getStatusColor(file.status),
                      color: 'white',
                      fontSize: '0.75rem',
                      fontWeight: 'bold'
                    }}>
                      {getStatusLabel(file.status)}
                    </span>
                  </td>
                  <td style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>{file.file_path}</td>
                  <td style={{ whiteSpace: 'nowrap' }}>{((file.file_size || 0) / 1024 / 1024 / 1024).toFixed(1)} GB</td>
                  {files.some(f => f.error_message) && (
                    <td style={{ fontSize: '0.75rem', color: '#dc3545' }}>{file.error_message || '-'}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      
      {jobDetail.job_log && (
        <div style={{ marginTop: '1rem' }}>
          <h3 style={{ fontSize: '1rem', marginBottom: '0.5rem' }}>Log:</h3>
          <pre style={{ 
            padding: '0.75rem', 
            background: '#f8f9fa', 
            borderRadius: '4px', 
            overflow: 'auto', 
            maxHeight: '400px',
            fontSize: '0.75rem',
            fontFamily: 'monospace',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word'
          }}>
            {jobDetail.job_log}
          </pre>
        </div>
      )}
      
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
    </div>
  )
}

export default CopyHddToNas

