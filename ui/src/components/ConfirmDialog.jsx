import React, { useEffect, useRef } from 'react'

export default function ConfirmDialog({ open, title = 'Potvrzení', message, onConfirm, onCancel, danger }) {
  const confirmRef = useRef(null)

  useEffect(() => {
    if (open && confirmRef.current) confirmRef.current.focus()
  }, [open])

  if (!open) return null

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); onConfirm() }
    if (e.key === 'Escape') { e.preventDefault(); onCancel() }
  }

  return (
    <div className="confirm-overlay" onClick={onCancel} onKeyDown={handleKeyDown}>
      <div className="confirm-dialog" onClick={e => e.stopPropagation()}>
        <div className="confirm-title">{title}</div>
        <div className="confirm-message">{message}</div>
        <div className="confirm-actions">
          <button className="btn btn-secondary" onClick={onCancel}>Zrušit</button>
          <button ref={confirmRef} className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} onClick={onConfirm}>
            Potvrdit
          </button>
        </div>
      </div>
    </div>
  )
}
