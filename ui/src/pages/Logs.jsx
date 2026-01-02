import React, { useState, useEffect } from 'react'
import axios from 'axios'
import './Logs.css'

function Logs() {
  const [jobs, setJobs] = useState([])
  const [selectedJob, setSelectedJob] = useState(null)
  
  useEffect(() => {
    loadJobs()
  }, [])
  
  const loadJobs = async () => {
    try {
      const response = await axios.get('/api/copy/jobs')
      setJobs(response.data)
    } catch (error) {
      console.error('Failed to load jobs:', error)
    }
  }
  
  return (
    <div className="logs-page">
      <div className="box box-compact">
        <h2>Historie jobů</h2>
        {jobs.length === 0 ? (
          <p>Žádné joby</p>
        ) : (
          <table className="jobs-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Typ</th>
                <th>Status</th>
                <th>Začátek</th>
                <th>Konec</th>
                <th>Akce</th>
              </tr>
            </thead>
            <tbody>
              {Array.isArray(jobs) && jobs.map(job => (
                <tr key={job.id}>
                  <td>{job.id}</td>
                  <td>{job.type || '-'}</td>
                  <td>
                    <span className={`status-badge ${job.status || 'unknown'}`}>
                      {job.status || 'unknown'}
                    </span>
                  </td>
                  <td>{job.started_at ? new Date(job.started_at).toLocaleString('cs-CZ') : '-'}</td>
                  <td>{job.finished_at ? new Date(job.finished_at).toLocaleString('cs-CZ') : '-'}</td>
                  <td>
                    <button
                      className="button"
                      onClick={() => setSelectedJob(job)}
                    >
                      Detail
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      
      {selectedJob && (
        <div className="box">
          <h2>Detail jobu #{selectedJob.id}</h2>
          <div className="job-detail">
            <p><strong>Typ:</strong> {selectedJob.type}</p>
            <p><strong>Status:</strong> {selectedJob.status}</p>
            <p><strong>Začátek:</strong> {new Date(selectedJob.started_at).toLocaleString('cs-CZ')}</p>
            {selectedJob.finished_at && (
              <p><strong>Konec:</strong> {new Date(selectedJob.finished_at).toLocaleString('cs-CZ')}</p>
            )}
            {selectedJob.error_message && (
              <div className="error-message">
                <strong>Chyba:</strong>
                <pre>{selectedJob.error_message}</pre>
              </div>
            )}
            {selectedJob.metadata && (
              <div className="job-metadata">
                <strong>Metadata:</strong>
                <pre>{JSON.stringify(selectedJob.metadata, null, 2)}</pre>
              </div>
            )}
          </div>
          <button className="button" onClick={() => setSelectedJob(null)}>
            Zavřít
          </button>
        </div>
      )}
    </div>
  )
}

export default Logs

