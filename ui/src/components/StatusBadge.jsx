import React from 'react'

const STATUS_MAP = {
  completed: 'badge-completed',
  running: 'badge-running',
  pending: 'badge-pending',
  failed: 'badge-failed',
  unknown: 'badge-unknown',
  missing: 'badge-missing',
  conflict: 'badge-conflict',
  extra: 'badge-extra',
  same: 'badge-same',
}

const LABEL_MAP = {
  completed: 'Dokončeno',
  running: 'Běží',
  pending: 'Čeká',
  failed: 'Chyba',
  missing: 'Chybí',
  conflict: 'Konflikt',
  extra: 'Přebývá',
  same: 'Stejné',
}

export default function StatusBadge({ status, label }) {
  const cls = STATUS_MAP[status] || 'badge-muted'
  const text = label || LABEL_MAP[status] || status || 'unknown'
  return <span className={`badge ${cls}`}>{text}</span>
}
