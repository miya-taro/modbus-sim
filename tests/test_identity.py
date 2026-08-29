"""機器識別（FC 43）/ 診断（FC 8）のテスト。"""

from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient

from modbus_sim.api.server import create_app
from modbus_sim.config import RegisterKind, TcpConfig, ValueKind
from modbus_sim.datastore import SlaveRegistry, rtu_registry, tcp_registry
from modbus_sim.identity import DeviceIdentity
from modbus_sim.models import RegisterPoint
from modbus_sim.server_manager import ModbusServerManager

_PORTS = itertools.count(18900)


def test_identity_to_pymodbus_maps_fields() -> None:
    ident = DeviceIdentity(vendor_name="Acme", product_name="PLC", major_minor_revision="1.2")
    pm = ident.to_pymodbus()
    assert pm.VendorName == "Acme"
    assert pm.ProductName == "PLC"
    assert pm.MajorMinorRevision == "1.2"


def test_identity_from_dict_ignores_junk() -> None:
    ident = DeviceIdentity.from_dict({"vendor_name": "X", "bogus": 1, "product_code": 5})
    assert ident.vendor_name == "X"
    assert ident.product_code == DeviceIdentity().product_code  # 非文字列は無視


class TestIdentityApi:
    @pytest.fixture
    def client(self, tmp_path):
        for r in (tcp_registry, rtu_registry):
            r.load_from_dict({"slaves": [{"id": 1, "tag": "", "points": []}]})
        with TestClient(create_app(tmp_path / "s.json")) as c:
            yield c

    def test_get_put_identity(self, client) -> None:
        got = client.get("/api/identity").json()
        assert "vendor_name" in got
        put = client.put("/api/identity", json={"vendor_name": "Acme", "product_name": "PLC"}).json()
        assert put["vendor_name"] == "Acme" and put["product_name"] == "PLC"
        assert client.get("/api/identity").json()["vendor_name"] == "Acme"

    def test_identity_locked_while_running(self, client) -> None:
        client.put("/api/settings", json={"tcp": {"host": "127.0.0.1", "port": next(_PORTS)}})
        assert client.post("/api/server/tcp/start").status_code == 200
        try:
            assert client.put("/api/identity", json={"vendor_name": "x"}).status_code == 409
        finally:
            client.post("/api/server/tcp/stop")

    def test_identity_persisted(self, client) -> None:
        client.put("/api/identity", json={"model_name": "Z9000"})
        assert client.get("/api/state").json()["identity"]["model_name"] == "Z9000"


@pytest.mark.asyncio
async def test_fc43_returns_configured_objects() -> None:
    from pymodbus.client import AsyncModbusTcpClient

    reg = SlaveRegistry()
    reg.get_slave(1).upsert_point(
        RegisterPoint(address=0, kind=RegisterKind.HOLDING_REGISTER, datatype=ValueKind.UINT16, raw=1)
    )
    mgr = ModbusServerManager(slave_registry=reg)
    ident = DeviceIdentity(vendor_name="Acme", product_code="P1", major_minor_revision="2.0").to_pymodbus()
    port = next(_PORTS)
    await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port), ident)
    try:
        c = AsyncModbusTcpClient("127.0.0.1", port=port)
        assert await c.connect()
        r = await c.read_device_information(device_id=1)
        assert not r.isError()
        assert r.information[0] == b"Acme"
        assert r.information[1] == b"P1"
        c.close()
    finally:
        await mgr.stop_tcp()


@pytest.mark.asyncio
async def test_fc8_return_query_data_echoes() -> None:
    from pymodbus.client import AsyncModbusTcpClient
    from pymodbus.pdu.diag_message import ReturnQueryDataRequest

    reg = SlaveRegistry()
    reg.get_slave(1).upsert_point(
        RegisterPoint(address=0, kind=RegisterKind.HOLDING_REGISTER, datatype=ValueKind.UINT16, raw=1)
    )
    mgr = ModbusServerManager(slave_registry=reg)
    port = next(_PORTS)
    await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
    try:
        c = AsyncModbusTcpClient("127.0.0.1", port=port)
        assert await c.connect()
        r = await c.execute(False, ReturnQueryDataRequest(message=b"\x12\x34", dev_id=1))
        assert not r.isError()
        c.close()
    finally:
        await mgr.stop_tcp()
