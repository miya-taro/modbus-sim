"""FastAPI アプリ本体（REST + WebSocket）。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from modbus_sim import registry_ops
from modbus_sim.api.hub import Hub
from modbus_sim.api.state import AppState, kind_from_slug, point_to_dict
from modbus_sim.config import AutoMode, FaultException, FaultMode, ValueKind
from modbus_sim.datastore import (
    parse_decoded_input,
    parse_raw_input,
    validate_address,
    validate_datatype_value,
)
from modbus_sim.error_messages import friendly_server_error
from modbus_sim.models import RegisterPoint
from modbus_sim.network import list_bind_addresses
from modbus_sim.settings_model import (
    apply_dict_to_comm,
    comm_to_dict,
    comm_to_rtu_config,
    comm_to_tcp_config,
)
from modbus_sim.settings_store import SettingsStore


# --- request models -------------------------------------------------------
class SettingsBody(BaseModel):
    tcp: dict[str, Any] | None = None
    rtu: dict[str, Any] | None = None


class SlaveBody(BaseModel):
    id: int


class SlavePatchBody(BaseModel):
    tag: str | None = None
    selected: bool | None = None


class PointBody(BaseModel):
    address: int
    kind: str
    datatype: str
    raw: float | str | None = None
    decoded: str | None = None
    tag: str | None = None
    fault_mode: str | None = None
    fault_exception: str | None = None
    delay_min_ms: int | None = None
    delay_max_ms: int | None = None
    auto_mode: str | None = None
    auto_min: int | None = None
    auto_max: int | None = None
    auto_step: float | None = None
    auto_period_sec: float | None = None


class RangeBody(BaseModel):
    start: int
    count: int
    kind: str
    datatype: str
    raw: float | str = 0
    tag_prefix: str = ""


class ImportTextBody(BaseModel):
    text: str
    active_kind: str = "hr"


class DuplicateBody(BaseModel):
    points: list[dict[str, Any]]


class PathBody(BaseModel):
    path: str


def _apply_point_body(existing: RegisterPoint | None, body: PointBody) -> RegisterPoint:
    try:
        datatype = ValueKind(body.datatype)
    except ValueError:
        raise HTTPException(400, f"未知の datatype: {body.datatype}") from None
    kind = kind_from_slug(body.kind)
    allowed = registry_ops.datatype_choices_for(kind)
    if datatype not in allowed:
        raise HTTPException(
            400,
            f"この Kind では Datatype は {', '.join(k.value for k in allowed)} のみ有効です",
        )

    point = replace(existing) if existing is not None else RegisterPoint(address=body.address, kind=kind)
    point.address = body.address
    point.kind = kind
    point.datatype = datatype
    if body.tag is not None:
        point.tag = body.tag.strip()
    if body.decoded is not None:
        try:
            point.raw = parse_decoded_input(body.decoded, datatype)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    elif body.raw is not None:
        if isinstance(body.raw, str):
            try:
                point.raw = parse_raw_input(body.raw, datatype)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        elif datatype.is_float:
            point.raw = float(body.raw)
        elif float(body.raw).is_integer():
            point.raw = int(body.raw)
        else:
            raise HTTPException(400, f"{datatype.value} には整数を指定してください")

    if body.fault_mode is not None:
        point.fault_mode = FaultMode(body.fault_mode)
    if body.fault_exception is not None:
        point.fault_exception = FaultException(body.fault_exception)
    if body.delay_min_ms is not None:
        point.delay_min_ms = max(0, body.delay_min_ms)
    if body.delay_max_ms is not None:
        point.delay_max_ms = max(0, body.delay_max_ms)
    if body.auto_mode is not None:
        point.auto_mode = AutoMode(body.auto_mode)
    if body.auto_min is not None:
        point.auto_min = body.auto_min
    if body.auto_max is not None:
        point.auto_max = body.auto_max
    if body.auto_step is not None:
        point.auto_step = body.auto_step
    if body.auto_period_sec is not None:
        point.auto_period_sec = body.auto_period_sec
    point.auto_phase = 0.0

    if point.delay_max_ms and point.delay_max_ms < point.delay_min_ms:
        raise HTTPException(400, "応答遅延の最大値は最小値以上にしてください。")
    if point.auto_mode != AutoMode.NONE and point.auto_min >= point.auto_max:
        raise HTTPException(400, "自動変化の上限は下限より大きくしてください。")

    try:
        validate_address(point.address, datatype)
        validate_datatype_value(datatype, point.raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return point


def create_app(settings_path: Path | None = None) -> FastAPI:
    state = AppState(settings_path)
    hub = Hub()

    async def poller() -> None:
        dt = AppState.POLL_INTERVAL_SEC
        while True:
            await asyncio.sleep(dt)
            try:
                auto_tcp = state.tcp_registry.tick_auto_values(dt)
                auto_rtu = state.rtu_registry.tick_auto_values(dt)
                synced = (
                    state.tcp_registry.sync_from_server()
                    | state.rtu_registry.sync_from_server()
                )
                await hub.broadcast(
                    state.build_tick(
                        points_tcp=auto_tcp or synced,
                        points_rtu=auto_rtu or synced,
                    )
                )
            except Exception:  # noqa: BLE001 - poller は落とさない
                log.exception("poller tick failed")

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(poller())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            with contextlib.suppress(Exception):
                await state.manager.stop_all()

    app = FastAPI(title="Modbus Simulator API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.app_state = state
    app.state.hub = hub

    # --- misc -------------------------------------------------------
    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True}

    @app.get("/api/state")
    async def get_state() -> dict:
        return state.full_state()

    @app.get("/api/bind-addresses")
    async def bind_addresses() -> list[str]:
        return list_bind_addresses()

    @app.get("/api/serial-ports")
    async def serial_ports() -> list[str]:
        try:
            from serial.tools import list_ports

            return [p.device for p in list_ports.comports()]
        except Exception:  # noqa: BLE001
            return []

    # --- settings -------------------------------------------------
    @app.get("/api/settings")
    async def get_settings() -> dict:
        return comm_to_dict(state.comm)

    @app.put("/api/settings")
    async def put_settings(body: SettingsBody) -> dict:
        apply_dict_to_comm(state.comm, body.model_dump(exclude_none=True))
        state.schedule_save()
        return comm_to_dict(state.comm)

    @app.post("/api/settings/export")
    async def export_settings(body: PathBody) -> dict:
        try:
            SettingsStore.write_payload(Path(body.path), state.settings_payload())
        except OSError as exc:
            raise HTTPException(400, f"エクスポートに失敗しました: {exc}") from exc
        return {"ok": True}

    @app.post("/api/settings/import")
    async def import_settings(body: PathBody) -> dict:
        if state.manager.any_running:
            raise HTTPException(409, "サーバー停止中のみインポートできます。")
        try:
            data = json.loads(Path(body.path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(400, f"設定を読み込めませんでした: {exc}") from exc
        if not isinstance(data, dict):
            raise HTTPException(400, "設定ファイルの形式が不正です")
        apply_dict_to_comm(state.comm, data)
        if "tcp_slaves" in data or "slaves" in data:
            state.tcp_registry.load_from_dict(
                {
                    "slaves": data.get("tcp_slaves", data.get("slaves", [])),
                    "selected_slave_id": data.get("tcp_selected_slave_id", 1),
                }
            )
        if "rtu_slaves" in data:
            state.rtu_registry.load_from_dict(
                {
                    "slaves": data["rtu_slaves"],
                    "selected_slave_id": data.get("rtu_selected_slave_id", 1),
                }
            )
        state.schedule_save()
        await hub.broadcast(state.full_state())
        return {"ok": True}

    # --- slaves --------------------------------------------------
    @app.get("/api/slaves/{mode}")
    async def list_slaves(mode: str) -> dict:
        _check_mode(mode)
        return state.slaves_snapshot(mode)

    @app.post("/api/slaves/{mode}")
    async def add_slave(mode: str, body: SlaveBody) -> dict:
        reg = _reg(mode)
        try:
            reg.add_slave(body.id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        reg.selected_slave_id = body.id
        state.schedule_save()
        return state.slaves_snapshot(mode)

    @app.delete("/api/slaves/{mode}/{slave_id}")
    async def remove_slave(mode: str, slave_id: int) -> dict:
        reg = _reg(mode)
        try:
            reg.remove_slave(slave_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        state.schedule_save()
        return state.slaves_snapshot(mode)

    @app.patch("/api/slaves/{mode}/{slave_id}")
    async def patch_slave(mode: str, slave_id: int, body: SlavePatchBody) -> dict:
        reg = _reg(mode)
        if slave_id not in reg.list_slave_ids():
            raise HTTPException(404, f"Slave ID {slave_id} not found")
        if body.tag is not None:
            reg.set_tag(slave_id, body.tag)
        if body.selected:
            reg.selected_slave_id = slave_id
        state.schedule_save()
        return state.slaves_snapshot(mode)

    # --- points -------------------------------------------------
    @app.get("/api/slaves/{mode}/{slave_id}/points")
    async def list_points(mode: str, slave_id: int, kind: str | None = Query(None)) -> list[dict]:
        _reg(mode)
        k = kind_from_slug(kind) if kind else None
        try:
            return state.points_snapshot(mode, slave_id, k)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.put("/api/slaves/{mode}/{slave_id}/points")
    async def upsert_point(mode: str, slave_id: int, body: PointBody) -> dict:
        reg = _reg(mode)
        try:
            slave = reg.get_slave(slave_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        kind = kind_from_slug(body.kind)
        existing = slave.get_point(body.address, kind)
        point = _apply_point_body(existing, body)
        clash = registry_ops.find_overlap(
            slave, point.address, kind, point.datatype, ignore_key=(point.address, kind)
        )
        if clash is not None:
            raise HTTPException(
                400,
                f"Addr {point.address} は Addr {clash.address}"
                f"（{clash.datatype.value}, {clash.datatype.register_span}レジスタ）と重複します",
            )
        slave.upsert_point(point)
        state.schedule_save()
        return point_to_dict(point)

    @app.delete("/api/slaves/{mode}/{slave_id}/points/{kind}/{address}")
    async def delete_point(mode: str, slave_id: int, kind: str, address: int) -> dict:
        reg = _reg(mode)
        try:
            slave = reg.get_slave(slave_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        removed = slave.remove_point(address, kind_from_slug(kind))
        if not removed:
            raise HTTPException(404, "対象のレジスタがありません")
        state.schedule_save()
        return {"ok": True}

    @app.post("/api/slaves/{mode}/{slave_id}/points/range")
    async def add_range(mode: str, slave_id: int, body: RangeBody) -> dict:
        reg = _reg(mode)
        try:
            slave = reg.get_slave(slave_id)
            kind = kind_from_slug(body.kind)
            datatype = registry_ops.parse_datatype(body.datatype, kind)
            raw = (
                parse_raw_input(body.raw, datatype)
                if isinstance(body.raw, str)
                else body.raw
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        added, errors = registry_ops.add_register_range(
            slave,
            start=body.start,
            count=body.count,
            kind=kind,
            datatype=datatype,
            raw=raw,
            tag_prefix=body.tag_prefix.strip(),
        )
        state.schedule_save()
        return {"added": added, "errors": errors}

    @app.post("/api/slaves/{mode}/{slave_id}/points/import")
    async def import_points(mode: str, slave_id: int, body: ImportTextBody) -> dict:
        reg = _reg(mode)
        try:
            slave = reg.get_slave(slave_id)
            active_kind = kind_from_slug(body.active_kind)
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        added, errors, first_kind = registry_ops.import_register_map_text(
            slave, body.text, active_kind=active_kind
        )
        state.schedule_save()
        return {
            "added": added,
            "errors": errors,
            "first_kind": first_kind.value if first_kind else None,
        }

    @app.post("/api/slaves/{mode}/{slave_id}/points/duplicate")
    async def duplicate_points_route(mode: str, slave_id: int, body: DuplicateBody) -> dict:
        reg = _reg(mode)
        try:
            slave = reg.get_slave(slave_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        points: list[RegisterPoint] = []
        for entry in body.points:
            p = slave.get_point(int(entry["address"]), kind_from_slug(entry["kind"]))
            if p is not None:
                points.append(p)
        added, skipped = registry_ops.duplicate_points(slave, points)
        state.schedule_save()
        return {"added": added, "skipped": skipped}

    # --- server lifecycle -------------------------------------
    @app.post("/api/server/{mode}/start")
    async def start_server(mode: str) -> dict:
        _check_mode(mode)
        try:
            if mode == "tcp":
                await state.manager.start_tcp(comm_to_tcp_config(state.comm))
            else:
                await state.manager.start_rtu(comm_to_rtu_config(state.comm))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, friendly_server_error(exc)) from exc
        return state.server_state()

    @app.post("/api/server/{mode}/stop")
    async def stop_server(mode: str) -> dict:
        _check_mode(mode)
        if mode == "tcp":
            await state.manager.stop_tcp()
        else:
            await state.manager.stop_rtu()
        return state.server_state()

    @app.post("/api/log/clear")
    async def clear_log() -> dict:
        state.clear_log()
        await hub.broadcast({"type": "tick", "log": state.log_payload()})
        return {"ok": True}

    # --- websocket -------------------------------------------
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await hub.connect(ws)
        try:
            await ws.send_json(state.full_state())
            while True:
                await ws.receive_text()  # クライアントからの受信は無視（ping 相当）
        except WebSocketDisconnect:
            pass
        finally:
            await hub.disconnect(ws)

    # --- helpers --------------------------------------------
    def _check_mode(mode: str) -> None:
        if mode not in ("tcp", "rtu"):
            raise HTTPException(404, f"未知の mode: {mode}")

    def _reg(mode: str):
        _check_mode(mode)
        return state.registry(mode)

    @app.exception_handler(ValueError)
    async def _value_error_handler(_req, exc: ValueError):  # noqa: ANN001
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return app
