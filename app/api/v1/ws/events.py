import uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.api.v1.ws.connection_manager import manager
from app.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """
    WebSocket endpoint for live event delivery.

    Events emitted:
      - extraction_complete  → document processing finished
      - alert_detected       → new GDELT alert created
      - poll_run_complete    → GDELT poll run finished

    No authentication payload required for local testing.
    Connect with: ws://localhost:8000/api/v1/ws/events
    """
    client_id = str(uuid.uuid4())
    await manager.connect(client_id, websocket)

    try:
        # Send a welcome ping so the client knows it's live
        await websocket.send_json({
            "event": "connected",
            "client_id": client_id,
            "message": "Connected to RFQ event stream. Waiting for events...",
        })

        # Keep the connection open; client messages are ignored (read-only channel)
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        await manager.disconnect(client_id)
    except Exception as exc:
        logger.exception("WS error", extra={"client_id": client_id, "error": str(exc)})
        await manager.disconnect(client_id)
