"""
WebSocket manager - broadcast eventů klientům
"""
from fastapi import WebSocket
from typing import List, Dict, Any
import json

class WebSocketManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Připojí nového klienta"""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """Odpojí klienta"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        """Odešle zprávu všem připojeným klientům"""
        if not self.active_connections:
            return
        
        message_json = json.dumps(message)
        disconnected = []
        
        for connection in self.active_connections:
            try:
                await connection.send_text(message_json)
            except Exception as e:
                print(f"Error sending WebSocket message: {e}")
                disconnected.append(connection)
        
        # Odstranění odpojených klientů
        for conn in disconnected:
            self.disconnect(conn)

websocket_manager = WebSocketManager()

