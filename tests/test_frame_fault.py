"""パケットレベル異常注入（CRC破壊 / 切断 / 破棄）のテスト。"""

from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient

from modbus_sim.api.server import create_app
from modbus_sim.config import CommMode, FrameFault, RegisterKind, TcpConfig, ValueKind
from modbus_sim.datastore import SlaveRegistry, rtu_registry, tcp_registry
from modbus_sim.models import RegisterPoint
from modbus_sim.packet_log import corrupt_frame
from modbus_sim.server_manager import ModbusServerManager

_PORTS = itertools.count(19100)


class TestCorruptFrame:
    def test_drop_returns_empty(self) -> None:
        assert corrupt_frame(CommMode.RTU, b"\x01\x03\x02\x00\x2a\xf8\x53", FrameFault.DROP) == b""

    def test_truncate_shortens(self) -> None:
        pkt = bytes(range(20))
        out = corrupt_frame(CommMode.TCP, pkt, FrameFault.TRUNCATE)
        assert 17 <= len(out) < 20

    def test_bad_crc_rtu_flips_last_byte(self) -> None:
        pkt = b"\x01\x03\x02\x00\x2a\xf8\x53"
        out = corrupt_frame(CommMode.RTU, pkt, FrameFault.BAD_CRC)
        assert out[:-1] == pkt[:-1] and out[-1] != pkt[-1]

    def test_bad_crc_tcp_corrupts_length(self) -> None:
        pkt = b"\x00\x01\x00\x00\x00\x05\x01\x03\x02\x00\x2a"
        out = corrupt_frame(CommMode.TCP, pkt, FrameFault.BAD_CRC)
        assert out[4:6] != pkt[4:6]
        assert out[:4] == pkt[:4] and out[6:] == pkt[6:]

    def test_none_is_passthrough(self) -> None:
        pkt = b"\x01\x02\x03"
        assert corrupt_frame(CommMode.RTU, pkt, FrameFault.NONE) == pkt


class TestFrameFaultApi:
    @pytest.fixture
    def client(self, tmp_path):
        for r in (tcp_registry, rtu_registry):
            r.load_from_dict({"slaves": [{"id": 1, "tag": "", "points": []}]})
        with TestClient(create_app(tmp_path / "s.json")) as c:
            yield c

    def test_patch_and_snapshot(self, client) -> None:
        snap = client.patch(
            "/api/slaves/tcp/1", json={"frame_fault": "truncate", "frame_fault_rate": 0.5}
        ).json()
        s = snap["slaves"][0]
        assert s["frame_fault"] == "truncate"
        assert s["frame_fault_rate"] == 0.5

    def test_rate_clamped(self, client) -> None:
        snap = client.patch("/api/slaves/tcp/1", json={"frame_fault": "drop", "frame_fault_rate": 5}).json()
        assert snap["slaves"][0]["frame_fault_rate"] == 1.0

    def test_unknown_fault_is_400(self, client) -> None:
        assert client.patch("/api/slaves/tcp/1", json={"frame_fault": "boom"}).status_code == 400

    def test_persisted(self, client) -> None:
        client.patch("/api/slaves/rtu/1", json={"frame_fault": "bad_crc", "frame_fault_rate": 0.3})
        reg = SlaveRegistry()
        reg.load_from_dict(rtu_registry.to_dict())
        f, r = reg.frame_fault_for(1)
        assert f == FrameFault.BAD_CRC and r == pytest.approx(0.3)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [FrameFault.DROP, FrameFault.TRUNCATE, FrameFault.BAD_CRC])
async def test_tcp_client_errors_under_frame_fault(fault) -> None:
    import asyncio

    from pymodbus.client import AsyncModbusTcpClient

    reg = SlaveRegistry()
    reg.get_slave(1).upsert_point(
        RegisterPoint(address=0, kind=RegisterKind.HOLDING_REGISTER, datatype=ValueKind.UINT16, raw=42)
    )
    reg.set_frame_fault(1, fault, 1.0)
    mgr = ModbusServerManager(slave_registry=reg)
    port = next(_PORTS)
    await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
    try:
        c = AsyncModbusTcpClient("127.0.0.1", port=port, timeout=1)
        assert await c.connect()
        with pytest.raises(Exception):  # noqa: B017
            await asyncio.wait_for(c.read_holding_registers(0, count=1, device_id=1), timeout=2)
        # rate 0 に戻すと正常
        reg.set_frame_fault(1, fault, 0.0)
        r = await asyncio.wait_for(c.read_holding_registers(0, count=1, device_id=1), timeout=2)
        assert not r.isError() and r.registers == [42]
        c.close()
    finally:
        await mgr.stop_tcp()
