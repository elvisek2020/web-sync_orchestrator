import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { useMountStatus } from '../hooks/useMountStatus'
import './Datasets.css'

function Datasets() {
  const mountStatus = useMountStatus()
  const [datasets, setDatasets] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [editingDataset, setEditingDataset] = useState(null)
  const [connectionStatus, setConnectionStatus] = useState({}) // { datasetId: { connected, error, message } }
  const [testingConnections, setTestingConnections] = useState(new Set())
  const [browsingDataset, setBrowsingDataset] = useState(null) // { datasetId, path, items, loading }
  const [browsePath, setBrowsePath] = useState('/')
  const [formData, setFormData] = useState({
    name: '',
    location: 'NAS1',
    roots: [''],
    scan_adapter_type: 'local',
    transfer_adapter_type: 'local',
    scan_adapter_config: {},
    transfer_adapter_config: {}
  })
  
  useEffect(() => {
    loadDatasets()
  }, [])
  
  useEffect(() => {
    // Když se načtou datasety, otestovat připojení pro všechny
    if (datasets.length > 0) {
      datasets.forEach(ds => {
        if (!connectionStatus[ds.id] && !testingConnections.has(ds.id)) {
          // Malé zpoždění, aby se UI stihlo vykreslit
          setTimeout(() => testConnection(ds.id), 500)
        }
      })
    }
  }, [datasets])
  
  const loadDatasets = async () => {
    try {
      const response = await axios.get('/api/datasets/')
      setDatasets(response.data)
    } catch (error) {
      console.error('Failed to load datasets:', error)
    }
  }
  
  const handleSubmit = async (e) => {
    e.preventDefault()
    try {
      const data = {
        ...formData,
        roots: formData.roots.filter(r => r.trim() !== '')
      }
      
      if (editingDataset) {
        await axios.put(`/api/datasets/${editingDataset.id}`, data)
      } else {
        await axios.post('/api/datasets/', data)
      }
      
      setShowForm(false)
      setEditingDataset(null)
      setFormData({
        name: '',
        location: 'NAS1',
        roots: [''],
        scan_adapter_type: 'local',
        transfer_adapter_type: 'local',
        scan_adapter_config: {},
        transfer_adapter_config: {}
      })
      loadDatasets()
    } catch (error) {
      console.error('Failed to save dataset:', error)
      alert('Chyba při ukládání datasetu: ' + (error.response?.data?.detail || error.message))
    }
  }
  
  const handleEdit = (dataset) => {
    setEditingDataset(dataset)
    setFormData({
      name: dataset.name,
      location: dataset.location,
      roots: dataset.roots.length > 0 ? dataset.roots : [''],
      scan_adapter_type: dataset.scan_adapter_type,
      transfer_adapter_type: dataset.transfer_adapter_type,
      scan_adapter_config: dataset.scan_adapter_config || {},
      transfer_adapter_config: dataset.transfer_adapter_config || {}
    })
    setShowForm(true)
  }
  
  const handleDelete = async (id) => {
    if (!confirm('Opravdu chcete smazat tento dataset?')) return
    
    try {
      await axios.delete(`/api/datasets/${id}`)
      loadDatasets()
    } catch (error) {
      console.error('Failed to delete dataset:', error)
      alert('Chyba při mazání datasetu')
    }
  }
  
  const addRoot = () => {
    setFormData({ ...formData, roots: [...formData.roots, ''] })
  }
  
  const removeRoot = (index) => {
    setFormData({ ...formData, roots: formData.roots.filter((_, i) => i !== index) })
  }
  
  const updateRoot = (index, value) => {
    const newRoots = [...formData.roots]
    newRoots[index] = value
    setFormData({ ...formData, roots: newRoots })
  }
  
  const testConnection = async (datasetId) => {
    if (testingConnections.has(datasetId)) {
      return // Už se testuje
    }
    
    setTestingConnections(prev => new Set(prev).add(datasetId))
    
    try {
      const response = await axios.get(`/api/datasets/${datasetId}/test-connection`)
      setConnectionStatus(prev => ({
        ...prev,
        [datasetId]: {
          connected: response.data.connected,
          error: response.data.error,
          message: response.data.message
        }
      }))
    } catch (error) {
      setConnectionStatus(prev => ({
        ...prev,
        [datasetId]: {
          connected: false,
          error: error.response?.data?.detail || error.message || "Connection test failed"
        }
      }))
    } finally {
      setTestingConnections(prev => {
        const newSet = new Set(prev)
        newSet.delete(datasetId)
        return newSet
      })
    }
  }
  
  const browseSSH = async (datasetId, path = '/') => {
    setBrowsingDataset({ datasetId, path, items: null, loading: true, type: 'ssh' })
    setBrowsePath(path)
    
    try {
      const response = await axios.get(`/api/datasets/${datasetId}/browse`, {
        params: { path }
      })
      setBrowsingDataset({ datasetId, path: response.data.path, items: response.data.items, loading: false, type: 'ssh' })
    } catch (error) {
      setBrowsingDataset({ datasetId, path, items: null, loading: false, error: error.response?.data?.detail || error.message, type: 'ssh' })
    }
  }
  
  const browseLocal = async (datasetId, path = '/', location = null) => {
    // Pro nový dataset (datasetId === -1) použijeme location z formData
    const actualLocation = location || (editingDataset ? editingDataset.location : formData.location)
    setBrowsingDataset({ datasetId, path, items: null, loading: true, type: 'local', location: actualLocation })
    setBrowsePath(path)
    
    try {
      let response
      // Pro nový dataset použijeme endpoint bez datasetu
      if (datasetId === -1) {
        if (!actualLocation) {
          alert('Nejdříve vyberte Lokaci pro dataset')
          setBrowsingDataset(null)
          return
        }
        response = await axios.get(`/api/datasets/browse-local`, {
          params: { location: actualLocation, path }
        })
      } else {
        response = await axios.get(`/api/datasets/${datasetId}/browse`, {
          params: { path }
        })
      }
      
      setBrowsingDataset({ 
        datasetId, 
        path: response.data.path, 
        relative_path: response.data.relative_path,
        mount_path: response.data.mount_path,
        items: response.data.items, 
        loading: false, 
        type: 'local',
        location: actualLocation
      })
    } catch (error) {
      setBrowsingDataset({ datasetId, path, items: null, loading: false, error: error.response?.data?.detail || error.message, type: 'local', location: actualLocation })
    }
  }
  
  const selectPath = (path, isLocal = false) => {
    if (isLocal) {
      // Pro lokální cesty potřebujeme relativní cestu k mount pointu
      // path je absolutní cesta, potřebujeme relativní část
      const mountPath = browsingDataset?.mount_path
      if (mountPath && path.startsWith(mountPath)) {
        let relativePath = path.substring(mountPath.length)
        // Odstranit úvodní lomítko
        if (relativePath.startsWith('/')) {
          relativePath = relativePath.substring(1)
        }
        // Pokud je prázdné, použijeme '/'
        setFormData({ ...formData, roots: [relativePath || '/'] })
      } else {
        // Pokud nemáme mount_path, použijeme celou cestu
        setFormData({ ...formData, roots: [path] })
      }
    } else {
      setFormData({ ...formData, roots: [path] })
    }
    setBrowsingDataset(null)
  }
  
  const [phase, setPhase] = useState(localStorage.getItem('sync_phase') || 'planning')
  
  useEffect(() => {
    const handlePhaseChange = (e) => {
      setPhase(e.detail)
    }
    window.addEventListener('syncPhaseChanged', handlePhaseChange)
    return () => window.removeEventListener('syncPhaseChanged', handlePhaseChange)
  }, [])
  
  // Test připojení po načtení datasetů
  useEffect(() => {
    if (datasets.length > 0) {
      datasets.forEach(ds => {
        if (!connectionStatus[ds.id] && !testingConnections.has(ds.id)) {
          // Malé zpoždění, aby se UI stihlo vykreslit
          setTimeout(() => testConnection(ds.id), 500)
        }
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasets])
  
  return (
    <div className="datasets-page">
      <div className="box box-compact help-box">
        <h3>📖 Nápověda: Datasety</h3>
        <p><strong>Dataset</strong> je logická jednotka, která definuje:</p>
        <ul>
          <li><strong>Lokace:</strong> Asociace k fyzickému úložišti - NAS1 (zdrojový NAS), USB (přechodné úložiště), nebo NAS2 (cílový NAS). Určuje, který mount point nebo SSH server se použije.</li>
          <li><strong>Root složka:</strong> Každý dataset má pouze jednu root složku (např. `/data/photos`). Pokud chcete skenovat více složek na stejném serveru, vytvořte více datasetů - každý s jednou root složkou. To umožní spouštět scany a diffy pro každou složku samostatně.</li>
          <li><strong>Způsob skenování:</strong> Jak se data skenují - z lokálního souborového systému nebo přes SSH ze vzdáleného serveru</li>
          <li><strong>Způsob kopírování:</strong> Jak se data kopírují - lokálně pomocí rsync nebo přes SSH na vzdálený server</li>
        </ul>
        {phase === 'planning' && (
          <p style={{ marginTop: '0.75rem' }}><strong>Pro fázi 1 (Plánování):</strong> Vytvořte dataset pro NAS1 (lokace: NAS1, může být SSH) a dataset pro NAS2 (lokace: NAS2, může být SSH).</p>
        )}
        {phase === 'copy-nas-hdd' && (
          <p style={{ marginTop: '0.75rem' }}><strong>Pro fázi 2a (NAS → HDD):</strong> Dataset pro NAS1 by měl být již vytvořen ve fázi 1. USB dataset není potřeba - kopírování probíhá přímo.</p>
        )}
        {phase === 'copy-hdd-nas' && (
          <p style={{ marginTop: '0.75rem' }}><strong>Pro fázi 2b (HDD → NAS):</strong> Dataset pro NAS2 by měl být již vytvořen ve fázi 1. USB dataset není potřeba - kopírování probíhá přímo.</p>
        )}
      </div>
      
      <div className="box box-compact">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2>Datasety</h2>
          <button
            className="button"
            onClick={() => {
              setShowForm(!showForm)
              setEditingDataset(null)
              setFormData({
                name: '',
                location: 'NAS1',
                roots: ['/'],
                scan_adapter_type: 'local',
                transfer_adapter_type: 'local',
                scan_adapter_config: {},
                transfer_adapter_config: {}
              })
            }}
            disabled={mountStatus.safe_mode}
          >
            {showForm ? 'Zrušit' : '+ Nový dataset'}
          </button>
        </div>
        
        {mountStatus.safe_mode && (
          <div className="warning-box">
            <strong>⚠ SAFE MODE</strong>
            <p>Vytváření datasetů není dostupné v SAFE MODE.</p>
          </div>
        )}
        
        {showForm && (
          <form onSubmit={handleSubmit} className="dataset-form">
            <div className="form-group">
              <label className="label">Název</label>
              <input
                type="text"
                className="input"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                required
              />
            </div>
            
            <div className="form-group">
              <label className="label">Lokace (asociace k úložišti)</label>
              <select
                className="input"
                value={formData.location}
                onChange={(e) => setFormData({ ...formData, location: e.target.value })}
                required
              >
                <option value="NAS1">NAS1 (zdrojový NAS)</option>
                <option value="USB">USB (přechodné úložiště)</option>
                <option value="NAS2">NAS2 (cílový NAS)</option>
              </select>
              <small style={{ color: '#666', fontSize: '0.875rem', display: 'block', marginTop: '0.25rem' }}>
                Určuje, které fyzické úložiště tento dataset reprezentuje. Pro lokální mount se použije /mnt/nas1, /mnt/usb nebo /mnt/nas2.
              </small>
            </div>
            
            <div className="form-group">
              <label className="label">Způsob skenování</label>
              <select
                className="input"
                value={formData.scan_adapter_type}
                onChange={(e) => {
                  const newType = e.target.value
                  setFormData({ 
                    ...formData, 
                    scan_adapter_type: newType,
                    scan_adapter_config: newType === 'ssh' ? (formData.scan_adapter_config || {}) : {}
                  })
                }}
              >
                <option value="local">Lokální souborový systém</option>
                <option value="ssh">Vzdálený SSH/SFTP server</option>
              </select>
              <small style={{ color: '#666', fontSize: '0.875rem', display: 'block', marginTop: '0.25rem' }}>
                Určuje, jak se budou skenovat soubory - z lokálního mount pointu nebo přes SSH ze vzdáleného serveru.
              </small>
            </div>
            
            {formData.scan_adapter_type === 'ssh' && (
              <div style={{ marginLeft: '1rem', padding: '1rem', background: '#f8f9fa', borderRadius: '6px', border: '1px solid #e0e0e0' }}>
                <h3 style={{ fontSize: '0.9375rem', marginBottom: '0.75rem', color: '#555' }}>SSH Scan konfigurace</h3>
                <div className="form-group">
                  <label className="label">Host (IP nebo hostname)</label>
                  <input
                    type="text"
                    className="input"
                    value={formData.scan_adapter_config?.host || ''}
                    onChange={(e) => setFormData({ 
                      ...formData, 
                      scan_adapter_config: { ...formData.scan_adapter_config, host: e.target.value }
                    })}
                    placeholder="např. 192.168.1.100 nebo nas.example.com"
                    required
                  />
                </div>
                <div className="form-group">
                  <label className="label">Port</label>
                  <input
                    type="number"
                    className="input"
                    value={formData.scan_adapter_config?.port || 22}
                    onChange={(e) => setFormData({ 
                      ...formData, 
                      scan_adapter_config: { ...formData.scan_adapter_config, port: parseInt(e.target.value) || 22 }
                    })}
                    min="1"
                    max="65535"
                  />
                </div>
                <div className="form-group">
                  <label className="label">Username</label>
                  <input
                    type="text"
                    className="input"
                    value={formData.scan_adapter_config?.username || ''}
                    onChange={(e) => setFormData({ 
                      ...formData, 
                      scan_adapter_config: { ...formData.scan_adapter_config, username: e.target.value }
                    })}
                    placeholder="např. admin"
                    required
                  />
                </div>
                <div className="form-group">
                  <label className="label">Password</label>
                  <input
                    type="password"
                    className="input"
                    value={formData.scan_adapter_config?.password || ''}
                    onChange={(e) => setFormData({ 
                      ...formData, 
                      scan_adapter_config: { ...formData.scan_adapter_config, password: e.target.value }
                    })}
                    placeholder="SSH heslo"
                    required
                  />
                </div>
                <div className="form-group">
                  <label className="label">Base path (výchozí cesta na SSH serveru)</label>
                  <input
                    type="text"
                    className="input"
                    value={formData.scan_adapter_config?.base_path || '/'}
                    onChange={(e) => setFormData({ 
                      ...formData, 
                      scan_adapter_config: { ...formData.scan_adapter_config, base_path: e.target.value }
                    })}
                    placeholder="/"
                  />
                  <small style={{ color: '#666', fontSize: '0.875rem', display: 'block', marginTop: '0.25rem' }}>
                    Výchozí cesta na SSH serveru, ze které se pak relativně řeší root složky. Např. pokud base_path je <code>/data</code> a root složka je <code>photos</code>, pak se skenuje <code>/data/photos</code>. Pokud je base_path <code>/</code>, pak root složka musí být absolutní cesta.
                  </small>
                </div>
              </div>
            )}
            
            <div className="form-group">
              <label className="label">Způsob kopírování</label>
              <select
                className="input"
                value={formData.transfer_adapter_type}
                onChange={(e) => {
                  const newType = e.target.value
                  setFormData({ 
                    ...formData, 
                    transfer_adapter_type: newType,
                    transfer_adapter_config: newType === 'ssh' ? (formData.transfer_adapter_config || {}) : {}
                  })
                }}
              >
                <option value="local">Lokální kopírování (rsync)</option>
                <option value="ssh">Vzdálené SSH kopírování (rsync)</option>
              </select>
              <small style={{ color: '#666', fontSize: '0.875rem', display: 'block', marginTop: '0.25rem' }}>
                Určuje, jak se budou kopírovat soubory - lokálně pomocí rsync nebo přes SSH na vzdálený server.
              </small>
            </div>
            
            {formData.transfer_adapter_type === 'ssh' && (
              <div style={{ marginLeft: '1rem', padding: '1rem', background: '#f8f9fa', borderRadius: '6px', border: '1px solid #e0e0e0' }}>
                <h3 style={{ fontSize: '0.9375rem', marginBottom: '0.75rem', color: '#555' }}>SSH Transfer konfigurace</h3>
                <div className="form-group">
                  <label className="label">Host (IP nebo hostname)</label>
                  <input
                    type="text"
                    className="input"
                    value={formData.transfer_adapter_config?.host || ''}
                    onChange={(e) => setFormData({ 
                      ...formData, 
                      transfer_adapter_config: { ...formData.transfer_adapter_config, host: e.target.value }
                    })}
                    placeholder="např. 192.168.1.100 nebo nas.example.com"
                    required
                  />
                </div>
                <div className="form-group">
                  <label className="label">Port</label>
                  <input
                    type="number"
                    className="input"
                    value={formData.transfer_adapter_config?.port || 22}
                    onChange={(e) => setFormData({ 
                      ...formData, 
                      transfer_adapter_config: { ...formData.transfer_adapter_config, port: parseInt(e.target.value) || 22 }
                    })}
                    min="1"
                    max="65535"
                  />
                </div>
                <div className="form-group">
                  <label className="label">Username</label>
                  <input
                    type="text"
                    className="input"
                    value={formData.transfer_adapter_config?.username || ''}
                    onChange={(e) => setFormData({ 
                      ...formData, 
                      transfer_adapter_config: { ...formData.transfer_adapter_config, username: e.target.value }
                    })}
                    placeholder="např. admin"
                    required
                  />
                </div>
                <div className="form-group">
                  <label className="label">Password</label>
                  <input
                    type="password"
                    className="input"
                    value={formData.transfer_adapter_config?.password || ''}
                    onChange={(e) => setFormData({ 
                      ...formData, 
                      transfer_adapter_config: { ...formData.transfer_adapter_config, password: e.target.value }
                    })}
                    placeholder="SSH heslo"
                    required
                  />
                </div>
              </div>
            )}
            
            <div className="form-group">
              <label className="label">Root složka</label>
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                <input
                  type="text"
                  className="input"
                  value={formData.roots[0] || ''}
                  onChange={(e) => updateRoot(0, e.target.value)}
                  placeholder="např. /data/photos nebo data/photos"
                  required
                  style={{ flex: 1, minWidth: '200px' }}
                />
                {formData.scan_adapter_type === 'local' && (
                  <button
                    type="button"
                    className="button"
                    onClick={() => {
                      // Pro existující dataset můžeme procházet přímo
                      if (editingDataset) {
                        browseLocal(editingDataset.id, '/')
                      }
                    }}
                    disabled={!editingDataset}
                    style={{ background: editingDataset ? '#17a2b8' : '#6c757d', whiteSpace: 'nowrap', cursor: editingDataset ? 'pointer' : 'not-allowed' }}
                    title={!editingDataset ? 'Procházení je dostupné pouze při editaci existujícího datasetu' : 'Procházet'}
                  >
                    📁 Procházet
                  </button>
                )}
                {formData.scan_adapter_type === 'ssh' && (
                  <button
                    type="button"
                    className="button"
                    onClick={() => {
                      // Pro existující dataset můžeme procházet přímo
                      if (editingDataset) {
                        browseSSH(editingDataset.id, formData.scan_adapter_config?.base_path || '/')
                      }
                    }}
                    disabled={!editingDataset}
                    style={{ background: editingDataset ? '#17a2b8' : '#6c757d', whiteSpace: 'nowrap', cursor: editingDataset ? 'pointer' : 'not-allowed' }}
                    title={!editingDataset ? 'Procházení je dostupné pouze při editaci existujícího datasetu' : 'Procházet SSH hosta'}
                  >
                    📁 Procházet SSH hosta
                  </button>
                )}
              </div>
              <small style={{ color: '#666', fontSize: '0.875rem', display: 'block', marginTop: '0.25rem' }}>
                <strong>Důležité:</strong> Každý dataset má pouze jednu root složku. Pokud chcete skenovat více složek na stejném serveru, vytvořte více datasetů (každý s jednou root složkou).
              </small>
            </div>
            
            <button type="submit" className="button">
              {editingDataset ? 'Uložit změny' : 'Vytvořit dataset'}
            </button>
          </form>
        )}
      </div>
      
      <div className="box box-compact">
        <h2>Seznam datasetů</h2>
        {datasets.length === 0 ? (
          <p>Žádné datasety</p>
        ) : (
          <table className="datasets-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Název</th>
                <th>Lokace</th>
                <th>Roots</th>
                <th>Scan</th>
                <th>Transfer</th>
                <th>Stav připojení</th>
                <th>Akce</th>
              </tr>
            </thead>
            <tbody>
              {Array.isArray(datasets) && datasets.map(dataset => {
                const status = connectionStatus[dataset.id]
                const isTesting = testingConnections.has(dataset.id)
                
                return (
                  <tr key={dataset.id}>
                    <td>{dataset.id}</td>
                    <td>{dataset.name || '-'}</td>
                    <td>{dataset.location || '-'}</td>
                    <td>{Array.isArray(dataset.roots) && dataset.roots.length > 0 ? dataset.roots[0] : '-'}</td>
                    <td>{dataset.scan_adapter_type || '-'}</td>
                    <td>{dataset.transfer_adapter_type || '-'}</td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', whiteSpace: 'nowrap' }}>
                        {isTesting ? (
                          <span style={{ color: '#666', fontSize: '0.875rem' }}>Testuji...</span>
                        ) : status ? (
                          <>
                            {status.connected ? (
                              <span style={{ color: '#28a745', fontWeight: 'bold', fontSize: '0.875rem' }}>✓ Připojeno</span>
                            ) : (
                              <span style={{ color: '#dc3545', fontWeight: 'bold', fontSize: '0.875rem' }}>✗ Nepřipojeno</span>
                            )}
                            {status.error && (
                              <span style={{ color: '#666', fontSize: '0.75rem' }} title={status.error}>
                                ⚠
                              </span>
                            )}
                          </>
                        ) : (
                          <span style={{ color: '#999', fontSize: '0.875rem' }}>Neotestováno</span>
                        )}
                        <button
                          className="button"
                          onClick={() => testConnection(dataset.id)}
                          disabled={isTesting}
                          style={{ 
                            fontSize: '0.75rem', 
                            padding: '0.2rem 0.4rem',
                            background: '#6c757d',
                            flexShrink: 0
                          }}
                          title="Otestovat připojení"
                        >
                          🔄
                        </button>
                      </div>
                    </td>
                    <td>
                      <button
                        className="button"
                        onClick={() => handleEdit(dataset)}
                        disabled={mountStatus.safe_mode}
                        style={{ marginRight: '0.5rem', fontSize: '0.875rem', padding: '0.25rem 0.5rem' }}
                      >
                        Upravit
                      </button>
                      <button
                        className="button"
                        onClick={() => handleDelete(dataset.id)}
                        disabled={mountStatus.safe_mode}
                        style={{ background: '#dc3545', fontSize: '0.875rem', padding: '0.25rem 0.5rem' }}
                      >
                        Smazat
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
      
      {/* Browse Dialog (SSH nebo Local) */}
      {browsingDataset && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0,0,0,0.5)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 10000,
          overflow: 'auto',
          padding: '20px'
        }}>
          <div className="box" style={{ maxWidth: '800px', maxHeight: '80vh', overflow: 'auto', width: '90%' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <h2>{browsingDataset.type === 'local' ? 'Procházení lokálního adresáře' : 'Procházení SSH hosta'}</h2>
              <button
                className="button"
                onClick={() => setBrowsingDataset(null)}
                style={{ background: '#6c757d' }}
              >
                ✕ Zavřít
              </button>
            </div>
            
            <div style={{ marginBottom: '1rem' }}>
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                <button
                  className="button"
                  onClick={() => {
                    if (browsingDataset.type === 'local') {
                      browseLocal(browsingDataset.datasetId, '/', browsingDataset.location)
                    } else {
                      browseSSH(browsingDataset.datasetId, '/')
                    }
                  }}
                  disabled={browsingDataset.relative_path === '/' || (browsingDataset.path === '/' && !browsingDataset.mount_path)}
                  style={{ fontSize: '0.875rem', padding: '0.25rem 0.5rem' }}
                >
                  🏠 Root
                </button>
                {(browsingDataset.path !== '/' && browsingDataset.path !== browsingDataset?.mount_path) && (
                  <button
                    className="button"
                    onClick={() => {
                      if (browsingDataset.type === 'local') {
                        // Pro lokální cesty potřebujeme získat parent adresář
                        const pathParts = browsingDataset.path.split('/')
                        const parentPath = pathParts.slice(0, -1).join('/') || '/'
                        browseLocal(browsingDataset.datasetId, parentPath, browsingDataset.location)
                      } else {
                        const parentPath = browsingDataset.path.split('/').slice(0, -1).join('/') || '/'
                        browseSSH(browsingDataset.datasetId, parentPath)
                      }
                    }}
                    style={{ fontSize: '0.875rem', padding: '0.25rem 0.5rem' }}
                  >
                    ⬆ Nahoru
                  </button>
                )}
                <span style={{ color: '#666', fontSize: '0.875rem' }}>
                  Cesta: <code>{browsingDataset.relative_path || browsingDataset.path}</code>
                </span>
                {browsingDataset.mount_path && (
                  <span style={{ color: '#999', fontSize: '0.75rem' }}>
                    (Mount: <code>{browsingDataset.mount_path}</code>)
                  </span>
                )}
              </div>
            </div>
            
            {browsingDataset.loading && (
              <p>Načítání...</p>
            )}
            
            {browsingDataset.error && (
              <div className="warning-box">
                <strong>Chyba:</strong> {browsingDataset.error}
              </div>
            )}
            
            {!browsingDataset.loading && !browsingDataset.error && browsingDataset.items && (
              <div>
                <table className="datasets-table" style={{ fontSize: '0.875rem' }}>
                  <thead>
                    <tr>
                      <th>Typ</th>
                      <th>Název</th>
                      <th>Velikost</th>
                      <th>Akce</th>
                    </tr>
                  </thead>
                  <tbody>
                    {browsingDataset.items.map((item, idx) => (
                      <tr key={idx}>
                        <td>
                          {item.is_directory === true ? '📁 Adresář' : 
                           item.is_directory === false ? '📄 Soubor' : '❓'}
                        </td>
                        <td style={{ fontFamily: 'monospace' }}>{item.name}</td>
                        <td style={{ whiteSpace: 'nowrap' }}>
                          {item.size !== null && item.size !== undefined 
                            ? `${((item.size || 0) / 1024 / 1024 / 1024).toFixed(1)} GB` 
                            : '-'}
                        </td>
                        <td>
                          {item.is_directory === true ? (
                            <button
                              className="button"
                              onClick={() => {
                                if (browsingDataset.type === 'local') {
                                  browseLocal(browsingDataset.datasetId, item.path, browsingDataset.location)
                                } else {
                                  browseSSH(browsingDataset.datasetId, item.path)
                                }
                              }}
                              style={{ fontSize: '0.75rem', padding: '0.2rem 0.4rem' }}
                            >
                              Otevřít
                            </button>
                          ) : (
                            <span style={{ color: '#999' }}>-</span>
                          )}
                          <button
                            className="button"
                            onClick={() => selectPath(item.path, browsingDataset.type === 'local')}
                            style={{ 
                              marginLeft: '0.5rem', 
                              fontSize: '0.75rem', 
                              padding: '0.2rem 0.4rem',
                              background: '#28a745'
                            }}
                            title="Použít tuto cestu jako root složku"
                          >
                            ✓ Vybrat
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default Datasets

