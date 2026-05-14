import asyncio
import json
from datetime import datetime, timezone
from fastapi import WebSocket
from app.logger import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    """
    In-memory WebSocket connection manager.

    Production note: This works for a single-instance deployment.
    For horizontal scaling, replace with a Redis pub/sub-backed manager
    (e.g. using `redis.asyncio` + a fan-out channel per event type).
    """

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def connect(self, client_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[client_id] = websocket
        logger.info("WS client connected", extra={"client_id": client_id, "total": len(self._connections)})

    async def disconnect(self, client_id: str) -> None:
        async with self._lock:
            self._connections.pop(client_id, None)
        logger.info("WS client disconnected", extra={"client_id": client_id})

    async def broadcast(self, event_name: str, payload: dict, correlation_id: str | None = None) -> int:
        """Broadcast to all connected clients.  Returns the number of clients reached."""
        message = json.dumps({
            "event": event_name,
            "ts": datetime.now(timezone.utc).isoformat(),
            "correlation_id": correlation_id,
            **payload,
        })

        disconnected: list[str] = []
        reached = 0

        async with self._lock:
            snapshot = dict(self._connections)

        for client_id, ws in snapshot.items():
            try:
                await ws.send_text(message)
                reached += 1
            except Exception:
                disconnected.append(client_id)

        for client_id in disconnected:
            await self.disconnect(client_id)

        logger.info(
            "WS broadcast",
            extra={"event": event_name, "reached": reached, "dropped": len(disconnected)},
        )
        return reached

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# Singleton — imported by routes and services
manager = ConnectionManager()
