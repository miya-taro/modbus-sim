"""Modbus Simulator バックエンド（API サーバ）のエントリポイント。

単体起動（ブラウザで開く）:
    python -m modbus_sim --open
    modbus-sim-backend.exe --open

Tauri シェルがサイドカーとして起動する場合はブラウザを開かない:
    python -m modbus_sim --host 127.0.0.1 --port 0

--port 0 で OS 採番。実際の待受ポートを stdout へ 1 行 JSON で出力する:
    {"event": "listening", "host": "127.0.0.1", "port": 51234}
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from modbus_sim.api.server import create_app


def _frontend_dist() -> Path | None:
    # PyInstaller onefile 展開時は sys._MEIPASS 配下
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    for candidate in (base / "frontend_dist", base / "frontend" / "dist"):
        if (candidate / "index.html").is_file():
            return candidate
    return None


def _pick_port(host: str, port: int) -> int:
    if port != 0:
        return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def build_app():
    app = create_app()
    dist = _frontend_dist()
    if dist is not None:
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
    return app


def _open_browser_when_ready(url: str, host: str, port: int) -> None:
    def _wait_and_open() -> None:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                with socket.create_connection((host, port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.2)
        webbrowser.open(url)

    threading.Thread(target=_wait_and_open, daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="modbus_sim")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--log-level", default="warning")
    parser.add_argument(
        "--open",
        action="store_true",
        help="待受開始後、既定のブラウザで UI を開く（単体で動作確認する用）",
    )
    args = parser.parse_args(argv)

    port = _pick_port(args.host, args.port)
    browser_host = "127.0.0.1" if args.host in ("0.0.0.0", "::", "") else args.host
    url = f"http://{browser_host}:{port}/"
    print(
        json.dumps({"event": "listening", "host": args.host, "port": port, "url": url}),
        flush=True,
    )
    if args.open:
        _open_browser_when_ready(url, browser_host, port)

    uvicorn.run(
        build_app(),
        host=args.host,
        port=port,
        log_level=args.log_level,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
