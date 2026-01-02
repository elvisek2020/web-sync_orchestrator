import { useState, useEffect, useRef } from 'react'

export function useWebSocket() {
  const [connected, setConnected] = useState(false)
  const [messages, setMessages] = useState([])
  const wsRef = useRef(null)
  
  useEffect(() => {
    let reconnectTimeout = null
    let isMounted = true
    
    const connect = () => {
      if (!isMounted) return
      
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = `${protocol}//${window.location.host}/ws`
      
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws
      
      ws.onopen = () => {
        if (isMounted) {
          setConnected(true)
          console.log('WebSocket connected')
        }
      }
      
      ws.onclose = () => {
        if (isMounted) {
          setConnected(false)
          console.log('WebSocket disconnected, reconnecting in 3 seconds...')
          // Reconnect after 3 seconds
          reconnectTimeout = setTimeout(() => {
            if (isMounted && wsRef.current === ws) {
              connect()
            }
          }, 3000)
        }
      }
      
      ws.onerror = (error) => {
        console.error('WebSocket error:', error)
        if (isMounted) {
          setConnected(false)
        }
      }
      
      ws.onmessage = (event) => {
        if (!isMounted) return
        try {
          const message = JSON.parse(event.data)
          setMessages(prev => [...prev, message])
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e)
        }
      }
    }
    
    connect()
    
    return () => {
      isMounted = false
      if (reconnectTimeout) {
        clearTimeout(reconnectTimeout)
      }
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [])
  
  return { connected, messages }
}

