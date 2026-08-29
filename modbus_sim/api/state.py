"""API サーバのアプリケーション状態。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from modbus_sim.config import CommMode, RegisterKind
from modbus_sim.datastore import (
    SlaveRegistry,
    decode_value,
    format_decoded_display,
    rtu_registry,
    tcp_registry,
)
from modbus_sim.identity import DeviceIdentity
from modbus_sim.models import CommSettings, RegisterPoint
from modbus_sim.wordorder import WordOrder
from modbus_sim.server_manager import ModbusServerManager
from modbus_sim.settings_model import apply_dict_to_comm, comm_to_dict
from modbus_sim.settings_store import SettingsStore

_KIND_BY_SLUG = {
    "hr": RegisterKind.HOLDING_REGISTER,
    "ir": RegisterKind.INPUT_REGISTER,
    "coil": RegisterKind.COIL,
    "di": RegisterKind.DISCRETE_INPUT,
}
_SLUG_BY_KIND = {v: k for k, v in _KIND_BY_SLUG.items()}


def kind_from_slug(slug: str) -> RegisterKind:
    try:
        return _KIND_BY_SLUG[slug]
    except KeyError:
        raise ValueError(f"未知の kind: {slug}") from None


def kind_to_slug(kind: RegisterKind) -> str:
    return _SLUG_BY_KIND[kind]


def point_to_dict(point: RegisterPoint, word_order: WordOrder = WordOrder.ABCD) -> dict:
    data = {
        "address": point.address,
        "kind": kind_to_slug(point.kind),
        "datatype": point.datatype.value,
        "raw": point.raw,
        "decoded_hex": format_decoded_display(point, word_order),
        "decoded": decode_value(point),
        "tag": point.tag,
        "advanced": point.has_advanced_settings(),
        "fault_mode": point.fault_mode.value,
        "fault_exception": point.fault_exception.value,
        "delay_min_ms": point.delay_min_ms,
        "delay_max_ms": point.delay_max_ms,
        "auto_mode": point.auto_mode.value,
        "auto_min": point.auto_min,
        "auto_max": point.auto_max,
        "auto_step": point.auto_step,
        "auto_period_sec": point.auto_period_sec,
    }
    return data


class AppState:
    POLL_INTERVAL_SEC = 0.4

    def __init__(self, settings_path: Path | None = None) -> None:
        self.tcp_registry: SlaveRegistry = tcp_registry
        self.rtu_registry: SlaveRegistry = rtu_registry
        self.comm = CommSettings()
        self.identity = DeviceIdentity()
        self.settings_store = SettingsStore(settings_path)
        self._save_task: asyncio.Task | None = None

        self.manager = ModbusServerManager(
            tcp_registry=self.tcp_registry,
            rtu_registry=self.rtu_registry,
            on_log=self._on_log,
            on_tcp_state_change=lambda _r: self._mark_dirty("server_state"),
            on_rtu_state_change=lambda _r: self._mark_dirty("server_state"),
            on_tcp_client_count_change=lambda _n: self._mark_dirty("server_state"),
        )
        self._dirty: set[str] = {"server_state", "log"}
        self._last_log_count = 0

        self.load_settings()

    # --- registry helpers -------------------------------------------------
    def registry(self, mode: str) -> SlaveRegistry:
        if mode == CommMode.TCP.value:
            return self.tcp_registry
        if mode == CommMode.RTU.value:
            return self.rtu_registry
        raise ValueError(f"未知の mode: {mode}")

    # --- settings -------------------------------------------------------
    def load_settings(self) -> None:
        data = self.settings_store.load()
        apply_dict_to_comm(self.comm, data)
        if "identity" in data:
            self.identity = DeviceIdentity.from_dict(data["identity"])
        if "tcp_slaves" in data:
            self.tcp_registry.load_from_dict(
                {
                    "slaves": data.get("tcp_slaves", []),
                    "selected_slave_id": data.get("tcp_selected_slave_id", 1),
                }
            )
        elif "slaves" in data:
            self.tcp_registry.load_from_dict(data)
        if "rtu_slaves" in data:
            self.rtu_registry.load_from_dict(
                {
                    "slaves": data.get("rtu_slaves", []),
                    "selected_slave_id": data.get("rtu_selected_slave_id", 1),
                }
            )

    def settings_payload(self) -> dict:
        panel = comm_to_dict(self.comm)
        return {
            "tcp": panel.get("tcp", {}),
            "rtu": panel.get("rtu", {}),
            "identity": self.identity.to_dict(),
            "tcp_slaves": self.tcp_registry.to_dict()["slaves"],
            "tcp_selected_slave_id": self.tcp_registry.selected_slave_id,
            "rtu_slaves": self.rtu_registry.to_dict()["slaves"],
            "rtu_selected_slave_id": self.rtu_registry.selected_slave_id,
        }

    def schedule_save(self) -> None:
        """500ms デバウンスでバックグラウンド保存。"""
        if self._save_task is not None and not self._save_task.done():
            self._save_task.cancel()
        self._save_task = asyncio.create_task(self._debounced_save())

    async def _debounced_save(self) -> None:
        try:
            await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return
        payload = self.settings_payload()
        await asyncio.to_thread(
            SettingsStore.write_payload, self.settings_store.path, payload
        )

    # --- dirty flags / broadcast --------------------------------------
    def _on_log(self, _msg: str) -> None:
        self._mark_dirty("log")

    def _mark_dirty(self, key: str) -> None:
        self._dirty.add(key)

    def take_dirty(self) -> set[str]:
        dirty, self._dirty = self._dirty, set()
        return dirty

    # --- snapshots ---------------------------------------------------
    def server_state(self) -> dict:
        return {
            "tcp_running": self.manager.tcp_running,
            "rtu_running": self.manager.rtu_running,
            "tcp_client_count": self.manager.tcp_client_count,
        }

    def activity_snapshot(self) -> list[dict]:
        out: list[dict] = []
        for mode, reg, running in (
            (CommMode.TCP.value, self.tcp_registry, self.manager.tcp_running),
            (CommMode.RTU.value, self.rtu_registry, self.manager.rtu_running),
        ):
            for slave_id in reg.list_slave_ids():
                out.append(
                    {
                        "mode": mode,
                        "slave_id": slave_id,
                        "state": reg.activity_state(slave_id, any_server_running=running),
                    }
                )
        return out

    def slaves_snapshot(self, mode: str) -> dict:
        reg = self.registry(mode)
        running = self.manager.tcp_running if mode == "tcp" else self.manager.rtu_running
        return {
            "mode": mode,
            "selected_slave_id": reg.selected_slave_id,
            "slaves": [self._slave_dict(reg, sid, running) for sid in reg.list_slave_ids()],
        }

    @staticmethod
    def _slave_dict(reg: SlaveRegistry, sid: int, running: bool) -> dict:
        fault, rate = reg.frame_fault_for(sid)
        return {
            "id": sid,
            "tag": reg.get_tag(sid),
            "word_order": reg.get_word_order(sid).value,
            "frame_fault": fault.value,
            "frame_fault_rate": rate,
            "activity": reg.activity_state(sid, any_server_running=running),
        }

    def points_snapshot(self, mode: str, slave_id: int, kind: RegisterKind | None = None) -> list[dict]:
        slave = self.registry(mode).get_slave(slave_id)
        points = slave.list_points()
        if kind is not None:
            points = [p for p in points if p.kind == kind]
        return [point_to_dict(p, slave.word_order) for p in points]

    def log_lines(self) -> list[str]:
        return list(self.manager.log_buffer)

    def clear_log(self) -> None:
        self.manager.clear_log()
        self._last_log_count = 0

    def full_state(self) -> dict:
        return {
            "type": "state",
            "server": self.server_state(),
            "settings": comm_to_dict(self.comm),
            "identity": self.identity.to_dict(),
            "tcp": self.mode_state("tcp"),
            "rtu": self.mode_state("rtu"),
            "log": {
                "lines": self.log_lines(),
                "total_count": self.manager.total_log_count,
            },
        }

    def mode_state(self, mode: str, *, all_slaves: bool = True) -> dict:
        """1 モード分のスナップショット。

        all_slaves=False のときは選択中スレーブの points のみ含める
        （フロントは選択中しか描画しないので tick では送信量を抑える）。
        """
        reg = self.registry(mode)
        snap = self.slaves_snapshot(mode)
        ids = reg.list_slave_ids() if all_slaves else [reg.selected_slave_id]
        snap["points"] = {str(sid): self.points_snapshot(mode, sid) for sid in ids}
        return snap

    def log_payload(self) -> dict:
        return {"lines": self.log_lines(), "total_count": self.manager.total_log_count}

    def build_tick(self, *, points_tcp: bool, points_rtu: bool) -> dict:
        """WebSocket の tick メッセージを組み立てる（差分のみ）。"""
        dirty = self.take_dirty()
        msg: dict = {"type": "tick", "activity": self.activity_snapshot()}
        if "server_state" in dirty:
            msg["server"] = self.server_state()
        if points_tcp:
            msg["tcp_points"] = self.mode_state("tcp", all_slaves=False)
        if points_rtu:
            msg["rtu_points"] = self.mode_state("rtu", all_slaves=False)
        if "log" in dirty or self.manager.total_log_count != self._last_log_count:
            self._last_log_count = self.manager.total_log_count
            msg["log"] = self.log_payload()
        return msg
