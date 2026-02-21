import React from 'react'

export default function ConfirmDialog({ open, title = 'Potvrzení', message, onConfirm, onCancel, danger }) {
  if (!open) return null

  return (
    <div className="confirm-overlay" onClick={onCancel}>
      <div className="confirm-dialog" onClick={e => e.stopPropagation()}>
        <div className="confirm-title">{title}</div>
        <div className="confirm-message">{message}</div>
        <div className="confirm-actions">
          <button className="btn btn-secondary" onClick={onCancel}>Zrušit</button>
          <button className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} onClick={onConfirm}>
            Potvrdit
          </button>
        </div>
      </div>
    </div>
  )
}
