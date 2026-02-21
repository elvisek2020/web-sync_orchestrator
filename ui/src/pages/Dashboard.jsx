import React, { useState, useEffect } from 'react'
import { useMountStatus } from '../hooks/useMountStatus'
import axios from 'axios'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { formatBytes, formatPercent } from '../utils'

export default function Dashboard() {
  const mountStatus = useMountStatus()
  const [datasets, setDatasets] = useState([])
  const [connectionStatus, setConnectionStatus] = useState({})
  const [testingConnections, setTestingConnections] = useState(new Set())
  const [phase, setPhase] = useState(localStorage.getItem('sync_phase') || 'planning')

  useEffect(() => {
    loadDatasets()
    const handler = (e) => { setPhase(e.detail); loadDatasets() }
    window.addEventListener('syncPhaseChanged', handler)
    return () => window.removeEventListener('syncPhaseChanged', handler)
  }, [])

  const loadDatasets = async () => {
    try {
      const { data } = await axios.get('/api/datasets/')
      const ds = Array.isArray(data) ? data : []
      setDatasets(ds)
      ds.forEach(d => {
        if (d.scan_adapter_type === 'ssh') setTimeout(() => testConnection(d.id), 500)
      })
    } catch { setDatasets([]) }
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

  const requiredMounts = phase === 'planning'
    ? { nas1: true, nas2: true, usb: false }
    : phase === 'copy-nas-hdd'
    ? { nas1: true, nas2: false, usb: true }
    : { nas1: false, nas2: true, usb: true }

  const byLocation = { NAS1: { has: false, local: false, ssh: false }, USB: { has: false, local: false }, NAS2: { has: false, local: false, ssh: false } }
  datasets.forEach(ds => {
    const loc = byLocation[ds.location]
    if (!loc) return
    loc.has = true
    if (ds.scan_adapter_type === 'local') loc.local = true
    if (ds.scan_adapter_type === 'ssh') loc.ssh = true
  })

  const phaseLabels = {
    planning: { title: 'Fáze 1: Plánování', img: '/images/faze_1.png', desc: 'NAS1 + NAS2', imgWidth: '75%' },
    'copy-nas-hdd': { title: 'Fáze 2: Kopírování NAS → HDD', img: '/images/faze_2.png', desc: 'NAS1 + HDD', imgWidth: '56.25%' },
    'copy-hdd-nas': { title: 'Fáze 3: Kopírování HDD → NAS', img: '/images/faze_3.png', desc: 'HDD + NAS2', imgWidth: '56.25%' },
  }
  const pl = phaseLabels[phase] || phaseLabels.planning

  const renderSshMount = (location) => {
    const ds = datasets.find(d => d.location === location && d.scan_adapter_type === 'ssh')
    if (!ds) return null
    const st = connectionStatus[ds.id]
    const testing = testingConnections.has(ds.id)
    return (
      <div className={`mount-card ${st?.connected ? 'available' : 'unavailable'}`}>
        <h3>{location} (SSH) {st?.connected ? '\u2713 Připojeno' : st ? '\u2717 Nepřipojeno' : '\u23F3'}</h3>
        <div className="mount-path">{ds.scan_adapter_config?.host || 'N/A'}:{ds.scan_adapter_config?.port || 22}</div>
        {st?.connected && st.message && <div className="text-sm" style={{ color: 'var(--color-success)' }}>{st.message}</div>}
        {st?.error && <div className="mount-error">{st.error}</div>}
        <button className="btn btn-outline btn-sm mt-sm" onClick={() => testConnection(ds.id)} disabled={testing}>Otestovat</button>
      </div>
    )
  }

  const renderLocalMount = (key, label, data) => {
    if (!data) return null
    return (
      <div className={`mount-card ${data.available ? 'available' : 'unavailable'}`}>
        <h3>{label} {data.available ? '\u2713 Dostupné' : '\u2717 Nedostupné'}{data.writable ? ' (RW)' : ''}</h3>
        <div className="mount-path">{data.path}</div>
        {data.available && data.total_size > 0 && (
          <div className="mount-stats">
            <span>Velikost: {formatBytes(data.total_size)}</span>
            <span>Využito: {formatBytes(data.used_size)} ({formatPercent(data.used_size, data.total_size)})</span>
            <span>Volné: {formatBytes(data.free_size)}</span>
          </div>
        )}
        {data.error && <div className="mount-error">{data.error}</div>}
      </div>
    )
  }

  return (
    <>
      <PageHeader title={pl.title} subtitle={`Potřebné zdroje: ${pl.desc}`} />

      <Card>
        <div className="phase-diagram">
          <img src={pl.img} alt={pl.title} style={{ maxWidth: pl.imgWidth }} />
        </div>
      </Card>

      <Card title="Stav připojení">
        <div className="banner banner-info mb-md">
          <strong>Aktuální fáze:</strong>&nbsp;{pl.title} (potřebuje {pl.desc})
        </div>

        <div className="card-grid">
          {requiredMounts.nas1 && byLocation.NAS1.has && (
            byLocation.NAS1.ssh ? renderSshMount('NAS1') : byLocation.NAS1.local && renderLocalMount('nas1', 'NAS1', mountStatus.nas1)
          )}
          {requiredMounts.usb && byLocation.USB.has && byLocation.USB.local && renderLocalMount('usb', 'USB', mountStatus.usb)}
          {requiredMounts.nas2 && byLocation.NAS2.has && (
            byLocation.NAS2.ssh ? renderSshMount('NAS2') : byLocation.NAS2.local && renderLocalMount('nas2', 'NAS2', mountStatus.nas2)
          )}
        </div>

        {/* Database status */}
        <div className={`banner ${mountStatus.database?.available ? 'banner-success' : 'banner-error'}`}>
          <div>
            <strong>Databáze {mountStatus.database?.available ? '\u2713 Připojena' : '\u2717 Nepřipojena'}</strong>
            {mountStatus.database?.db_path && <span> &mdash; <code>{mountStatus.database.db_path}</code></span>}
            {mountStatus.database?.error && <div className="mt-sm">{mountStatus.database.error}</div>}
          </div>
        </div>

        {mountStatus.safe_mode && (
          <div className="banner banner-warning mt-sm">
            <strong>SAFE MODE</strong>&nbsp;&mdash; USB nebo databáze není dostupná. Operace zápisu jsou zakázány.
          </div>
        )}
      </Card>
    </>
  )
}
