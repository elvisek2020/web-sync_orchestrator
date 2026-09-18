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
  ready_to_phase_2: 'badge-completed',
  ready_to_phase_3: 'badge-completed',
  ready: 'badge-completed',
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
  ready_to_phase_2: 'Ready fáze 2',
  ready_to_phase_3: 'Ready fáze 3',
  ready: 'Ready',
}

export default function StatusBadge({ status, label }) {
  const cls = STATUS_MAP[status] || 'badge-muted'
  const text = label || LABEL_MAP[status] || status || 'unknown'
  return <span className={`badge ${cls}`}>{text}</span>
}
