"""Persist application settings to JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from modbus_sim.datastore import SlaveRegistry, rtu_registry, tcp_registry
from modbus_sim.ui.settings_panel import SettingsPanel


def settings_path() -> Path:
    return Path.home() / ".modbus_sim" / "settings.json"


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or settings_path()

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            with self._path.open(encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save(
        self,
        settings_panel: SettingsPanel,
        tcp_slaves: SlaveRegistry | None = None,
        rtu_slaves: SlaveRegistry | None = None,
    ) -> None:
        tcp_reg = tcp_slaves or tcp_registry
        rtu_reg = rtu_slaves or rtu_registry
        panel = settings_panel.to_dict()
        payload = {
            "tcp": panel.get("tcp", {}),
            "rtu": panel.get("rtu", {}),
            "tcp_slaves": tcp_reg.to_dict()["slaves"],
            "tcp_selected_slave_id": tcp_reg.selected_slave_id,
            "rtu_slaves": rtu_reg.to_dict()["slaves"],
            "rtu_selected_slave_id": rtu_reg.selected_slave_id,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    def apply(
        self,
        settings_panel: SettingsPanel,
        tcp_slaves: SlaveRegistry | None = None,
        rtu_slaves: SlaveRegistry | None = None,
    ) -> None:
        data = self.load()
        if not data:
            return
        self._apply_data(data, settings_panel, tcp_slaves, rtu_slaves)

    def apply_from_path(
        self,
        settings_panel: SettingsPanel,
        tcp_slaves: SlaveRegistry | None = None,
        rtu_slaves: SlaveRegistry | None = None,
    ) -> None:
        """`load()` と異なり、読み込み失敗時に例外を送出する（明示的なインポート用）。"""
        with self._path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("設定ファイルの形式が不正です")
        self._apply_data(data, settings_panel, tcp_slaves, rtu_slaves)

    def _apply_data(
        self,
        data: dict[str, Any],
        settings_panel: SettingsPanel,
        tcp_slaves: SlaveRegistry | None,
        rtu_slaves: SlaveRegistry | None,
    ) -> None:
        settings_panel.apply_settings(data)
        tcp_reg = tcp_slaves or tcp_registry
        rtu_reg = rtu_slaves or rtu_registry

        if "tcp_slaves" in data:
            tcp_reg.load_from_dict(
                {
                    "slaves": data.get("tcp_slaves", []),
                    "selected_slave_id": data.get("tcp_selected_slave_id", 1),
                }
            )
        elif "slaves" in data:
            # 旧形式: 共通 slaves → TCP 側へ移行
            tcp_reg.load_from_dict(data)

        if "rtu_slaves" in data:
            rtu_reg.load_from_dict(
                {
                    "slaves": data.get("rtu_slaves", []),
                    "selected_slave_id": data.get("rtu_selected_slave_id", 1),
                }
            )
