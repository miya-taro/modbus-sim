"""Persist application settings to JSON.

設定ファイルの読み書きだけを担う薄いラッパ。CommSettings ⇔ dict の変換は
`modbus_sim.settings_model`、レジストリの load/save は `SlaveRegistry` 側にある。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def settings_path() -> Path:
    return Path.home() / ".modbus_sim" / "settings.json"


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or settings_path()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            with self._path.open(encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def write_payload(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
