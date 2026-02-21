import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { useMountStatus } from '../hooks/useMountStatus'
import { useWebSocket } from '../hooks/useWebSocket'
import { useNotification } from '../components/Notification'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import StatusBadge from '../components/StatusBadge'
import ConfirmDialog from '../components/ConfirmDialog'
import { formatGB, formatDate } from '../utils'

export default function Scan() {
  const mountStatus = useMountStatus()
  const { messages } = useWebSocket()
  const notify = useNotification()
  const [scans, setScans] = useState([])
  const [datasets, setDatasets] = useState([])
  const [loading, setLoading] = useState(false)
  const [selectedDataset, setSelectedDataset] = useState('')
  const [selectedScan, setSelectedScan] = useState(null)
  const [runningScans, setRunningScans] = useState({})
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [phase, setPhase] = useState(localStorage.getItem('sync_phase') || 'planning')

  useEffect(() => {
    loadScans(); loadDatasets()
    const interval = setInterval(loadScans, 2000)
    const h = (e) => setPhase(e.detail)
    window.addEventListener('syncPhaseChanged', h)
    return () => { clearInterval(interval); window.removeEventListener('syncPhaseChanged', h) }
  }, [])

  useEffect(() => {
    messages.forEach(msg => {
      if (msg.type === 'job.started' && msg.data.type === 'scan')
        setRunningScans(prev => ({ ...prev, [msg.data.job_id]: { status: 'running', progress: 0 } }))
      else if (msg.type === 'job.progress' && msg.data.type === 'scan')
        setRunningScans(prev => ({ ...prev, [msg.data.job_id]: { status: 'running', progress: msg.data.count || 0 } }))
      else if (msg.type === 'job.finished' && msg.data.type === 'scan') {
        setRunningScans(prev => { const s = { ...prev }; delete s[msg.data.job_id]; return s })
        loadScans()
      }
    })
  }, [messages])

  const loadScans = async () => { try { setScans((await axios.get('/api/scans/')).data) } catch { } }
  const loadDatasets = async () => { try { setDatasets((await axios.get('/api/datasets/')).data) } catch { } }

  const handleStartScan = async () => {
    if (!selectedDataset) return
    setLoading(true)
    try {
      await axios.post('/api/scans/', { dataset_id: parseInt(selectedDataset) })
      setSelectedDataset('')
      notify('Scan spuštěn', 'success')
      loadScans()
    } catch (err) {
      notify('Chyba: ' + (err.response?.data?.detail || err.message), 'error')
    } finally { setLoading(false) }
  }

  const handleDeleteScan = async () => {
    if (!deleteTarget) return
    try {
      await axios.delete(`/api/scans/${deleteTarget}`)
      if (selectedScan === deleteTarget) setSelectedScan(null)
      notify('Scan smazán', 'success')
      loadScans()
    } catch (err) {
      notify('Chyba: ' + (err.response?.data?.detail || err.message), 'error')
    } finally { setDeleteTarget(null) }
  }

  const handleExport = async (scanId) => {
    try {
      const { data } = await axios.get(`/api/scans/${scanId}/export`, { responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([data]))
      const a = document.createElement('a')
      a.href = url; a.download = `scan_${scanId}_export.csv`
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
    } catch (err) { notify('Chyba při exportu: ' + (err.response?.data?.detail || err.message), 'error') }
  }

  const canScan = !mountStatus.safe_mode

  return (
    <>
      <PageHeader title="Scan" subtitle="Vytvoření snapshotu souborů v datasetu" />

      <Card title="Spustit scan">
        {!canScan && <div className="banner banner-warning mb-sm"><strong>Scan není dostupný</strong> &mdash; SAFE MODE je aktivní.</div>}
        <div className="form-group">
          <label className="form-label">Dataset</label>
          <select className="input select" value={selectedDataset} onChange={e => setSelectedDataset(e.target.value)} disabled={!canScan || !datasets.length}>
            <option value="">-- Vyberte dataset --</option>
            {datasets.filter(ds => ds.location === 'NAS1' || ds.location === 'NAS2').map(ds => (
              <option key={ds.id} value={ds.id}>{ds.name} ({ds.location})</option>
            ))}
          </select>
        </div>
        <button className="btn btn-primary" onClick={handleStartScan} disabled={!canScan || loading || !selectedDataset}>
          {loading ? 'Spouštím...' : 'Spustit scan'}
        </button>
      </Card>

      <Card title="Historie scanů">
        {scans.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">{'\u{1F50D}'}</div>
            <div className="empty-state-title">Žádné scany</div>
            <div className="empty-state-text">Spusťte první scan pro inventuru souborů.</div>
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Dataset</th>
                <th>Status</th>
                <th>Vytvořeno</th>
                <th>Soubory</th>
                <th>Velikost</th>
                <th style={{ textAlign: 'right' }}>Akce</th>
              </tr>
            </thead>
            <tbody>
              {scans.map(scan => {
                const running = runningScans[scan.id]
                const ds = datasets.find(d => d.id === scan.dataset_id)
                return (
                  <tr key={scan.id}>
                    <td>{scan.id}</td>
                    <td>{ds ? `${ds.name} (${ds.location})` : `Dataset #${scan.dataset_id}`}</td>
                    <td>
                      <StatusBadge status={scan.status} />
                      {running && <span className="text-muted text-sm" style={{ marginLeft: '0.375rem' }}>({running.progress} souborů)</span>}
                      {scan.status === 'failed' && scan.error_message && (
                        <div className="banner banner-error mt-sm" style={{ marginBottom: 0, fontSize: '0.75rem' }}>{scan.error_message}</div>
                      )}
                    </td>
                    <td className="nowrap">{formatDate(scan.created_at)}</td>
                    <td>{scan.total_files || (running ? running.progress : 0)}</td>
                    <td className="nowrap">{formatGB(scan.total_size)}</td>
                    <td>
                      <div style={{ display: 'flex', gap: '0.375rem', justifyContent: 'flex-end' }}>
                        <button className="btn btn-outline btn-sm" onClick={() => setSelectedScan(selectedScan === scan.id ? null : scan.id)}>
                          {selectedScan === scan.id ? 'Skrýt' : 'Detail'}
                        </button>
                        {scan.status === 'completed' && (
                          <button className="btn btn-success btn-sm" onClick={() => handleExport(scan.id)}>Export CSV</button>
                        )}
                        <button className="btn btn-danger btn-sm" onClick={() => setDeleteTarget(scan.id)} disabled={mountStatus.safe_mode || scan.status === 'running'}>Smazat</button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </Card>

      {selectedScan && (
        <Card title={`Detail scanu #${selectedScan}`}>
          <ScanDetail scanId={selectedScan} />
        </Card>
      )}

      <Card variant="info" title="Nápověda: Scan">
        <p className="text-sm" style={{ color: 'var(--color-text-light)', lineHeight: 1.6 }}>
          {phase === 'planning'
            ? 'Vytvořte inventuru souborů na NAS1 a NAS2. Po dokončení obou scanů přejděte na Porovnání.'
            : 'Ve fázi kopírování obvykle nepotřebujete nové scany. Použijte plán z fáze 1.'}
        </p>
      </Card>

      <ConfirmDialog open={!!deleteTarget} title="Smazat scan" message="Opravdu chcete smazat tento scan?" danger onConfirm={handleDeleteScan} onCancel={() => setDeleteTarget(null)} />
    </>
  )
}

function ScanDetail({ scanId }) {
  const [files, setFiles] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => { loadFiles() }, [scanId])
  const loadFiles = async () => {
    setLoading(true)
    try {
      const { data } = await axios.get(`/api/scans/${scanId}/files?limit=100`)
      setFiles([...data].sort((a, b) => (a.full_rel_path || '').localeCompare(b.full_rel_path || '')))
    } catch { } finally { setLoading(false) }
  }

  if (loading) return <p className="text-muted text-sm">Načítání...</p>

  return (
    <>
      <p className="text-sm text-muted mb-sm">Zobrazeno {files.length} souborů (max 100)</p>
      <table className="table">
        <thead><tr><th>Cesta</th><th>Velikost</th><th>Datum změny</th></tr></thead>
        <tbody>
          {files.map(f => (
            <tr key={f.id}>
              <td className="text-mono text-sm">{f.full_rel_path}</td>
              <td className="nowrap">{formatGB(f.size)}</td>
              <td className="nowrap">{new Date(f.mtime_epoch * 1000).toLocaleString('cs-CZ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}
