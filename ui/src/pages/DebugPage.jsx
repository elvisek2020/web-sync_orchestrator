import React, { useState } from 'react'
import axios from 'axios'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'

export default function DebugPage() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const handleDownload = async () => {
    setLoading(true)
    setError(null)
    try {
      const { data } = await axios.get('/api/debug/diagnostics')
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `diagnostics_${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err.response?.data?.detail || err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <PageHeader title="Debug" subtitle="Stáhni diagnostický JSON pro analýzu." />
      {error && <div className="banner banner-danger">{error}</div>}
      <div style={{ marginTop: '16px' }}>
        <button
          className="btn btn-primary"
          onClick={handleDownload}
          disabled={loading}
        >
          {loading ? 'Stahuji…' : 'Stáhnout diagnostiku (JSON)'}
        </button>
      </div>

      <Card variant="info" title="Nápověda: Debug">
        <p className="text-sm" style={{ color: 'var(--color-text-light)', lineHeight: 1.6 }}>
          Stáhni diagnostiku obsahující přehled datasetů, scanů, diffů a batchů včetně vzorků cest a normalizace. JSON můžeš předat k analýze (např. při řešení nesouladu v plánu nebo chyb v porovnání).
        </p>
      </Card>
    </div>
  )
}
