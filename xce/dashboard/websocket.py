"""
WebSocket Manager for XCE Dashboard
Manages WebSocket connections for real-time updates
"""

import asyncio
from typing import Dict, List
from fastapi import WebSocket


class WebSocketManager:
    """Manages WebSocket connections"""
    
    def __init__(self):
        self._connections: Dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str):
        """Accept and store a WebSocket connection"""
        await websocket.accept()
        self._connections[client_id] = websocket
    
    def disconnect(self, client_id: str):
        """Remove a WebSocket connection"""
        if client_id in self._connections:
            del self._connections[client_id]
    
    async def send_personal(self, client_id: str, message: dict):
        """Send message to a specific client"""
        if client_id in self._connections:
            try:
                await self._connections[client_id].send_json(message)
            except Exception:
                # Connection might be closed
                self.disconnect(client_id)
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        disconnected = []
        for client_id, websocket in self._connections.items():
            try:
                await websocket.send_json(message)
            except Exception:
                disconnected.append(client_id)
        
        # Clean up disconnected clients
        for client_id in disconnected:
            self.disconnect(client_id)
    
    def get_connected_count(self) -> int:
        """Get number of connected clients"""
        return len(self._connections)