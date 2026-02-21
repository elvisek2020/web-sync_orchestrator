import React from 'react'

export default function BrowseModal({ data, onClose, onNavigate, onSelect, onGoRoot, onGoUp }) {
  if (!data) return null

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: '900px' }}>
        <div className="modal-header">
          <h3 className="modal-title">
            {data.type === 'local' ? 'Procházení lokálního adresáře' : 'Procházení SSH hosta'}
          </h3>
          <button className="modal-close" onClick={onClose}>&times;</button>
        </div>

        <div className="modal-body">
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap', marginBottom: '1rem' }}>
            <button className="btn btn-outline btn-sm" onClick={onGoRoot}>Root</button>
            {data.path !== '/' && data.path !== data.mount_path && (
              <button className="btn btn-outline btn-sm" onClick={onGoUp}>Nahoru</button>
            )}
            <span className="text-sm text-muted">
              Cesta: <code>{data.relative_path || data.path}</code>
            </span>
          </div>

          {data.loading && <p className="text-muted text-sm">Načítání...</p>}
          {data.error && <div className="banner banner-error">{data.error}</div>}

          {!data.loading && !data.error && data.items && (
            <table className="table">
              <thead>
                <tr>
                  <th>Typ</th>
                  <th>Název</th>
                  <th>Velikost</th>
                  <th style={{ textAlign: 'right' }}>Akce</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item, idx) => (
                  <tr key={idx}>
                    <td>{item.is_directory ? 'Adresář' : 'Soubor'}</td>
                    <td className="text-mono">{item.name}</td>
                    <td className="nowrap">
                      {item.size != null ? `${(item.size / 1024 / 1024 / 1024).toFixed(1)} GB` : '-'}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <div style={{ display: 'flex', gap: '0.375rem', justifyContent: 'flex-end' }}>
                        {item.is_directory && (
                          <button className="btn btn-outline btn-sm" onClick={() => onNavigate(item.path)}>
                            Otevřít
                          </button>
                        )}
                        <button className="btn btn-success btn-sm" onClick={() => onSelect(item.path)}>
                          Vybrat
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
    </div>
  )
}
