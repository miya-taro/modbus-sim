"""Persist application settings to JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from modbus_sim.datastore import SlaveRegistry, registry
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
        slave_registry: SlaveRegistry | None = None,
    ) -> None:
        reg = slave_registry or registry
        payload = {
            "tcp": settings_panel.to_dict().get("tcp", {}),
            "rtu": settings_panel.to_dict().get("rtu", {}),
            "slaves": reg.to_dict()["slaves"],
            "selected_slave_id": reg.selected_slave_id,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    def apply(
        self,
        settings_panel: SettingsPanel,
        slave_registry: SlaveRegistry | None = None,
    ) -> None:
        data = self.load()
        if not data:
            return
        settings_panel.apply_settings(data)
        reg = slave_registry or registry
        if "slaves" in data:
            reg.load_from_dict(data)
