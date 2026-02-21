import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { useMountStatus } from '../hooks/useMountStatus'
import { useNotification } from '../components/Notification'
import ConfirmDialog from '../components/ConfirmDialog'
import BrowseModal from '../components/BrowseModal'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import StatusBadge from '../components/StatusBadge'

const EMPTY_FORM = {
  name: '', location: 'NAS1', roots: [''],
  scan_adapter_type: 'local', transfer_adapter_type: 'local',
  scan_adapter_config: {}, transfer_adapter_config: {}
}

export default function Datasets() {
  const mountStatus = useMountStatus()
  const notify = useNotification()
  const [datasets, setDatasets] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [editingDataset, setEditingDataset] = useState(null)
  const [connectionStatus, setConnectionStatus] = useState({})
  const [testingConnections, setTestingConnections] = useState(new Set())
  const [browsingDataset, setBrowsingDataset] = useState(null)
  const [formData, setFormData] = useState({ ...EMPTY_FORM })
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [phase, setPhase] = useState(localStorage.getItem('sync_phase') || 'planning')

  useEffect(() => { loadDatasets() }, [])
  useEffect(() => {
    const h = (e) => setPhase(e.detail)
    window.addEventListener('syncPhaseChanged', h)
    return () => window.removeEventListener('syncPhaseChanged', h)
  }, [])

  useEffect(() => {
    datasets.forEach(ds => {
      if (!connectionStatus[ds.id] && !testingConnections.has(ds.id))
        setTimeout(() => testConnection(ds.id), 500)
    })
  }, [datasets])

  const loadDatasets = async () => {
    try { setDatasets((await axios.get('/api/datasets/')).data) } catch { setDatasets([]) }
  }

  const testConnection = async (id) => {
    if (testingConnections.has(id)) return
    setTestingConnections(prev => new Set(prev).add(id))
    try {
      const { data } = await axios.get(`/api/datasets/${id}/test-connection`)
      setConnectionStatus(prev => ({ ...prev, [id]: { connected: data.connected, error: data.error, message: data.message } }))
    } catch (err) {
      setConnectionStatus(prev => ({ ...prev, [id]: { connected: false, error: err.response?.data?.detail || err.message } }))
    } finally {
      setTestingConnections(prev => { const s = new Set(prev); s.delete(id); return s })
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    try {
      const data = { ...formData, roots: formData.roots.filter(r => r.trim()) }
      if (editingDataset) await axios.put(`/api/datasets/${editingDataset.id}`, data)
      else await axios.post('/api/datasets/', data)
      setShowForm(false); setEditingDataset(null); setFormData({ ...EMPTY_FORM })
      notify(editingDataset ? 'Dataset uložen' : 'Dataset vytvořen', 'success')
      loadDatasets()
    } catch (err) {
      notify('Chyba: ' + (err.response?.data?.detail || err.message), 'error')
    }
  }

  const handleEdit = (ds) => {
    setEditingDataset(ds)
    setFormData({
      name: ds.name, location: ds.location, roots: ds.roots.length ? ds.roots : [''],
      scan_adapter_type: ds.scan_adapter_type, transfer_adapter_type: ds.transfer_adapter_type,
      scan_adapter_config: ds.scan_adapter_config || {}, transfer_adapter_config: ds.transfer_adapter_config || {}
    })
    setShowForm(true)
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    try {
      await axios.delete(`/api/datasets/${deleteTarget}`)
      notify('Dataset smazán', 'success')
      loadDatasets()
    } catch (err) {
      notify('Chyba při mazání: ' + (err.response?.data?.detail || err.message), 'error')
    } finally { setDeleteTarget(null) }
  }

  const handleDuplicate = async (ds) => {
    if (mountStatus.safe_mode) return notify('SAFE MODE - nelze duplikovat', 'warning')
    try {
      let newName = `${ds.name} (kopie)`
      let c = 1
      while (datasets.some(d => d.name === newName)) { c++; newName = `${ds.name} (kopie ${c})` }
      await axios.post('/api/datasets/', {
        name: newName, location: ds.location,
        roots: ds.roots?.length ? ds.roots : ['/'],
        scan_adapter_type: ds.scan_adapter_type || 'local',
        transfer_adapter_type: ds.transfer_adapter_type || 'local',
        scan_adapter_config: ds.scan_adapter_config || {},
        transfer_adapter_config: ds.transfer_adapter_config || {}
      })
      notify('Dataset duplikován', 'success')
      loadDatasets()
    } catch (err) { notify('Chyba: ' + (err.response?.data?.detail || err.message), 'error') }
  }

  const browseSSH = async (datasetId, path = '/') => {
    setBrowsingDataset({ datasetId, path, items: null, loading: true, type: 'ssh' })
    try {
      const { data } = await axios.get(`/api/datasets/${datasetId}/browse`, { params: { path } })
      setBrowsingDataset({ datasetId, path: data.path, items: data.items, loading: false, type: 'ssh' })
    } catch (err) {
      setBrowsingDataset({ datasetId, path, items: null, loading: false, error: err.response?.data?.detail || err.message, type: 'ssh' })
    }
  }

  const browseLocal = async (datasetId, path = '/', location = null) => {
    const loc = location || editingDataset?.location || formData.location
    setBrowsingDataset({ datasetId, path, items: null, loading: true, type: 'local', location: loc })
    try {
      let response
      if (datasetId === -1) {
        if (!loc) { notify('Vyberte lokaci', 'warning'); setBrowsingDataset(null); return }
        response = await axios.get('/api/datasets/browse-local', { params: { location: loc, path } })
      } else {
        response = await axios.get(`/api/datasets/${datasetId}/browse`, { params: { path } })
      }
      setBrowsingDataset({ datasetId, path: response.data.path, relative_path: response.data.relative_path, mount_path: response.data.mount_path, items: response.data.items, loading: false, type: 'local', location: loc })
    } catch (err) {
      setBrowsingDataset({ datasetId, path, items: null, loading: false, error: err.response?.data?.detail || err.message, type: 'local', location: loc })
    }
  }

  const selectPath = (path) => {
    const mp = browsingDataset?.mount_path
    if (browsingDataset?.type === 'local' && mp && path.startsWith(mp)) {
      let rel = path.substring(mp.length).replace(/^\//, '')
      setFormData({ ...formData, roots: [rel || '/'] })
    } else {
      setFormData({ ...formData, roots: [path] })
    }
    setBrowsingDataset(null)
  }

  const updateConfig = (section, field, value) => {
    setFormData({ ...formData, [section]: { ...formData[section], [field]: value } })
  }

  return (
    <>
      <PageHeader title="Datasety" subtitle="Konfigurace datových zdrojů a cílů"
        actions={!showForm && (
          <button className="btn btn-primary" onClick={() => { setShowForm(true); setEditingDataset(null); setFormData({ ...EMPTY_FORM }) }} disabled={mountStatus.safe_mode}>
            + Nový dataset
          </button>
        )}
      />

      {mountStatus.safe_mode && <div className="banner banner-warning mb-md"><strong>SAFE MODE</strong> &mdash; operace zápisu nejsou dostupné.</div>}

      {showForm && (
        <Card title={editingDataset ? 'Upravit dataset' : 'Nový dataset'}
          actions={<button className="btn btn-outline btn-sm" onClick={() => { setShowForm(false); setEditingDataset(null) }}>Zrušit</button>}
        >
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label className="form-label">Název</label>
              <input className="input" value={formData.name} onChange={e => setFormData({ ...formData, name: e.target.value })} required />
            </div>

            <div className="form-group">
              <label className="form-label">Lokace</label>
              <select className="input select" value={formData.location} onChange={e => setFormData({ ...formData, location: e.target.value })}>
                <option value="NAS1">NAS1 (zdrojový NAS)</option>
                <option value="USB">USB (přechodné úložiště)</option>
                <option value="NAS2">NAS2 (cílový NAS)</option>
              </select>
              <span className="form-hint">Určuje fyzické úložiště. Pro lokální mount se použije /mnt/nas1, /mnt/usb nebo /mnt/nas2.</span>
            </div>

            <div className="form-group">
              <label className="form-label">Způsob skenování</label>
              <select className="input select" value={formData.scan_adapter_type}
                onChange={e => setFormData({ ...formData, scan_adapter_type: e.target.value, scan_adapter_config: e.target.value === 'ssh' ? formData.scan_adapter_config : {} })}>
                <option value="local">Lokální souborový systém</option>
                <option value="ssh">Vzdálený SSH/SFTP</option>
              </select>
            </div>

            {formData.scan_adapter_type === 'ssh' && (
              <div className="subform">
                <div className="subform-title">SSH Scan konfigurace</div>
                <div className="form-group">
                  <label className="form-label">Host</label>
                  <input className="input" value={formData.scan_adapter_config?.host || ''} onChange={e => updateConfig('scan_adapter_config', 'host', e.target.value)} placeholder="192.168.1.100" required />
                </div>
                <div className="form-row">
                  <div className="form-group" style={{ flex: 1 }}>
                    <label className="form-label">Port</label>
                    <input className="input" type="number" value={formData.scan_adapter_config?.port || 22} onChange={e => updateConfig('scan_adapter_config', 'port', parseInt(e.target.value) || 22)} />
                  </div>
                  <div className="form-group" style={{ flex: 2 }}>
                    <label className="form-label">Username</label>
                    <input className="input" value={formData.scan_adapter_config?.username || ''} onChange={e => updateConfig('scan_adapter_config', 'username', e.target.value)} required />
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">Password</label>
                  <input className="input" type="password" value={formData.scan_adapter_config?.password || ''} onChange={e => updateConfig('scan_adapter_config', 'password', e.target.value)} required />
                </div>
                <div className="form-group">
                  <label className="form-label">Base path</label>
                  <input className="input" value={formData.scan_adapter_config?.base_path || '/'} onChange={e => updateConfig('scan_adapter_config', 'base_path', e.target.value)} placeholder="/" />
                  <span className="form-hint">Výchozí cesta na SSH serveru, ze které se relativně řeší root složky.</span>
                </div>
              </div>
            )}

            <div className="form-group">
              <label className="form-label">Způsob kopírování</label>
              <select className="input select" value={formData.transfer_adapter_type}
                onChange={e => setFormData({ ...formData, transfer_adapter_type: e.target.value, transfer_adapter_config: e.target.value === 'ssh' ? formData.transfer_adapter_config : {} })}>
                <option value="local">Lokální kopírování (rsync)</option>
                <option value="ssh">Vzdálené SSH kopírování (rsync)</option>
              </select>
            </div>

            {formData.transfer_adapter_type === 'ssh' && (
              <div className="subform">
                <div className="subform-title">SSH Transfer konfigurace</div>
                <div className="form-group">
                  <label className="form-label">Host</label>
                  <input className="input" value={formData.transfer_adapter_config?.host || ''} onChange={e => updateConfig('transfer_adapter_config', 'host', e.target.value)} placeholder="192.168.1.100" required />
                </div>
                <div className="form-row">
                  <div className="form-group" style={{ flex: 1 }}>
                    <label className="form-label">Port</label>
                    <input className="input" type="number" value={formData.transfer_adapter_config?.port || 22} onChange={e => updateConfig('transfer_adapter_config', 'port', parseInt(e.target.value) || 22)} />
                  </div>
                  <div className="form-group" style={{ flex: 2 }}>
                    <label className="form-label">Username</label>
                    <input className="input" value={formData.transfer_adapter_config?.username || ''} onChange={e => updateConfig('transfer_adapter_config', 'username', e.target.value)} required />
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">Password</label>
                  <input className="input" type="password" value={formData.transfer_adapter_config?.password || ''} onChange={e => updateConfig('transfer_adapter_config', 'password', e.target.value)} required />
                </div>
              </div>
            )}

            <div className="form-group">
              <label className="form-label">Root složka</label>
              <div className="form-row">
                <input className="input" style={{ flex: 1 }} value={formData.roots[0] || ''} onChange={e => setFormData({ ...formData, roots: [e.target.value] })} placeholder="/data/photos" required />
                {editingDataset && (
                  <button type="button" className="btn btn-outline btn-sm" onClick={() => {
                    if (formData.scan_adapter_type === 'ssh') browseSSH(editingDataset.id, formData.scan_adapter_config?.base_path || '/')
                    else browseLocal(editingDataset.id, '/')
                  }}>Procházet</button>
                )}
              </div>
              <span className="form-hint">Každý dataset má jednu root složku. Pro více složek vytvořte více datasetů.</span>
            </div>

            <div className="form-actions">
              <button type="button" className="btn btn-secondary" onClick={() => { setShowForm(false); setEditingDataset(null) }}>Zrušit</button>
              <button type="submit" className="btn btn-primary">{editingDataset ? 'Uložit' : 'Vytvořit'}</button>
            </div>
          </form>
        </Card>
      )}

      <Card title="Seznam datasetů">
        {datasets.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">{'\u{1F4BE}'}</div>
            <div className="empty-state-title">Žádné datasety</div>
            <div className="empty-state-text">Vytvořte první dataset pro zahájení synchronizace.</div>
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Název</th>
                <th>Lokace</th>
                <th>Root</th>
                <th>Scan</th>
                <th>Transfer</th>
                <th>Stav</th>
                <th style={{ textAlign: 'right' }}>Akce</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map(ds => {
                const st = connectionStatus[ds.id]
                const testing = testingConnections.has(ds.id)
                return (
                  <tr key={ds.id}>
                    <td>{ds.id}</td>
                    <td style={{ fontWeight: 500 }}>{ds.name || '-'}</td>
                    <td><StatusBadge status={ds.location === 'NAS1' ? 'info' : ds.location === 'USB' ? 'warning' : 'success'} label={ds.location} /></td>
                    <td className="text-mono text-sm">{ds.roots?.[0] || '-'}</td>
                    <td>{ds.scan_adapter_type}</td>
                    <td>{ds.transfer_adapter_type}</td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                        {testing ? <span className="text-muted text-sm">Testuji...</span>
                          : st ? (st.connected
                            ? <span style={{ color: 'var(--color-success)', fontWeight: 600, fontSize: '0.8125rem' }}>{'\u2713'} OK</span>
                            : <span style={{ color: 'var(--color-error)', fontWeight: 600, fontSize: '0.8125rem' }}>{'\u2717'}</span>
                          ) : <span className="text-muted text-sm">-</span>}
                        <button className="btn btn-outline btn-xs" onClick={() => testConnection(ds.id)} disabled={testing}>Test</button>
                      </div>
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: '0.375rem', justifyContent: 'flex-end' }}>
                        <button className="btn btn-outline btn-sm" onClick={() => handleEdit(ds)} disabled={mountStatus.safe_mode}>Upravit</button>
                        <button className="btn btn-outline btn-sm" onClick={() => handleDuplicate(ds)} disabled={mountStatus.safe_mode}>Duplikovat</button>
                        <button className="btn btn-danger btn-sm" onClick={() => setDeleteTarget(ds.id)} disabled={mountStatus.safe_mode}>Smazat</button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </Card>

      <Card variant="info" title="Nápověda: Datasety">
        <p className="text-sm" style={{ color: 'var(--color-text-light)', lineHeight: 1.6 }}>
          <strong>Dataset</strong> definuje logickou jednotku synchronizace: lokaci (NAS1/USB/NAS2), root složku,
          způsob skenování (lokální/SSH) a kopírování (rsync/SSH). Každý dataset má jednu root složku &mdash;
          pro více složek vytvořte více datasetů.
          {phase === 'planning' && <><br /><strong>Fáze 1:</strong> Vytvořte datasety pro NAS1 a NAS2.</>}
          {phase === 'copy-nas-hdd' && <><br /><strong>Fáze 2:</strong> Dataset pro NAS1 by měl být již vytvořen.</>}
          {phase === 'copy-hdd-nas' && <><br /><strong>Fáze 3:</strong> Dataset pro NAS2 by měl být již vytvořen.</>}
        </p>
      </Card>

      <ConfirmDialog open={!!deleteTarget} title="Smazat dataset" message="Opravdu chcete smazat tento dataset?" danger onConfirm={handleDelete} onCancel={() => setDeleteTarget(null)} />

      <BrowseModal data={browsingDataset} onClose={() => setBrowsingDataset(null)}
        onNavigate={(p) => browsingDataset?.type === 'local' ? browseLocal(browsingDataset.datasetId, p, browsingDataset.location) : browseSSH(browsingDataset.datasetId, p)}
        onSelect={selectPath}
        onGoRoot={() => browsingDataset?.type === 'local' ? browseLocal(browsingDataset.datasetId, '/', browsingDataset.location) : browseSSH(browsingDataset.datasetId, '/')}
        onGoUp={() => {
          const parent = browsingDataset?.path?.split('/').slice(0, -1).join('/') || '/'
          browsingDataset?.type === 'local' ? browseLocal(browsingDataset.datasetId, parent, browsingDataset.location) : browseSSH(browsingDataset.datasetId, parent)
        }}
      />
    </>
  )
}
