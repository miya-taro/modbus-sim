"""シナリオ実行エンジンのテスト。"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from modbus_sim.api.server import create_app
from modbus_sim.api.state import AppState
from modbus_sim.datastore import rtu_registry, tcp_registry
from modbus_sim.scenario import run_scenario

_PORTS = itertools.count(19500)


@pytest.fixture
def state(tmp_path) -> AppState:
    for r in (tcp_registry, rtu_registry):
        r.load_from_dict({"slaves": [{"id": 1, "tag": "", "points": []}]})
    return AppState(tmp_path / "s.json")


@pytest.mark.asyncio
async def test_scenario_read_write_expect(state) -> None:
    port = next(_PORTS)
    scenario = {
        "name": "rw",
        "steps": [
            {"type": "set_point", "mode": "tcp", "kind": "hr", "address": 0, "datatype": "int32", "raw": -7},
            {"type": "start_server", "mode": "tcp", "host": "127.0.0.1", "port": port},
            {"type": "master_connect", "mode": "tcp", "host": "127.0.0.1", "port": port},
            {"type": "master_request", "function": "read_holding_registers", "address": 0,
             "count": 1, "datatype": "int32", "expect": {"ok": True, "values": [-7]}},
            {"type": "master_request", "function": "write_registers", "address": 0,
             "datatype": "int32", "values": [123456], "expect": {"ok": True}},
            {"type": "master_request", "function": "read_holding_registers", "address": 0,
             "count": 1, "datatype": "int32", "expect": {"values": [123456]}},
            {"type": "master_disconnect"},
            {"type": "stop_server", "mode": "tcp"},
        ],
    }
    result = await run_scenario(state, scenario)
    assert result["ok"] is True
    assert result["summary"] == {"total": 8, "passed": 8, "failed": 0}


@pytest.mark.asyncio
async def test_scenario_expect_mismatch_marks_step_failed(state) -> None:
    port = next(_PORTS)
    result = await run_scenario(
        state,
        {
            "steps": [
                {"type": "set_point", "mode": "tcp", "kind": "hr", "address": 0, "raw": 10},
                {"type": "start_server", "mode": "tcp", "host": "127.0.0.1", "port": port},
                {"type": "master_connect", "mode": "tcp", "host": "127.0.0.1", "port": port},
                {"type": "master_request", "function": "read_holding_registers", "address": 0,
                 "count": 1, "expect": {"values": [999]}},
                {"type": "master_disconnect"},
                {"type": "stop_server", "mode": "tcp"},
            ]
        },
    )
    assert result["ok"] is False
    failed = [s for s in result["steps"] if not s["ok"]]
    assert len(failed) == 1 and failed[0]["type"] == "master_request"
    assert "MISMATCH" in failed[0]["detail"]


@pytest.mark.asyncio
async def test_scenario_frame_fault_expect_error(state) -> None:
    port = next(_PORTS)
    result = await run_scenario(
        state,
        {
            "steps": [
                {"type": "set_point", "mode": "tcp", "kind": "hr", "address": 0, "raw": 1},
                {"type": "start_server", "mode": "tcp", "host": "127.0.0.1", "port": port},
                {"type": "set_frame_fault", "mode": "tcp", "slave_id": 1, "fault": "drop", "rate": 1.0},
                {"type": "master_connect", "mode": "tcp", "host": "127.0.0.1", "port": port},
                {"type": "master_request", "function": "read_holding_registers", "address": 0,
                 "count": 1, "expect": {"ok": False}},
                {"type": "master_disconnect"},
                {"type": "stop_server", "mode": "tcp"},
            ]
        },
    )
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_scenario_unknown_step_type(state) -> None:
    result = await run_scenario(state, {"steps": [{"type": "frobnicate"}]})
    assert result["ok"] is False
    assert "未知のステップ" in result["steps"][0]["detail"]


@pytest.mark.asyncio
async def test_scenario_stop_on_failure(state) -> None:
    result = await run_scenario(
        state,
        {
            "stop_on_failure": True,
            "steps": [
                {"type": "frobnicate"},
                {"type": "log", "message": "should not run"},
            ],
        },
    )
    assert len(result["steps"]) == 1


def test_scenario_api_route(tmp_path) -> None:
    for r in (tcp_registry, rtu_registry):
        r.load_from_dict({"slaves": [{"id": 1, "tag": "", "points": []}]})
    port = next(_PORTS)
    with TestClient(create_app(tmp_path / "s.json")) as c:
        scenario = {
            "steps": [
                {"type": "set_point", "mode": "tcp", "kind": "hr", "address": 0, "raw": 42},
                {"type": "start_server", "mode": "tcp", "host": "127.0.0.1", "port": port},
                {"type": "master_connect", "mode": "tcp", "host": "127.0.0.1", "port": port},
                {"type": "master_request", "function": "read_holding_registers", "address": 0,
                 "count": 1, "expect": {"values": [42]}},
                {"type": "master_disconnect"},
                {"type": "stop_server", "mode": "tcp"},
            ]
        }
        r = c.post("/api/scenario/run", json=scenario)
        assert r.status_code == 200
        assert r.json()["ok"] is True


def test_example_scenario_file_is_valid_json() -> None:
    p = Path(__file__).resolve().parent.parent / "examples" / "scenario_example.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(data.get("steps"), list) and data["steps"]
