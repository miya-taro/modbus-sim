"""マスター（クライアント）機能のテスト。"""

from __future__ import annotations

import asyncio
import itertools

import pytest
from fastapi.testclient import TestClient

from modbus_sim.api.server import create_app
from modbus_sim.config import RegisterKind, TcpConfig, ValueKind
from modbus_sim.datastore import (
    SlaveRegistry,
    registers_to_values,
    rtu_registry,
    tcp_registry,
    value_to_registers,
)
from modbus_sim.master import ModbusMaster
from modbus_sim.models import RegisterPoint
from modbus_sim.server_manager import ModbusServerManager
from modbus_sim.wordorder import WordOrder

_PORTS = itertools.count(19300)


@pytest.mark.parametrize("order", list(WordOrder))
def test_registers_values_roundtrip(order) -> None:
    for dt, val in [
        (ValueKind.UINT16, 40000),
        (ValueKind.INT16, -5),
        (ValueKind.INT32, -123456),
        (ValueKind.FLOAT32, 3.5),
        (ValueKind.FLOAT64, -2.71828),
    ]:
        regs = value_to_registers(val, dt, order)
        back = registers_to_values(regs, dt, order)
        assert back[0] == pytest.approx(val)


@pytest.mark.asyncio
async def test_master_read_write_against_own_server() -> None:
    reg = SlaveRegistry()
    reg.get_slave(1).upsert_point(
        RegisterPoint(address=100, kind=RegisterKind.HOLDING_REGISTER, datatype=ValueKind.FLOAT32, raw=1.25)
    )
    mgr = ModbusServerManager(slave_registry=reg)
    port = next(_PORTS)
    await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
    master = ModbusMaster()
    try:
        await master.connect_tcp(TcpConfig(host="127.0.0.1", port=port))
        assert master.connected

        r = await master.request(
            function="read_holding_registers", device_id=1, address=100, count=1,
            datatype=ValueKind.FLOAT32, word_order=WordOrder.ABCD,
        )
        assert r["ok"] and r["values"] == [1.25]

        w = await master.request(
            function="write_registers", device_id=1, address=100,
            datatype=ValueKind.FLOAT32, word_order=WordOrder.ABCD, values=[9.5],
        )
        assert w["ok"]

        r2 = await master.request(
            function="read_holding_registers", device_id=1, address=100, count=1,
            datatype=ValueKind.FLOAT32, word_order=WordOrder.ABCD,
        )
        assert r2["values"] == [9.5]

        # 存在しない device への読み取りは例外応答
        bad = await master.request(
            function="read_holding_registers", device_id=9, address=0, count=1,
        )
        assert bad["ok"] is False
    finally:
        await master.disconnect()
        await mgr.stop_tcp()


@pytest.mark.asyncio
async def test_master_request_without_connection_raises() -> None:
    master = ModbusMaster()
    with pytest.raises(ConnectionError):
        await master.request(function="read_coils", device_id=1, address=0, count=1)


class TestMasterApi:
    @pytest.fixture
    def client(self, tmp_path):
        for r in (tcp_registry, rtu_registry):
            r.load_from_dict({"slaves": [{"id": 1, "tag": "", "points": []}]})
        with TestClient(create_app(tmp_path / "s.json")) as c:
            yield c

    def test_connect_request_disconnect(self, client) -> None:
        port = next(_PORTS)
        client.put("/api/slaves/tcp/1/points", json={"address": 5, "kind": "hr", "datatype": "uint16", "raw": 4660})
        client.put("/api/settings", json={"tcp": {"host": "127.0.0.1", "port": port}})
        assert client.post("/api/server/tcp/start").status_code == 200
        try:
            m = client.post("/api/master/connect", json={"mode": "tcp", "host": "127.0.0.1", "port": port}).json()
            assert m["connected"] is True
            r = client.post(
                "/api/master/request",
                json={"function": "read_holding_registers", "device_id": 1, "address": 5, "count": 1},
            ).json()
            assert r["ok"] and r["values"] == [4660]
            assert client.post("/api/master/disconnect").json()["connected"] is False
        finally:
            client.post("/api/server/tcp/stop")

    def test_request_without_connection_is_400(self, client) -> None:
        r = client.post(
            "/api/master/request",
            json={"function": "read_coils", "device_id": 1, "address": 0, "count": 1},
        )
        assert r.status_code == 400

    def test_connect_failure_is_400(self, client) -> None:
        r = client.post("/api/master/connect", json={"mode": "tcp", "host": "127.0.0.1", "port": 1})
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_poll_start_stop(self, client) -> None:
        port = next(_PORTS)
        client.put("/api/slaves/tcp/1/points", json={"address": 0, "kind": "hr", "datatype": "uint16", "raw": 7})
        client.put("/api/settings", json={"tcp": {"host": "127.0.0.1", "port": port}})
        client.post("/api/server/tcp/start")
        try:
            client.post("/api/master/connect", json={"mode": "tcp", "host": "127.0.0.1", "port": port})
            m = client.post(
                "/api/master/poll",
                json={"function": "read_holding_registers", "address": 0, "count": 1, "interval_ms": 100},
            ).json()
            assert m["polling"] is True
            await asyncio.sleep(0.25)
            assert client.post("/api/master/poll/stop").json()["polling"] is False
        finally:
            client.post("/api/master/disconnect")
            client.post("/api/server/tcp/stop")
