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

export default function Compare() {
  const mountStatus = useMountStatus()
  const { messages } = useWebSocket()
  const notify = useNotification()
  const [diffs, setDiffs] = useState([])
  const [scans, setScans] = useState([])
  const [datasets, setDatasets] = useState([])
  const [phase, setPhase] = useState(localStorage.getItem('sync_phase') || 'planning')
  const [form, setForm] = useState({ source_scan_id: '', target_scan_id: '' })
  const [runningJobs, setRunningJobs] = useState({})
  const [diffProgress, setDiffProgress] = useState({})
  const [selectedDiff, setSelectedDiff] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)

  useEffect(() => {
    loadAll()
    const interval = setInterval(loadDiffs, 2000)
    const h = (e) => setPhase(e.detail)
    window.addEventListener('syncPhaseChanged', h)
    return () => { clearInterval(interval); window.removeEventListener('syncPhaseChanged', h) }
  }, [])

  useEffect(() => {
    messages.forEach(msg => {
      if (msg.type === 'job.started' && msg.data.type === 'diff') {
        setRunningJobs(prev => ({ ...prev, [msg.data.job_id]: true }))
        setDiffProgress(prev => ({ ...prev, [msg.data.job_id]: { count: 0, total: msg.data.total || 0 } }))
      } else if (msg.type === 'job.progress' && msg.data.type === 'diff') {
        setDiffProgress(prev => ({ ...prev, [msg.data.job_id]: { count: msg.data.count || 0, total: msg.data.total || prev[msg.data.job_id]?.total || 0 } }))
      } else if (msg.type === 'job.finished' && msg.data.type === 'diff') {
        setRunningJobs(prev => { const s = { ...prev }; delete s[msg.data.job_id]; return s })
        setDiffProgress(prev => { const s = { ...prev }; delete s[msg.data.job_id]; return s })
        loadDiffs()
      }
    })
  }, [messages])

  const loadAll = () => { loadDiffs(); loadScans(); loadDatasets() }
  const loadDiffs = async () => { try { setDiffs((await axios.get('/api/diffs/')).data) } catch { } }
  const loadScans = async () => { try { setScans((await axios.get('/api/scans/')).data.filter(s => s.status === 'completed')) } catch { } }
  const loadDatasets = async () => { try { setDatasets((await axios.get('/api/datasets/')).data) } catch { } }

  const handleCreate = async () => {
    if (!form.source_scan_id || !form.target_scan_id) return
    try {
      await axios.post('/api/diffs/', { source_scan_id: parseInt(form.source_scan_id), target_scan_id: parseInt(form.target_scan_id) })
      setForm({ source_scan_id: '', target_scan_id: '' })
      notify('Porovnání vytvořeno', 'success')
      loadDiffs()
    } catch (err) { notify('Chyba: ' + (err.response?.data?.detail || err.message), 'error') }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    try {
      await axios.delete(`/api/diffs/${deleteTarget}`)
      notify('Porovnání smazáno', 'success')
      loadDiffs()
    } catch (err) { notify('Chyba: ' + (err.response?.data?.detail || err.message), 'error') }
    finally { setDeleteTarget(null) }
  }

  const canPlan = phase === 'planning'

  return (
    <>
      <PageHeader title="Porovnání" subtitle="Porovnání dvou scanů pro identifikaci rozdílů" />

      <Card title="Vytvořit porovnání">
        {!canPlan && <div className="banner banner-warning mb-sm">Porovnání je dostupné pouze ve fázi 1 (Plánování).</div>}
        <div className="form-group">
          <label className="form-label">NAS1 scan (zdroj)</label>
          <select className="input select" value={form.source_scan_id} onChange={e => setForm({ ...form, source_scan_id: e.target.value })}>
            <option value="">-- Vyberte NAS1 scan --</option>
            {scans.filter(s => { const d = datasets.find(d => d.id === s.dataset_id); return d?.location === 'NAS1' }).map(s => {
              const ds = datasets.find(d => d.id === s.dataset_id)
              return <option key={s.id} value={s.id}>Scan #{s.id} - {ds?.name || `Dataset #${s.dataset_id}`} ({s.total_files || 0} souborů)</option>
            })}
          </select>
        </div>
        <div className="form-group">
          <label className="form-label">NAS2 scan (cíl)</label>
          <select className="input select" value={form.target_scan_id} onChange={e => setForm({ ...form, target_scan_id: e.target.value })}>
            <option value="">-- Vyberte NAS2 scan --</option>
            {scans.filter(s => { const d = datasets.find(d => d.id === s.dataset_id); return d?.location === 'NAS2' }).map(s => {
              const ds = datasets.find(d => d.id === s.dataset_id)
              return <option key={s.id} value={s.id}>Scan #{s.id} - {ds?.name || `Dataset #${s.dataset_id}`} ({s.total_files || 0} souborů)</option>
            })}
          </select>
        </div>
        <button className="btn btn-primary" onClick={handleCreate} disabled={!canPlan || !form.source_scan_id || !form.target_scan_id}>
          Vytvořit porovnání
        </button>
      </Card>

      <Card title="Seznam porovnání">
        {diffs.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">{'\u2194'}</div>
            <div className="empty-state-title">Žádná porovnání</div>
            <div className="empty-state-text">Vytvořte porovnání dvou scanů výše.</div>
          </div>
        ) : (
          <table className="table">
            <thead><tr><th>ID</th><th>Source → Target</th><th>Status</th><th>Vytvořeno</th><th style={{ textAlign: 'right' }}>Akce</th></tr></thead>
            <tbody>
              {diffs.map(diff => {
                const running = runningJobs[diff.id]
                const progress = diffProgress[diff.id]
                return (
                  <tr key={diff.id}>
                    <td>{diff.id}</td>
                    <td>{getDiffName(diff, scans, datasets)}</td>
                    <td>
                      <StatusBadge status={running ? 'running' : diff.status} />
                      {progress && <span className="text-muted text-sm" style={{ marginLeft: '0.375rem' }}>({progress.count}/{progress.total})</span>}
                      {diff.status === 'failed' && diff.error_message && <div className="banner banner-error mt-sm" style={{ marginBottom: 0, fontSize: '0.75rem' }}>{diff.error_message}</div>}
                    </td>
                    <td className="nowrap">{formatDate(diff.created_at)}</td>
                    <td>
                      <div style={{ display: 'flex', gap: '0.375rem', justifyContent: 'flex-end' }}>
                        <button className="btn btn-outline btn-sm" onClick={() => setSelectedDiff(selectedDiff === diff.id ? null : diff.id)}>
                          {selectedDiff === diff.id ? 'Skrýt' : 'Detail'}
                        </button>
                        <button className="btn btn-danger btn-sm" onClick={() => setDeleteTarget(diff.id)} disabled={mountStatus.safe_mode || diff.status === 'running'}>Smazat</button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </Card>

      {selectedDiff && (
        <Card title={`Detail porovnání #${selectedDiff}`}>
          <DiffDetail diffId={selectedDiff} />
        </Card>
      )}

      <Card variant="info" title="Nápověda: Porovnání">
        <p className="text-sm" style={{ color: 'var(--color-text-light)', lineHeight: 1.6 }}>
          Porovnejte scan NAS1 (source) se scanem NAS2 (target) pro identifikaci chybějících, přebývajících a konfliktních souborů.
          Výsledek se použije pro vytvoření plánu přenosu.
        </p>
      </Card>

      <ConfirmDialog open={!!deleteTarget} title="Smazat porovnání" message="Opravdu chcete smazat toto porovnání?" danger onConfirm={handleDelete} onCancel={() => setDeleteTarget(null)} />
    </>
  )
}

function DiffDetail({ diffId }) {
  const [items, setItems] = useState([])
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('')
  const [displayLimit, setDisplayLimit] = useState(500)

  useEffect(() => { loadSummary(); loadItems() }, [diffId, filter])

  const loadSummary = async () => { try { setSummary((await axios.get(`/api/diffs/${diffId}/summary`)).data) } catch { } }
  const loadItems = async () => {
    setLoading(true); setDisplayLimit(500)
    try {
      const params = new URLSearchParams({ limit: '5000' })
      if (filter) params.set('category', filter)
      const { data } = await axios.get(`/api/diffs/${diffId}/items?${params}`)
      const order = { missing: 1, conflict: 2, extra: 3, same: 4 }
      setItems([...data].sort((a, b) => (order[a.category] || 9) - (order[b.category] || 9) || (a.full_rel_path || '').localeCompare(b.full_rel_path || '')))
    } catch { } finally { setLoading(false) }
  }

  if (loading) return <p className="text-muted text-sm">Načítání...</p>

  const cats = ['', 'missing', 'conflict', 'extra', 'same']
  const catLabels = { '': 'Vše', missing: 'Chybí', conflict: 'Konflikt', extra: 'Přebývá', same: 'Stejné' }

  return (
    <>
      {summary && (
        <div className="summary-grid mb-md">
          <div className="summary-item"><strong>Celkem:</strong> {summary.total_files}</div>
          <div className="summary-item"><strong>Chybí:</strong> {summary.missing_count} ({formatGB(summary.missing_size)})</div>
          <div className="summary-item"><strong>Stejné:</strong> {summary.same_count} ({formatGB(summary.same_size)})</div>
          <div className="summary-item"><strong>Konflikty:</strong> {summary.conflict_count} ({formatGB(summary.conflict_size)})</div>
          <div className="summary-item"><strong>Přebývá:</strong> {summary.extra_count || 0} ({formatGB(summary.extra_size)})</div>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
        <span className="text-sm text-muted">Zobrazeno {Math.min(displayLimit, items.length)} z {items.length}</span>
        <div className="filter-pills">
          {cats.map(c => (
            <button key={c || 'all'} className={`filter-pill ${filter === c ? 'active' : ''}`} onClick={() => setFilter(c)}>
              {catLabels[c]}
            </button>
          ))}
        </div>
      </div>

      <table className="table">
        <thead><tr><th>Kategorie</th><th>Cesta</th><th>Velikost</th></tr></thead>
        <tbody>
          {items.slice(0, displayLimit).map(item => (
            <tr key={item.id}>
              <td><StatusBadge status={item.category} /></td>
              <td className="text-mono text-sm">{item.full_rel_path}</td>
              <td className="nowrap">{formatGB(item.source_size || item.target_size)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {items.length > displayLimit && (
        <button className="btn btn-outline mt-sm" onClick={() => setDisplayLimit(prev => prev + 500)}>
          Zobrazit dalších 500 ({items.length - displayLimit} zbývá)
        </button>
      )}
    </>
  )
}
