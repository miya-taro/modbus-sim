"""Modbus TCP/RTU simulator entry point.

UI は Tauri（Rust シェル + React フロント）へ移行済み。このエントリは
バックエンド（FastAPI + WebSocket）を起動する。Tauri がサイドカーとして呼ぶ。
単体でも `python main.py --port 8000` として起動し、ブラウザから利用できる。
"""

from modbus_sim.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
