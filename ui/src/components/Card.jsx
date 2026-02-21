import React from 'react'

export default function Card({ title, actions, children, variant, className = '' }) {
  const variantClass = variant ? `card-${variant}` : ''
  return (
    <div className={`card ${variantClass} ${className}`.trim()}>
      {title && (
        <div className="card-header">
          <h2 className="card-title">{title}</h2>
          {actions && <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>{actions}</div>}
        </div>
      )}
      <div className="card-body">{children}</div>
    </div>
  )
}
