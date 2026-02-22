import React, { useState, useEffect } from 'react'
import axios from 'axios'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'

export default function DebugPage() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [testPath, setTestPath] = useState('')
  const [testRoot, setTestRoot] = useState('')
  const [testResult, setTestResult] = useState(null)
  const [expandedSections, setExpandedSections] = useState({})

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const { data: d } = await axios.get('/api/debug/diagnostics')
      setData(d)
    } catch (err) {
      setError(err.response?.data?.detail || err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const toggle = (key) => setExpandedSections(prev => ({ ...prev, [key]: !prev[key] }))

  const testNormalization = async () => {
    try {
      const { data: r } = await axios.get('/api/debug/normalization-test', { params: { path: testPath, root: testRoot } })
      setTestResult(r)
    } catch (err) {
      setTestResult({ error: err.message })
    }
  }

  const renderJson = (obj) => (
    <pre style={{ background: 'var(--bg-secondary)', padding: '8px 12px', borderRadius: '6px', fontSize: '12px', overflow: 'auto', maxHeight: '400px', margin: '4px 0' }}>
      {JSON.stringify(obj, null, 2)}
    </pre>
  )

  const SectionHeader = ({ id, title, count, color }) => (
    <div
      onClick={() => toggle(id)}
      style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 0', userSelect: 'none' }}
    >
      <span style={{ fontFamily: 'monospace', color: 'var(--text-muted)', width: '16px' }}>
        {expandedSections[id] ? '▼' : '▶'}
      </span>
      <strong>{title}</strong>
      {count != null && (
        <span className={`badge badge-${color || 'default'}`} style={{ fontSize: '11px' }}>{count}</span>
      )}
    </div>
  )

  const PathTable = ({ rows, columns }) => (
    <div style={{ overflow: 'auto' }}>
      <table className="table" style={{ fontSize: '12px' }}>
        <thead>
          <tr>{columns.map(c => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map(c => (
                <td key={c} style={{ fontFamily: 'monospace', wordBreak: 'break-all', maxWidth: '400px' }}>
                  {typeof row[c] === 'boolean' ? (row[c] ? '✓' : '') : String(row[c] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )

  return (
    <div>
      <PageHeader title="Debug / Diagnostika" subtitle="Interní pohled na data, normalizaci cest a výsledky porovnání" />

      <div className="card card-info" style={{ marginBottom: '16px' }}>
        <strong>Jak použít:</strong> Stránka načte data automaticky po otevření. Tlačítko <strong>Obnovit data</strong> slouží k znovunačtení. Sekce (Datasety, Scany, Diffy, Batche) lze rozkliknout kliknutím na řádek. V <strong>Normalization Tester</strong> zadej cestu a root a klikni <strong>Test</strong> pro ověření normalizace.
      </div>

      <div style={{ marginBottom: '16px', display: 'flex', gap: '8px' }}>
        <button className="btn btn-primary btn-sm" onClick={load} disabled={loading}>
          {loading ? 'Načítám...' : 'Obnovit data'}
        </button>
      </div>

      {error && <div className="banner banner-danger">{error}</div>}

      {/* Normalization Tester */}
      <Card title="Normalization Tester" style={{ marginBottom: '16px' }}>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div>
            <label style={{ fontSize: '12px', display: 'block', marginBottom: '2px' }}>Path</label>
            <input
              className="form-input"
              value={testPath}
              onChange={e => setTestPath(e.target.value)}
              placeholder="share/Filmy/Movie/file.mkv"
              style={{ width: '350px', fontSize: '13px' }}
            />
          </div>
          <div>
            <label style={{ fontSize: '12px', display: 'block', marginBottom: '2px' }}>Root</label>
            <input
              className="form-input"
              value={testRoot}
              onChange={e => setTestRoot(e.target.value)}
              placeholder="Filmy"
              style={{ width: '200px', fontSize: '13px' }}
            />
          </div>
          <button className="btn btn-outline btn-sm" onClick={testNormalization}>Test</button>
        </div>
        {testResult && (
          <div style={{ marginTop: '8px' }}>
            {testResult.error
              ? <span className="text-danger">{testResult.error}</span>
              : <div style={{ fontFamily: 'monospace', fontSize: '13px' }}>
                  <span style={{ color: 'var(--text-muted)' }}>input:</span> {testResult.input_path}<br/>
                  <span style={{ color: 'var(--text-muted)' }}>root:</span> {testResult.input_root}<br/>
                  <span style={{ color: 'var(--success)' }}>normalized:</span> <strong>{testResult.normalized}</strong>
                  {testResult.ignored && <span className="badge badge-warning" style={{ marginLeft: '8px' }}>IGNORED</span>}
                </div>
            }
          </div>
        )}
      </Card>

      {data && (
        <>
          {/* Datasets */}
          <Card title={`Datasety (${data.datasets.length})`} style={{ marginBottom: '16px' }}>
            {data.datasets.map(ds => (
              <div key={ds.id} style={{ marginBottom: '12px', padding: '8px', background: 'var(--bg-secondary)', borderRadius: '6px' }}>
                <div style={{ display: 'flex', gap: '12px', alignItems: 'center', marginBottom: '4px' }}>
                  <strong>#{ds.id} {ds.name}</strong>
                  <span className="badge badge-default">{ds.location}</span>
                  <span className="badge badge-default">{ds.scan_adapter_type}</span>
                </div>
                <div style={{ fontSize: '12px', fontFamily: 'monospace' }}>
                  <span style={{ color: 'var(--text-muted)' }}>roots:</span> {JSON.stringify(ds.roots)}
                  <span style={{ marginLeft: '16px', color: 'var(--text-muted)' }}>base_path:</span> {ds.base_path}
                </div>
              </div>
            ))}
          </Card>

          {/* Scans */}
          <Card title={`Scany (${data.scans.length})`} style={{ marginBottom: '16px' }}>
            {data.scans.map(scan => (
              <div key={scan.id} style={{ marginBottom: '16px' }}>
                <SectionHeader
                  id={`scan-${scan.id}`}
                  title={`Scan #${scan.id} — ${scan.dataset_name} (${scan.dataset_location})`}
                  count={`${scan.total_files} files, ${scan.total_size_gb} GB`}
                  color="info"
                />
                {expandedSections[`scan-${scan.id}`] && (
                  <div style={{ marginLeft: '24px' }}>
                    <div style={{ fontSize: '12px', marginBottom: '8px' }}>
                      <strong>Dataset roots:</strong> <code>{JSON.stringify(scan.dataset_roots)}</code>
                      &nbsp; | <strong>Status:</strong> {scan.status}
                    </div>

                    <div style={{ fontSize: '12px', marginBottom: '8px' }}>
                      <strong>root_rel_path distribuce:</strong>
                      {scan.root_rel_path_distribution.map((r, i) => (
                        <span key={i} className="badge badge-default" style={{ marginLeft: '4px' }}>
                          {r.root_rel_path}: {r.count}
                        </span>
                      ))}
                    </div>

                    <div style={{ fontSize: '12px', marginBottom: '4px' }}><strong>Vzorky souborů + normalizace:</strong></div>
                    <PathTable
                      rows={scan.sample_files}
                      columns={['full_rel_path', 'root_rel_path', 'effective_root', 'normalized', 'ignored']}
                    />
                  </div>
                )}
              </div>
            ))}
          </Card>

          {/* Diffs */}
          <Card title={`Diffy (${data.diffs.length})`} style={{ marginBottom: '16px' }}>
            {data.diffs.map(diff => (
              <div key={diff.id} style={{ marginBottom: '16px' }}>
                <SectionHeader
                  id={`diff-${diff.id}`}
                  title={`Diff #${diff.id} — ${diff.source_dataset} → ${diff.target_dataset}`}
                  count={Object.entries(diff.category_counts).map(([k, v]) => `${k}: ${v}`).join(', ')}
                  color={diff.category_counts.missing > 100 ? 'danger' : 'success'}
                />
                {expandedSections[`diff-${diff.id}`] && (
                  <div style={{ marginLeft: '24px' }}>
                    {diff.error && <div className="banner banner-danger" style={{ marginBottom: '8px' }}>{diff.error}</div>}

                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '12px' }}>
                      {Object.entries(diff.category_counts).map(([cat, count]) => (
                        <div key={cat} style={{
                          padding: '6px 12px', borderRadius: '6px', fontSize: '13px',
                          background: cat === 'missing' ? 'var(--danger-bg, #fef2f2)' :
                                     cat === 'same' ? 'var(--success-bg, #f0fdf4)' :
                                     cat === 'conflict' ? 'var(--warning-bg, #fffbeb)' :
                                     'var(--bg-secondary)',
                          color: cat === 'missing' ? 'var(--danger)' :
                                 cat === 'same' ? 'var(--success)' :
                                 cat === 'conflict' ? 'var(--warning)' :
                                 'var(--text-muted)',
                        }}>
                          <strong>{count}</strong> {cat}
                        </div>
                      ))}
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '12px' }}>
                      <div>
                        <div style={{ fontSize: '12px', fontWeight: '600', marginBottom: '4px' }}>
                          Source normalizace (scan #{diff.source_scan_id}):
                        </div>
                        {diff.source_normalization_samples.map((s, i) => (
                          <div key={i} style={{ fontSize: '11px', fontFamily: 'monospace', marginBottom: '4px', padding: '4px', background: 'var(--bg-secondary)', borderRadius: '4px' }}>
                            <div style={{ color: 'var(--text-muted)' }}>{s.original}</div>
                            <div>root: <code>{s.root}</code> → <strong style={{ color: 'var(--success)' }}>{s.normalized}</strong></div>
                          </div>
                        ))}
                      </div>
                      <div>
                        <div style={{ fontSize: '12px', fontWeight: '600', marginBottom: '4px' }}>
                          Target normalizace (scan #{diff.target_scan_id}):
                        </div>
                        {diff.target_normalization_samples.map((s, i) => (
                          <div key={i} style={{ fontSize: '11px', fontFamily: 'monospace', marginBottom: '4px', padding: '4px', background: 'var(--bg-secondary)', borderRadius: '4px' }}>
                            <div style={{ color: 'var(--text-muted)' }}>{s.original}</div>
                            <div>root: <code>{s.root}</code> → <strong style={{ color: 'var(--success)' }}>{s.normalized}</strong></div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {Object.entries(diff.diff_item_samples).map(([cat, items]) => (
                      <div key={cat} style={{ marginBottom: '8px' }}>
                        <div style={{ fontSize: '12px', fontWeight: '600' }}>Vzorky — {cat}:</div>
                        <PathTable
                          rows={items}
                          columns={['path', 'source_size', 'target_size']}
                        />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </Card>

          {/* Batches */}
          <Card title={`Batche (${data.batches.length})`} style={{ marginBottom: '16px' }}>
            {data.batches.map(batch => (
              <div key={batch.id} style={{ marginBottom: '16px' }}>
                <SectionHeader
                  id={`batch-${batch.id}`}
                  title={`Batch #${batch.id} (diff #${batch.diff_id})`}
                  count={`${batch.total_items} items, ${batch.total_size_gb} GB`}
                  color="info"
                />
                {expandedSections[`batch-${batch.id}`] && (
                  <div style={{ marginLeft: '24px' }}>
                    <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
                      {Object.entries(batch.category_counts).map(([cat, count]) => (
                        <span key={cat} className="badge badge-default">{cat}: {count}</span>
                      ))}
                    </div>
                    <PathTable
                      rows={batch.sample_items}
                      columns={['path', 'size', 'category', 'enabled']}
                    />
                  </div>
                )}
              </div>
            ))}
          </Card>

          {/* Raw JSON dump */}
          <Card title="Raw JSON" style={{ marginBottom: '16px' }}>
            <SectionHeader id="raw-json" title="Zobrazit celý JSON dump" />
            {expandedSections['raw-json'] && renderJson(data)}
          </Card>
        </>
      )}
    </div>
  )
}
