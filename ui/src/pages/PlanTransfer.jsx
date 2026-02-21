import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { useMountStatus } from '../hooks/useMountStatus'
import { useWebSocket } from '../hooks/useWebSocket'
import { useNotification } from '../components/Notification'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import StatusBadge from '../components/StatusBadge'
import ConfirmDialog from '../components/ConfirmDialog'
import { formatGB, getDiffName } from '../utils'

export default function PlanTransfer() {
  const mountStatus = useMountStatus()
  const { messages } = useWebSocket()
  const notify = useNotification()
  const [diffs, setDiffs] = useState([])
  const [batches, setBatches] = useState([])
  const [scans, setScans] = useState([])
  const [datasets, setDatasets] = useState([])
  const [expandedBatches, setExpandedBatches] = useState(new Set())
  const [batchItems, setBatchItems] = useState({})
  const [batchProgress, setBatchProgress] = useState({})
  const [form, setForm] = useState({ diff_id: '', include_conflicts: false, exclude_patterns: '' })
  const [deleteTarget, setDeleteTarget] = useState(null)

  useEffect(() => {
    loadAll()
    const interval = setInterval(() => { loadDiffs(); loadBatches() }, 2000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    messages.forEach(msg => {
      if (msg.type === 'job.started' && msg.data.type === 'batch')
        setBatchProgress(prev => ({ ...prev, [msg.data.job_id]: { count: 0, total: msg.data.total || 0 } }))
      else if (msg.type === 'job.progress' && msg.data.type === 'batch')
        setBatchProgress(prev => ({ ...prev, [msg.data.job_id]: { count: msg.data.count || 0, total: msg.data.total || prev[msg.data.job_id]?.total || 0 } }))
      else if (msg.type === 'job.finished' && msg.data.type === 'batch') {
        setBatchProgress(prev => { const s = { ...prev }; delete s[msg.data.job_id]; return s })
        loadBatches()
      }
    })
  }, [messages])

  const loadAll = () => { loadDiffs(); loadBatches(); loadScans(); loadDatasets() }
  const loadDiffs = async () => { try { const { data } = await axios.get('/api/diffs/'); setDiffs(Array.isArray(data) ? data : []) } catch { setDiffs([]) } }
  const loadBatches = async () => { try { setBatches((await axios.get('/api/batches/')).data || []) } catch { setBatches([]) } }
  const loadScans = async () => { try { setScans((await axios.get('/api/scans/')).data || []) } catch { setScans([]) } }
  const loadDatasets = async () => { try { setDatasets((await axios.get('/api/datasets/')).data || []) } catch { setDatasets([]) } }

  const handleCreate = async () => {
    try {
      const excludeList = form.exclude_patterns ? form.exclude_patterns.split(/[,\n]/).map(s => s.trim()).filter(Boolean) : null
      await axios.post('/api/batches/', { diff_id: parseInt(form.diff_id), include_conflicts: form.include_conflicts, exclude_patterns: excludeList })
      setForm({ diff_id: '', include_conflicts: false, exclude_patterns: '' })
      notify('Plán vytvořen', 'success')
      loadBatches()
    } catch (err) {
      const detail = err.response?.data?.detail
      notify('Chyba: ' + (typeof detail === 'string' ? detail : JSON.stringify(detail) || err.message), 'error')
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    try { await axios.delete(`/api/batches/${deleteTarget}`); notify('Plán smazán', 'success'); loadBatches() }
    catch (err) { notify('Chyba: ' + (err.response?.data?.detail || err.message), 'error') }
    finally { setDeleteTarget(null) }
  }

  const toggleExpanded = (id) => {
    const s = new Set(expandedBatches)
    if (s.has(id)) s.delete(id)
    else { s.add(id); if (!batchItems[id]) loadBatchItems(id) }
    setExpandedBatches(s)
  }

  const loadBatchItems = async (id) => {
    try {
      const { data } = await axios.get(`/api/batches/${id}/items?limit=1000`)
      setBatchItems(prev => ({ ...prev, [id]: data }))
    } catch { setBatchItems(prev => ({ ...prev, [id]: [] })) }
  }

  const toggleItemEnabled = async (batchId, itemId, enabled) => {
    try {
      await axios.put(`/api/batches/${batchId}/items/${itemId}/enabled?enabled=${enabled}`)
      setBatchItems(prev => ({ ...prev, [batchId]: (prev[batchId] || []).map(i => i.id === itemId ? { ...i, enabled } : i) }))
    } catch (err) { notify('Chyba: ' + (err.response?.data?.detail || err.message), 'error') }
  }

  const toggleAll = async (batchId, enabled) => {
    try {
      await axios.put(`/api/batches/${batchId}/items/toggle-all?enabled=${enabled}`)
      setBatchItems(prev => ({ ...prev, [batchId]: (prev[batchId] || []).map(i => ({ ...i, enabled })) }))
    } catch (err) { notify('Chyba: ' + (err.response?.data?.detail || err.message), 'error') }
  }

  const exportCSV = (batchId, items) => {
    const enabled = items.filter(i => i.enabled !== false)
    const csv = 'Cesta,Velikost (GB)\n' + enabled.map(i => `"${i.full_rel_path.replace(/"/g, '""')}",${((i.size || 0) / 1024 / 1024 / 1024).toFixed(1)}`).join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob); a.download = `batch_${batchId}_export.csv`
    document.body.appendChild(a); a.click(); a.remove()
  }

  const showSummary = async (batch) => {
    try {
      const { data } = await axios.get(`/api/batches/${batch.id}/summary`)
      let diffInfo = ''
      try {
        const ds = (await axios.get(`/api/diffs/${batch.diff_id}/summary`)).data
        diffInfo = `\n\nZ porovnání: Chybí: ${ds.missing_count} (${formatGB(ds.missing_size)}), Stejné: ${ds.same_count}, Konflikty: ${ds.conflict_count}`
      } catch { }
      alert(`Plán #${batch.id}:\nSoubory: ${data.total_files || 0}\nVelikost: ${formatGB(data.total_size)}\nUSB volné: ${formatGB(data.usb_available)}\n\nInclude conflicts: ${batch.include_conflicts ? 'Ano' : 'Ne'}${diffInfo}`)
    } catch { notify('Chyba při načítání shrnutí', 'error') }
  }

  return (
    <>
      <PageHeader title="Plán přenosu" subtitle="Vytvoření plánu kopírování na základě porovnání" />

      <Card title="Vytvořit plán">
        <div className="form-group">
          <label className="form-label">Porovnání</label>
          <select className="input select" value={form.diff_id} onChange={e => setForm({ ...form, diff_id: e.target.value })}>
            <option value="">-- Vyberte porovnání --</option>
            {diffs.filter(d => d.status === 'completed').map(d => (
              <option key={d.id} value={d.id}>#{d.id}: {getDiffName(d, scans, datasets)}</option>
            ))}
          </select>
        </div>
        <div className="form-group">
          <label className="checkbox-label">
            <input type="checkbox" checked={form.include_conflicts} onChange={e => setForm({ ...form, include_conflicts: e.target.checked })} />
            Zahrnout konflikty
          </label>
          <span className="form-hint">Zahrne soubory se stejným názvem ale jinou velikostí. Přepíšou verzi na cíli.</span>
        </div>
        <div className="form-group">
          <label className="form-label">Výjimky (exclude patterns)</label>
          <input className="input text-mono" value={form.exclude_patterns} onChange={e => setForm({ ...form, exclude_patterns: e.target.value })}
            placeholder=".DS_Store, Thumbs.db, *.tmp" />
          <span className="form-hint">Výchozí: .DS_Store, ._*, .AppleDouble, Thumbs.db, desktop.ini, .Trash*, *.tmp, *.swp, *.bak, @eaDir, ...</span>
        </div>
        <button className="btn btn-primary" onClick={handleCreate} disabled={mountStatus.safe_mode || !form.diff_id}>
          Vytvořit plán
        </button>
      </Card>

      <Card title="Seznam plánů">
        {batches.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">{'\u{1F4CB}'}</div>
            <div className="empty-state-title">Žádné plány</div>
            <div className="empty-state-text">Vytvořte plán z porovnání výše.</div>
          </div>
        ) : (
          <table className="table">
            <thead><tr><th>ID</th><th>Porovnání</th><th>Status</th><th style={{ textAlign: 'right' }}>Akce</th></tr></thead>
            <tbody>
              {batches.map(batch => {
                const isExpanded = expandedBatches.has(batch.id)
                const items = batchItems[batch.id] || []
                const progress = batchProgress[batch.id]
                const isRunning = batch.status === 'running' || batch.status === 'pending'
                const diff = diffs.find(d => d.id === batch.diff_id)
                return (
                  <React.Fragment key={batch.id}>
                    <tr>
                      <td>{batch.id}</td>
                      <td>{diff ? `#${diff.id}: ${getDiffName(diff, scans, datasets)}` : `Porovnání #${batch.diff_id}`}</td>
                      <td>
                        <StatusBadge status={batch.status} />
                        {progress && isRunning && <span className="text-muted text-sm" style={{ marginLeft: '0.375rem' }}>({progress.count}/{progress.total})</span>}
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: '0.375rem', justifyContent: 'flex-end' }}>
                          <button className="btn btn-outline btn-sm" onClick={() => toggleExpanded(batch.id)}>
                            {isExpanded ? 'Skrýt' : 'Soubory'}
                          </button>
                          <button className="btn btn-success btn-sm" onClick={() => exportCSV(batch.id, items)} disabled={!items.length}>Export CSV</button>
                          <button className="btn btn-outline btn-sm" onClick={() => showSummary(batch)}>Shrnutí</button>
                          <button className="btn btn-danger btn-sm" onClick={() => setDeleteTarget(batch.id)} disabled={mountStatus.safe_mode}>Smazat</button>
                        </div>
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr>
                        <td colSpan="4" style={{ padding: '1rem', background: 'var(--color-border-light)' }}>
                          <div style={{ maxHeight: '400px', overflowY: 'auto' }}>
                            <div className="flex-between mb-sm">
                              <span className="text-sm" style={{ fontWeight: 600 }}>Soubory ({items.length})</span>
                              {items.length > 0 && (
                                <div style={{ display: 'flex', gap: '0.375rem', alignItems: 'center' }}>
                                  <button className="btn btn-outline btn-xs" onClick={() => toggleAll(batch.id, true)}>Označit vše</button>
                                  <button className="btn btn-outline btn-xs" onClick={() => toggleAll(batch.id, false)}>Odznačit vše</button>
                                  <span className="text-sm text-muted">{items.filter(i => i.enabled !== false).length}/{items.length}</span>
                                </div>
                              )}
                            </div>
                            {items.length === 0 ? (
                              <p className="text-muted text-sm">Načítání...</p>
                            ) : (
                              <table className="table">
                                <thead><tr><th style={{ width: 40 }}></th><th>Cesta</th><th style={{ textAlign: 'right' }}>Velikost</th><th>Kat.</th></tr></thead>
                                <tbody>
                                  {items.map(item => (
                                    <tr key={item.id} style={{ opacity: item.enabled !== false ? 1 : 0.4 }}>
                                      <td>
                                        <input type="checkbox" checked={item.enabled !== false} onChange={e => toggleItemEnabled(batch.id, item.id, e.target.checked)} style={{ cursor: 'pointer' }} />
                                      </td>
                                      <td className="text-mono text-sm">{item.full_rel_path}</td>
                                      <td className="nowrap" style={{ textAlign: 'right' }}>{formatGB(item.size)}</td>
                                      <td><StatusBadge status={item.category} /></td>
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
      </Card>

      <ConfirmDialog open={!!deleteTarget} title="Smazat plán" message="Opravdu chcete smazat tento plán?" danger onConfirm={handleDelete} onCancel={() => setDeleteTarget(null)} />
    </>
  )
}
