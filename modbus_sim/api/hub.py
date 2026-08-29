"""WebSocket 接続の管理とブロードキャスト。"""

from __future__ import annotations

import asyncio
import contextlib

from starlette.websockets import WebSocket, WebSocketState


class Hub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            targets = list(self._clients)
        dead: list[WebSocket] = []
        for ws in targets:
            if ws.application_state != WebSocketState.CONNECTED:
                dead.append(ws)
                continue
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 - 切断済みクライアント
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)
                    with contextlib.suppress(Exception):
                        await ws.close()
