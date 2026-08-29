"""FastAPI ベースのローカル API 層（Tauri フロントエンド向け）。"""

from modbus_sim.api.server import create_app

__all__ = ["create_app"]
