import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { useMountStatus } from '../hooks/useMountStatus'
import { useWebSocket } from '../hooks/useWebSocket'
import { useNotification } from '../components/Notification'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import StatusBadge from '../components/StatusBadge'
import ConfirmDialog from '../components/ConfirmDialog'
import { formatDate, formatGB, getDiffName } from '../utils'

export default function CopyPage() {
  const mountStatus = useMountStatus()
  const { messages } = useWebSocket()
  const notify = useNotification()
  const [phase, setPhase] = useState(localStorage.getItem('sync_phase') || 'copy-nas-hdd')
  const [batches, setBatches] = useState([])
  const [diffs, setDiffs] = useState([])
  const [scans, setScans] = useState([])
  const [datasets, setDatasets] = useState([])
  const [expandedBatches, setExpandedBatches] = useState(new Set())
  const [batchItems, setBatchItems] = useState({})
  const [runningJobs, setRunningJobs] = useState({})
  const [copyProgress, setCopyProgress] = useState({})
  const [recentJobs, setRecentJobs] = useState([])
  const [fileStatuses, setFileStatuses] = useState({})
  const [selectedJob, setSelectedJob] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)

  const isNasToHdd = phase === 'copy-nas-hdd'
  const dirLabel = isNasToHdd ? 'NAS → USB' : 'USB → NAS'
  const apiEndpoint = isNasToHdd ? '/api/copy/nas1-usb' : '/api/copy/usb-nas2'
  const readyStatus = isNasToHdd ? 'ready_to_phase_2' : 'ready_to_phase_3'

  useEffect(() => {
    const h = (e) => setPhase(e.detail)
    window.addEventListener('syncPhaseChanged', h)
    return () => window.removeEventListener('syncPhaseChanged', h)
  }, [])

  useEffect(() => {
    loadAll()
    const interval = setInterval(loadAll, 2000)
    return () => clearInterval(interval)
  }, [])

  const loadAll = () => {
    loadBatches(); loadDiffs(); loadScans(); loadDatasets(); loadRecentJobs(); loadRunningJobs()
  }

  const loadDiffs = async () => { try { setDiffs((await axios.get('/api/diffs/')).data || []) } catch { setDiffs([]) } }
  const loadScans = async () => { try { setScans((await axios.get('/api/scans/')).data || []) } catch { setScans([]) } }
  const loadDatasets = async () => { try { setDatasets((await axios.get('/api/datasets/')).data || []) } catch { setDatasets([]) } }
  const loadBatches = async () => { try { setBatches((await axios.get('/api/batches/')).data || []) } catch { setBatches([]) } }
  const loadRecentJobs = async () => { try { setRecentJobs(((await axios.get('/api/copy/jobs')).data || []).slice(0, 5)) } catch { setRecentJobs([]) } }

  const loadRunningJobs = async () => {
    try {
      const allJobs = (await axios.get('/api/copy/jobs')).data || []
      const running = allJobs.filter(j => j.type === 'copy' && j.status === 'running')
      running.forEach(job => {
        const batchId = job.job_metadata?.batch_id
        if (!batchId) return
        setRunningJobs(prev => ({ ...prev, [job.id]: { type: job.type, status: 'running' }, [batchId]: { type: job.type, status: 'running', job_id: job.id } }))
        axios.get(`/api/copy/jobs/${job.id}/files`).then(({ data: files }) => {
          axios.get(`/api/batches/${batchId}/items`).then(({ data: items }) => {
            const enabled = (items || []).filter(i => i.enabled !== false)
            const copiedCount = (files || []).filter(f => f.status === 'copied').length
            setCopyProgress(prev => ({ ...prev, [batchId]: { currentFileNum: copiedCount, totalFiles: enabled.length, totalSize: enabled.reduce((s, i) => s + (i.size || 0), 0), copiedSize: (files || []).reduce((s, f) => s + (f.file_size || 0), 0), job_id: job.id } }))
            setFileStatuses(prev => ({ ...prev, [job.id]: files || [] }))
          }).catch(() => {})
        }).catch(() => {})
      })
    } catch { }
  }

  const loadFileStatuses = async (jobId) => {
    try {
      const files = (await axios.get(`/api/copy/jobs/${jobId}/files`)).data || []
      setFileStatuses(prev => ({ ...prev, [jobId]: files }))
      const batchId = Object.keys(runningJobs).find(bId => runningJobs[bId]?.job_id === jobId)
      if (batchId) {
        const copiedCount = files.filter(f => f.status === 'copied').length
        setCopyProgress(prev => ({ ...prev, [batchId]: { ...prev[batchId], currentFileNum: copiedCount } }))
      }
    } catch { }
  }

  useEffect(() => {
    messages.forEach(msg => {
      if (msg.type === 'job.started' && msg.data.type === 'copy' && msg.data.batch_id) {
        setRunningJobs(prev => ({ ...prev, [msg.data.job_id]: { type: 'copy', status: 'running' }, [msg.data.batch_id]: { type: 'copy', status: 'running', job_id: msg.data.job_id } }))
        setCopyProgress(prev => ({ ...prev, [msg.data.batch_id]: { currentFileNum: 0, totalFiles: msg.data.total_files || 0, totalSize: msg.data.total_size || 0, copiedSize: 0, job_id: msg.data.job_id } }))
      } else if (msg.type === 'job.progress' && msg.data.type === 'copy' && msg.data.batch_id) {
        if (msg.data.job_id) loadFileStatuses(msg.data.job_id)
        setCopyProgress(prev => ({ ...prev, [msg.data.batch_id]: { ...prev[msg.data.batch_id], currentFile: msg.data.current_file || '', currentFileNum: msg.data.count || prev[msg.data.batch_id]?.currentFileNum || 0, totalFiles: msg.data.total_files || prev[msg.data.batch_id]?.totalFiles || 0, copiedSize: msg.data.copied_size || 0, totalSize: msg.data.total_size || prev[msg.data.batch_id]?.totalSize || 0, job_id: msg.data.job_id || prev[msg.data.batch_id]?.job_id } }))
      } else if (msg.type === 'job.finished' && msg.data.batch_id) {
        setTimeout(() => {
          setRunningJobs(prev => { const s = { ...prev }; delete s[msg.data.batch_id]; delete s[msg.data.job_id]; return s })
          setCopyProgress(prev => { const s = { ...prev }; delete s[msg.data.batch_id]; return s })
        }, 2000)
        loadBatches()
      }
    })
  }, [messages])

  const handleCopy = async (batchId) => {
    try {
      await axios.post(apiEndpoint, { batch_id: batchId, dry_run: false })
      notify('Kopírování spuštěno', 'success')
    } catch (err) { notify('Chyba: ' + (err.response?.data?.detail || err.message), 'error') }
  }

  const handleDownloadScript = async (batchId) => {
    try {
      const direction = isNasToHdd ? 'nas-to-usb' : 'usb-to-nas'
      const { data } = await axios.get(`/api/batches/${batchId}/script`, { params: { direction }, responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([data], { type: 'application/x-sh' }))
      const a = document.createElement('a')
      a.href = url; a.download = `copy_batch_${batchId}.sh`
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
      notify('Skript stažen', 'success')
    } catch (err) { notify('Chyba: ' + (err.response?.data?.detail || err.message), 'error') }
  }

  const loadBatchItems = async (id) => {
    try {
      const { data } = await axios.get(`/api/batches/${id}/items?limit=1000`)
      setBatchItems(prev => ({ ...prev, [id]: data }))
    } catch { setBatchItems(prev => ({ ...prev, [id]: [] })) }
  }

  const toggleExpanded = (id) => {
    const s = new Set(expandedBatches)
    if (s.has(id)) s.delete(id)
    else { s.add(id); if (!batchItems[id]) loadBatchItems(id) }
    setExpandedBatches(s)
  }

  const handleDeleteJob = async () => {
    if (!deleteTarget) return
    try { await axios.delete(`/api/copy/jobs/${deleteTarget}`); notify('Job smazán', 'success'); loadRecentJobs() }
    catch (err) { notify('Chyba: ' + (err.response?.data?.detail || err.message), 'error') }
    finally { setDeleteTarget(null) }
  }

  const hasNas2Dataset = datasets.some(d => d.location === 'NAS2')
  const canCopy = isNasToHdd
    ? (mountStatus.usb?.available && mountStatus.nas1?.available && !mountStatus.safe_mode)
    : (mountStatus.usb?.available && (mountStatus.nas2?.available || hasNas2Dataset) && !mountStatus.safe_mode)

  return (
    <>
      <PageHeader title={`Kopírování ${dirLabel}`} subtitle={isNasToHdd ? 'Kopírování dat z NAS1 na USB HDD' : 'Kopírování dat z USB HDD na NAS2'} />

      {!canCopy && (
        <div className="banner banner-warning mb-md">
          <strong>Kopírování není dostupné</strong> &mdash; {mountStatus.safe_mode ? 'SAFE MODE' : isNasToHdd ? 'NAS1 nebo USB není dostupné' : 'USB nebo NAS2 není dostupné'}.
        </div>
      )}

      <Card title="Plány">
        {batches.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">{'\u{1F4E6}'}</div>
            <div className="empty-state-title">Žádné plány</div>
            <div className="empty-state-text">Vytvořte plán ve fázi 1 (Plánování).</div>
          </div>
        ) : (
          <table className="table">
            <thead><tr><th>ID</th><th>Porovnání</th><th>Status</th><th>Kopírování</th><th style={{ textAlign: 'right' }}>Akce</th></tr></thead>
            <tbody>
              {batches.map(batch => {
                const running = runningJobs[batch.id]
                const progress = copyProgress[batch.id]
                const isExpanded = expandedBatches.has(batch.id)
                const allItems = batchItems[batch.id] || []
                const items = allItems.filter(i => i.enabled !== false)
                const jobId = progress?.job_id || running?.job_id
                const fsForJob = jobId ? (fileStatuses[jobId] || []) : []
                const fsMap = {}
                fsForJob.forEach(fs => { fsMap[fs.file_path] = fs })
                const diff = diffs.find(d => d.id === batch.diff_id)

                return (
                  <React.Fragment key={batch.id}>
                    <tr>
                      <td>{batch.id}</td>
                      <td>{diff ? getDiffName(diff, scans, datasets) : `Diff #${batch.diff_id}`}</td>
                      <td><StatusBadge status={running ? 'running' : batch.status} /></td>
                      <td>
                        <button className="btn btn-primary btn-sm" onClick={() => handleCopy(batch.id)}
                          disabled={!canCopy || batch.status !== readyStatus || !!running}>
                          Copy {dirLabel}
                        </button>
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: '0.375rem', justifyContent: 'flex-end' }}>
                          <button className="btn btn-outline btn-sm" onClick={() => toggleExpanded(batch.id)}>
                            {isExpanded ? 'Skrýt' : 'Soubory'}
                          </button>
                          <button className="btn btn-success btn-sm" onClick={() => handleDownloadScript(batch.id)}>
                            Skript
                          </button>
                        </div>
                      </td>
                    </tr>
                    {running && progress && (
                      <tr>
                        <td colSpan="5" style={{ padding: '0.75rem 1rem', background: 'var(--color-info-light)', borderTop: '2px solid var(--color-primary)' }}>
                          <div className="flex-between mb-sm">
                            <span style={{ fontWeight: 600, fontSize: '0.875rem' }}>Průběh kopírování</span>
                            <span className="text-sm">{progress.currentFileNum || 0} / {progress.totalFiles || 0} souborů</span>
                          </div>
                          <div className="progress-bar">
                            <div className="progress-fill" style={{ width: progress.totalFiles ? `${Math.min(100, ((progress.currentFileNum || 0) / progress.totalFiles) * 100)}%` : '0%' }} />
                          </div>
                        </td>
                      </tr>
                    )}
                    {isExpanded && (
                      <tr>
                        <td colSpan="5" style={{ padding: '1rem', background: 'var(--color-border-light)' }}>
                          <div style={{ maxHeight: '400px', overflowY: 'auto' }}>
                            <div className="flex-between mb-sm">
                              <span className="text-sm" style={{ fontWeight: 600 }}>Soubory k kopírování ({items.length})</span>
                            </div>
                            {items.length === 0 ? (
                              <p className="text-muted text-sm">Načítání...</p>
                            ) : (
                              <table className="table">
                                <thead><tr><th>Cesta</th><th style={{ textAlign: 'right' }}>Velikost</th><th>Kat.</th>{jobId && <th>Stav</th>}</tr></thead>
                                <tbody>
                                  {items.map(item => {
                                    const fs = fsMap[item.full_rel_path]
                                    const st = fs?.status || (jobId ? 'pending' : null)
                                    return (
                                      <tr key={item.id} style={{ opacity: st === 'copied' ? 0.5 : 1 }}>
                                        <td className="text-mono text-sm">{item.full_rel_path}</td>
                                        <td className="nowrap" style={{ textAlign: 'right' }}>{formatGB(item.size)}</td>
                                        <td><StatusBadge status={item.category} /></td>
                                        {jobId && <td><StatusBadge status={st === 'copied' ? 'completed' : st === 'failed' ? 'failed' : 'pending'} label={st === 'copied' ? 'OK' : st === 'failed' ? 'Chyba' : 'Čeká'} /></td>}
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
      </Card>

      <Card title="Poslední joby">
        {recentJobs.length === 0 ? (
          <p className="text-muted text-sm">Žádné nedávné joby</p>
        ) : (
          <table className="table">
            <thead><tr><th>Typ</th><th>Porovnání</th><th>Status</th><th>Začátek</th><th>Konec</th><th style={{ textAlign: 'right' }}>Akce</th></tr></thead>
            <tbody>
              {recentJobs.map(job => {
                const batchId = job.job_metadata?.batch_id
                const batch = batches.find(b => b.id === batchId)
                const diff = batch ? diffs.find(d => d.id === batch.diff_id) : null
                return (
                  <tr key={job.id}>
                    <td>{job.type}</td>
                    <td>{diff ? getDiffName(diff, scans, datasets) : batchId ? `Batch #${batchId}` : '-'}</td>
                    <td><StatusBadge status={job.status} /></td>
                    <td className="nowrap">{formatDate(job.started_at)}</td>
                    <td className="nowrap">{formatDate(job.finished_at)}</td>
                    <td>
                      <div style={{ display: 'flex', gap: '0.375rem', justifyContent: 'flex-end' }}>
                        <button className="btn btn-outline btn-sm" onClick={() => setSelectedJob(selectedJob === job.id ? null : job.id)}>
                          {selectedJob === job.id ? 'Skrýt' : 'Detail'}
                        </button>
                        {job.status === 'failed' && (
                          <button className="btn btn-warning btn-sm" onClick={async () => {
                            try { await axios.post(`/api/copy/jobs/${job.id}/retry`); loadRecentJobs(); notify('Opakování spuštěno', 'success') }
                            catch (err) { notify('Chyba: ' + (err.response?.data?.detail || err.message), 'error') }
                          }}>Opakovat</button>
                        )}
                        <button className="btn btn-danger btn-sm" onClick={() => setDeleteTarget(job.id)}>Smazat</button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </Card>

      {selectedJob && (
        <Card title={`Detail jobu #${selectedJob}`}>
          <JobDetail jobId={selectedJob} />
        </Card>
      )}

      <Card variant="info" title={`Nápověda: Kopírování ${dirLabel}`}>
        <p className="text-sm" style={{ color: 'var(--color-text-light)', lineHeight: 1.6 }}>
          {isNasToHdd
            ? 'Zkopírujte data z NAS1 na USB HDD podle plánu z fáze 1. NAS1 a USB musí být dostupné. Systém použije rsync.'
            : 'Zkopírujte data z USB HDD na NAS2 podle plánu z fáze 1. USB a NAS2 musí být dostupné. Systém použije rsync.'}
        </p>
      </Card>

      <ConfirmDialog open={!!deleteTarget} title="Smazat job" message="Opravdu chcete smazat tento job?" danger onConfirm={handleDeleteJob} onCancel={() => setDeleteTarget(null)} />
    </>
  )
}

function JobDetail({ jobId }) {
  const notify = useNotification()
  const [detail, setDetail] = useState(null)
  const [files, setFiles] = useState([])
  const [loading, setLoading] = useState(true)
  const [verifyResult, setVerifyResult] = useState(null)
  const [verifying, setVerifying] = useState(false)

  useEffect(() => { load(); setVerifyResult(null) }, [jobId])

  const load = async () => {
    setLoading(true)
    try {
      const [jr, fr] = await Promise.all([axios.get(`/api/copy/jobs/${jobId}`), axios.get(`/api/copy/jobs/${jobId}/files`)])
      setDetail(jr.data); setFiles(fr.data || [])
    } catch { } finally { setLoading(false) }
  }

  const handleVerify = async () => {
    setVerifying(true)
    try { setVerifyResult((await axios.get(`/api/copy/jobs/${jobId}/verify`)).data) }
    catch (err) { setVerifyResult({ success: false, error: err.response?.data?.detail || err.message }) }
    finally { setVerifying(false) }
  }

  if (loading) return <p className="text-muted text-sm">Načítání...</p>
  if (!detail) return <p className="text-muted text-sm">Job nenalezen</p>

  const ok = verifyResult && verifyResult.missing_count === 0 && verifyResult.size_mismatch_count === 0

  return (
    <>
      <div className="summary-grid mb-md">
        <div className="summary-item"><strong>Typ:</strong> {detail.type}</div>
        <div className="summary-item"><strong>Status:</strong> <StatusBadge status={detail.status} /></div>
        <div className="summary-item"><strong>Začátek:</strong> {formatDate(detail.started_at)}</div>
        <div className="summary-item"><strong>Konec:</strong> {detail.finished_at ? formatDate(detail.finished_at) : 'Probíhá'}</div>
        {detail.job_metadata?.batch_id && <div className="summary-item"><strong>Batch:</strong> #{detail.job_metadata.batch_id}</div>}
        {detail.job_metadata?.direction && <div className="summary-item"><strong>Směr:</strong> {detail.job_metadata.direction}</div>}
      </div>

      {detail.error_message && <div className="banner banner-error mb-md">{detail.error_message}</div>}

      {detail.status === 'completed' && (
        <button className="btn btn-outline btn-sm mb-md" onClick={handleVerify} disabled={verifying}>
          {verifying ? 'Ověřuji...' : 'Ověřit zkopírované soubory'}
        </button>
      )}

      {verifyResult && (
        <div className={`banner ${ok ? 'banner-success' : 'banner-error'} mb-md`}>
          <div>
            <strong>Výsledek ověření:</strong> Celkem: {verifyResult.total_files}, OK: {verifyResult.verified_ok}, Chybí: {verifyResult.missing_count}, Špatná velikost: {verifyResult.size_mismatch_count}
            {verifyResult.missing_files?.length > 0 && (
              <details><summary className="text-sm">Chybějící soubory</summary>
                <ul className="text-mono text-sm">{verifyResult.missing_files.map((f, i) => <li key={i}>{f}</li>)}</ul>
              </details>
            )}
            {verifyResult.size_mismatch_files?.length > 0 && (
              <details><summary className="text-sm">Špatná velikost</summary>
                <ul className="text-mono text-sm">{verifyResult.size_mismatch_files.map((f, i) => <li key={i}>{f.path} ({f.expected} vs {f.actual})</li>)}</ul>
              </details>
            )}
          </div>
        </div>
      )}

      {files.length > 0 && (
        <>
          <p className="text-sm text-muted mb-sm">{files.length} souborů</p>
          <table className="table">
            <thead><tr><th>Stav</th><th>Cesta</th><th>Velikost</th>{files.some(f => f.error_message) && <th>Chyba</th>}</tr></thead>
            <tbody>
              {files.map((f, i) => (
                <tr key={i}>
                  <td><StatusBadge status={f.status === 'copied' ? 'completed' : f.status === 'failed' ? 'failed' : 'pending'} label={f.status === 'copied' ? 'OK' : f.status} /></td>
                  <td className="text-mono text-sm">{f.file_path}</td>
                  <td className="nowrap">{formatGB(f.file_size)}</td>
                  {files.some(x => x.error_message) && <td className="text-sm" style={{ color: 'var(--color-error)' }}>{f.error_message || '-'}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {detail.job_log && (
        <div className="mt-md">
          <strong className="text-sm">Log:</strong>
          <pre style={{ padding: '0.75rem', background: 'var(--color-border-light)', borderRadius: 'var(--radius-xs)', overflow: 'auto', maxHeight: '400px', fontSize: '0.75rem', fontFamily: 'monospace', whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginTop: '0.375rem' }}>
            {detail.job_log}
          </pre>
        </div>
      )}
    </>
  )
}
