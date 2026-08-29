"""ワード/バイト順（ABCD / CDAB / BADC / DCBA）のテスト。"""

from __future__ import annotations

import itertools
import struct

import pytest
from fastapi.testclient import TestClient

from modbus_sim.api.server import create_app
from modbus_sim.config import RegisterKind, TcpConfig, ValueKind
from modbus_sim.datastore import SlaveRegistry, rtu_registry, tcp_registry
from modbus_sim.models import RegisterPoint
from modbus_sim.server_manager import ModbusServerManager
from modbus_sim.wordorder import WordOrder, pack_words, unpack_bytes

_PORTS = itertools.count(18700)


@pytest.mark.parametrize("order", list(WordOrder))
@pytest.mark.parametrize(
    ("dt", "fmt", "value"),
    [
        (ValueKind.INT32, ">i", -12345),
        (ValueKind.FLOAT32, ">f", 3.14159),
        (ValueKind.FLOAT64, ">d", -2.718281828),
    ],
)
def test_roundtrip_all_orders(order, dt, fmt, value) -> None:
    span = dt.register_span
    reg = SlaveRegistry()
    slave = reg.get_slave(1)
    slave.word_order = order
    slave.upsert_point(RegisterPoint(address=10, kind=RegisterKind.HOLDING_REGISTER, datatype=dt, raw=value))

    words = slave._memory_words(slave.get_point(10, RegisterKind.HOLDING_REGISTER))
    assert words == pack_words(struct.pack(fmt, value), order)
    # 逆変換で元の正規バイト列へ戻る
    assert struct.unpack(fmt, unpack_bytes(words, order))[0] == pytest.approx(value)


def test_abcd_matches_legacy_layout() -> None:
    reg = SlaveRegistry()
    slave = reg.get_slave(1)  # 既定 ABCD
    slave.upsert_point(
        RegisterPoint(address=0, kind=RegisterKind.HOLDING_REGISTER, datatype=ValueKind.INT32, raw=0x12345678)
    )
    assert slave._memory_words(slave.get_point(0, RegisterKind.HOLDING_REGISTER)) == [0x1234, 0x5678]


def test_cdab_swaps_words() -> None:
    reg = SlaveRegistry()
    slave = reg.get_slave(1)
    slave.set_word_order(WordOrder.CDAB)
    slave.upsert_point(
        RegisterPoint(address=0, kind=RegisterKind.HOLDING_REGISTER, datatype=ValueKind.INT32, raw=0x12345678)
    )
    assert slave._memory_words(slave.get_point(0, RegisterKind.HOLDING_REGISTER)) == [0x5678, 0x1234]


def test_set_word_order_rewrites_existing_points() -> None:
    reg = SlaveRegistry()
    slave = reg.get_slave(1)
    p = RegisterPoint(address=0, kind=RegisterKind.HOLDING_REGISTER, datatype=ValueKind.FLOAT32, raw=1.0)
    slave.upsert_point(p)
    before = list(slave._memory_words(slave.get_point(0, RegisterKind.HOLDING_REGISTER)))
    slave.set_word_order(WordOrder.DCBA)
    after = list(slave._memory_words(slave.get_point(0, RegisterKind.HOLDING_REGISTER)))
    assert before != after
    # raw は不変
    assert slave.get_point(0, RegisterKind.HOLDING_REGISTER).raw == 1.0


class TestWordOrderApi:
    @pytest.fixture
    def client(self, tmp_path):
        for r in (tcp_registry, rtu_registry):
            r.load_from_dict({"slaves": [{"id": 1, "tag": "", "points": []}]})
        with TestClient(create_app(tmp_path / "s.json")) as c:
            yield c

    def test_patch_and_decoded_hex_reflects_order(self, client) -> None:
        client.put(
            "/api/slaves/tcp/1/points",
            json={"address": 0, "kind": "hr", "datatype": "int32", "raw": 0x12345678},
        )
        pts = client.get("/api/slaves/tcp/1/points", params={"kind": "hr"}).json()
        assert pts[0]["decoded_hex"] == "0x12345678"

        snap = client.patch("/api/slaves/tcp/1", json={"word_order": "CDAB"}).json()
        assert snap["slaves"][0]["word_order"] == "CDAB"

        pts = client.get("/api/slaves/tcp/1/points", params={"kind": "hr"}).json()
        assert pts[0]["decoded_hex"] == "0x56781234"  # ワイヤ上の並び
        assert pts[0]["raw"] == 0x12345678  # 値は不変

    def test_decoded_input_respects_order(self, client) -> None:
        client.patch("/api/slaves/tcp/1", json={"word_order": "CDAB"})
        r = client.put(
            "/api/slaves/tcp/1/points",
            json={"address": 0, "kind": "hr", "datatype": "int32", "decoded": "0x56781234"},
        )
        assert r.json()["raw"] == 0x12345678

    def test_unknown_word_order_is_400(self, client) -> None:
        assert client.patch("/api/slaves/tcp/1", json={"word_order": "XXXX"}).status_code == 400

    def test_persisted_and_reloaded(self, client) -> None:
        client.patch("/api/slaves/rtu/1", json={"word_order": "BADC"})
        data = SlaveRegistry()
        data.load_from_dict(rtu_registry.to_dict())
        assert data.get_word_order(1) == WordOrder.BADC


@pytest.mark.asyncio
async def test_tcp_client_sees_reordered_words() -> None:
    from pymodbus.client import AsyncModbusTcpClient

    reg = SlaveRegistry()
    slave = reg.get_slave(1)
    slave.set_word_order(WordOrder.CDAB)
    slave.upsert_point(
        RegisterPoint(address=0, kind=RegisterKind.HOLDING_REGISTER, datatype=ValueKind.INT32, raw=0x12345678)
    )
    mgr = ModbusServerManager(slave_registry=reg)
    port = next(_PORTS)
    await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
    try:
        client = AsyncModbusTcpClient("127.0.0.1", port=port)
        assert await client.connect()
        rr = await client.read_holding_registers(0, count=2, device_id=1)
        assert not rr.isError()
        assert rr.registers == [0x5678, 0x1234]  # CDAB
        client.close()
    finally:
        await mgr.stop_tcp()
