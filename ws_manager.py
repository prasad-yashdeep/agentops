"""WebSocket connection manager for real-time updates."""
import json
from typing import Dict, List
from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket connections and broadcasts."""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}  # user_name -> websocket
        self.presence: Dict[str, str] = {}  # user_name -> viewing_incident_id

    async def connect(self, websocket: WebSocket, user_name: str):
        await websocket.accept()
        self.active_connections[user_name] = websocket
        await self.broadcast_presence()

    def disconnect(self, user_name: str):
        self.active_connections.pop(user_name, None)
        self.presence.pop(user_name, None)

    async def broadcast(self, event_type: str, data: dict):
        """Broadcast an event to all connected clients."""
        message = json.dumps({"type": event_type, "data": data})
        dead = []
        for user_name, ws in self.active_connections.items():
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(user_name)
        for u in dead:
            self.disconnect(u)

    async def send_to(self, user_name: str, event_type: str, data: dict):
        """Send event to specific user."""
        ws = self.active_connections.get(user_name)
        if ws:
            try:
                await ws.send_text(json.dumps({"type": event_type, "data": data}))
            except Exception:
                self.disconnect(user_name)

    async def broadcast_presence(self):
        """Broadcast who's online and what they're viewing."""
        presence_data = {
            "online": list(self.active_connections.keys()),
            "viewing": self.presence,
        }
        await self.broadcast("presence", presence_data)

    def set_viewing(self, user_name: str, incident_id: str | None):
        if incident_id:
            self.presence[user_name] = incident_id
        else:
            self.presence.pop(user_name, None)


manager = ConnectionManager()
