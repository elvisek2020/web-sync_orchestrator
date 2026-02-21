import { useState, useEffect } from 'react'
import { useWebSocket } from './useWebSocket'
import axios from 'axios'

export function useMountStatus() {
  const [status, setStatus] = useState({
    nas1: { available: false, writable: false },
    usb: { available: false, writable: false },
    nas2: { available: false, writable: false },
    safe_mode: true,
    database: { available: false, db_path: null, error: null }
  })
  const { messages } = useWebSocket()
  
  useEffect(() => {
    // Initial load
    loadStatus()
  }, [])
  
  useEffect(() => {
    // Listen for WebSocket updates
    const mountMessages = messages.filter(m => m.type === 'mounts.status')
    if (mountMessages.length > 0) {
      const lastMessage = mountMessages[mountMessages.length - 1]
      setStatus(prev => ({ ...prev, ...lastMessage.data }))
    }
  }, [messages])
  
  const loadStatus = async () => {
    try {
      const response = await axios.get('/api/mounts/status')
      setStatus(response.data)
    } catch (error) {
      console.error('Failed to load mount status:', error)
    }
  }
  
  return {
    ...status,
    refresh: loadStatus
  }
}

