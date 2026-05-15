"""
WebSocket tests.

Uses a minimal in-process ASGI WebSocket client so tests run in the same
asyncio event loop as pytest-asyncio — no TestClient, no cross-loop issues.
"""
import asyncio
import io
import json
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class _WSClient:
    """
    Drives a single WebSocket connection directly against the ASGI app.
    Runs the endpoint coroutine as an asyncio Task in the current event loop
    so broadcasts from background tasks are delivered without any extra waiting.
    """

    def __init__(self, app, path: str) -> None:
        self._app = app
        self._path = path
        self._to_app: asyncio.Queue = asyncio.Queue()    # test → endpoint
        self._from_app: asyncio.Queue = asyncio.Queue()  # endpoint → test
        self._task: asyncio.Task | None = None

    async def connect(self) -> None:
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "headers": [],
            "path": self._path,
            "root_path": "",
            "scheme": "ws",
            "server": ("localhost", 8000),
            "query_string": b"",
            "client": ("127.0.0.1", 9999),
        }
        self._task = asyncio.create_task(
            self._app(scope, self._receive, self._send)
        )
        await self._to_app.put({"type": "websocket.connect"})
        msg = await self._from_app.get()
        assert msg["type"] == "websocket.accept", f"Expected accept, got {msg['type']}"

    async def _receive(self) -> dict:
        return await self._to_app.get()

    async def _send(self, message: dict) -> None:
        await self._from_app.put(message)

    async def receive_json(self, timeout: float = 5.0) -> dict:
        msg = await asyncio.wait_for(self._from_app.get(), timeout=timeout)
        assert msg["type"] == "websocket.send"
        text: str = msg.get("text") or (msg.get("bytes") or b"{}").decode()
        return json.loads(text)

    async def close(self) -> None:
        await self._to_app.put({"type": "websocket.disconnect", "code": 1000})
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()

    async def __aenter__(self) -> "_WSClient":
        await self.connect()
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()


async def test_ws_connect_receives_welcome(app) -> None:
    async with _WSClient(app, "/api/v1/ws/events") as ws:
        data = await ws.receive_json()
        assert data["event"] == "connected"
        assert "client_id" in data


async def test_ws_broadcast_on_extraction(app, client: AsyncClient) -> None:
    async with _WSClient(app, "/api/v1/ws/events") as ws:
        welcome = await ws.receive_json()
        assert welcome["event"] == "connected"

        response = await client.post(
            "/api/v1/documents",
            files={
                "file": (
                    "ws_extraction_test.txt",
                    io.BytesIO(b"WS test RFQ stainless steel CNC DDP Bremen EUR tolerance"),
                    "text/plain",
                )
            },
        )
        assert response.status_code == 202
        doc_id = response.json()["document_id"]

        msg = await ws.receive_json(timeout=5.0)
        assert msg["event"] == "extraction_complete"
        assert msg["document_id"] == doc_id
