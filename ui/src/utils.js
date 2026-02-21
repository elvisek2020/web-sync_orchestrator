export function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return (bytes / Math.pow(k, i)).toFixed(i >= 3 ? 1 : 0) + ' ' + sizes[i]
}

export function formatGB(bytes) {
  return ((bytes || 0) / 1024 / 1024 / 1024).toFixed(1) + ' GB'
}

export function formatPercent(used, total) {
  if (!total) return '0%'
  return Math.round((used / total) * 100) + '%'
}

export function formatDate(dateStr) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('cs-CZ')
}

export function getDiffName(diff, scans, datasets) {
  if (!diff) return '-'
  const sourceScan = scans.find(s => s.id === diff.source_scan_id)
  const targetScan = scans.find(s => s.id === diff.target_scan_id)
  const sourceDs = sourceScan ? datasets.find(d => d.id === sourceScan.dataset_id) : null
  const targetDs = targetScan ? datasets.find(d => d.id === targetScan.dataset_id) : null
  const src = sourceDs ? sourceDs.name : `Scan #${diff.source_scan_id}`
  const tgt = targetDs ? targetDs.name : `Scan #${diff.target_scan_id}`
  return `${src} → ${tgt}`
}
