"""異常応答強制 / 応答遅延 / 値の自動変化 のテスト。"""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from modbus_sim.api.server import create_app
from modbus_sim.config import AutoMode, FaultException, FaultMode, RegisterKind, TcpConfig, ValueKind
from modbus_sim.datastore import SlaveDatastore, SlaveRegistry, rtu_registry, tcp_registry
from modbus_sim.models import RegisterPoint
from modbus_sim.server_manager import ModbusServerManager


def _hr(address: int, raw: int = 0, **kwargs) -> RegisterPoint:
    return RegisterPoint(address=address, kind=RegisterKind.HOLDING_REGISTER, raw=raw, **kwargs)


class TestForcedExceptionOverTcp:
    @pytest.mark.asyncio
    async def test_exception_mode_returns_configured_exception_code(self) -> None:
        from pymodbus.client import AsyncModbusTcpClient

        reg = SlaveRegistry()
        reg.get_slave(1).upsert_point(
            _hr(10, raw=1, fault_mode=FaultMode.EXCEPTION, fault_exception=FaultException.DEVICE_BUSY)
        )
        mgr = ModbusServerManager(slave_registry=reg)
        await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=19301))
        try:
            client = AsyncModbusTcpClient("127.0.0.1", port=19301)
            assert await client.connect()
            result = await client.read_holding_registers(10, count=1, device_id=1)
            assert result.isError()
            assert result.exception_code == 6  # DEVICE_BUSY
            client.close()
        finally:
            await mgr.stop_tcp()

    @pytest.mark.asyncio
    async def test_registers_without_fault_are_unaffected(self) -> None:
        from pymodbus.client import AsyncModbusTcpClient

        reg = SlaveRegistry()
        slave = reg.get_slave(1)
        slave.upsert_point(
            _hr(10, raw=1, fault_mode=FaultMode.EXCEPTION, fault_exception=FaultException.DEVICE_BUSY)
        )
        slave.upsert_point(_hr(20, raw=42))
        mgr = ModbusServerManager(slave_registry=reg)
        await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=19302))
        try:
            client = AsyncModbusTcpClient("127.0.0.1", port=19302)
            assert await client.connect()
            result = await client.read_holding_registers(20, count=1, device_id=1)
            assert not result.isError()
            assert result.registers == [42]
            client.close()
        finally:
            await mgr.stop_tcp()


class TestResponseDelayOverTcp:
    @pytest.mark.asyncio
    async def test_fixed_delay_is_applied(self) -> None:
        from pymodbus.client import AsyncModbusTcpClient

        reg = SlaveRegistry()
        reg.get_slave(1).upsert_point(_hr(30, raw=7, delay_min_ms=250, delay_max_ms=250))
        mgr = ModbusServerManager(slave_registry=reg)
        await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=19303))
        try:
            client = AsyncModbusTcpClient("127.0.0.1", port=19303)
            assert await client.connect()
            start = time.monotonic()
            result = await client.read_holding_registers(30, count=1, device_id=1)
            elapsed = time.monotonic() - start
            assert not result.isError()
            assert result.registers == [7]
            assert elapsed >= 0.2
            client.close()
        finally:
            await mgr.stop_tcp()


class TestNoResponseOverTcp:
    @pytest.mark.asyncio
    async def test_no_response_mode_never_answers_within_timeout(self) -> None:
        from pymodbus.client import AsyncModbusTcpClient

        reg = SlaveRegistry()
        reg.get_slave(1).upsert_point(_hr(40, raw=1, fault_mode=FaultMode.NO_RESPONSE))
        mgr = ModbusServerManager(slave_registry=reg)
        await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=19304))
        try:
            client = AsyncModbusTcpClient("127.0.0.1", port=19304)
            assert await client.connect()
            with pytest.raises(Exception):  # noqa: B017
                await asyncio.wait_for(
                    client.read_holding_registers(40, count=1, device_id=1), timeout=0.5
                )
            client.close()
        finally:
            await mgr.stop_tcp()


class TestTickAutoValues:
    def test_increment_wraps_within_range(self) -> None:
        slave = SlaveDatastore(1)
        slave.upsert_point(
            _hr(1, raw=8, auto_mode=AutoMode.INCREMENT, auto_min=0, auto_max=10, auto_step=1, auto_period_sec=1.0)
        )
        seen = []
        for _ in range(4):
            slave.tick_auto_values(1.0)
            seen.append(slave.get_point(1, RegisterKind.HOLDING_REGISTER).raw)
        assert seen == [9, 10, 0, 1]

    def test_increment_does_not_step_before_period_elapses(self) -> None:
        slave = SlaveDatastore(1)
        slave.upsert_point(
            _hr(1, raw=0, auto_mode=AutoMode.INCREMENT, auto_min=0, auto_max=10, auto_step=1, auto_period_sec=2.0)
        )
        changed = slave.tick_auto_values(0.5)
        assert changed is False
        assert slave.get_point(1, RegisterKind.HOLDING_REGISTER).raw == 0

    def test_random_walk_stays_within_bounds(self) -> None:
        slave = SlaveDatastore(1)
        slave.upsert_point(
            _hr(2, raw=50, auto_mode=AutoMode.RANDOM_WALK, auto_min=0, auto_max=100, auto_step=5, auto_period_sec=0.1)
        )
        for _ in range(50):
            slave.tick_auto_values(0.1)
            value = slave.get_point(2, RegisterKind.HOLDING_REGISTER).raw
            assert 0 <= value <= 100

    def test_sine_oscillates_between_min_and_max(self) -> None:
        slave = SlaveDatastore(1)
        slave.upsert_point(
            _hr(3, raw=0, auto_mode=AutoMode.SINE, auto_min=0, auto_max=100, auto_period_sec=4.0)
        )
        values = []
        for _ in range(9):
            slave.tick_auto_values(0.5)
            values.append(slave.get_point(3, RegisterKind.HOLDING_REGISTER).raw)
        assert max(values) == 100
        assert min(values) == 0

    def test_sine_float64_oscillates(self) -> None:
        slave = SlaveDatastore(1)
        slave.upsert_point(
            _hr(4, raw=0.0, datatype=ValueKind.FLOAT64, auto_mode=AutoMode.SINE,
                auto_min=0, auto_max=10, auto_period_sec=4.0)
        )
        values = []
        for _ in range(9):
            slave.tick_auto_values(0.5)
            values.append(slave.get_point(4, RegisterKind.HOLDING_REGISTER).raw)
        assert max(values) > 9
        assert min(values) < 1
        assert any(isinstance(v, float) and v != int(v) for v in values)

    def test_disabled_range_is_a_no_op(self) -> None:
        slave = SlaveDatastore(1)
        slave.upsert_point(_hr(4, raw=5, auto_mode=AutoMode.INCREMENT))
        changed = slave.tick_auto_values(10.0)
        assert changed is False
        assert slave.get_point(4, RegisterKind.HOLDING_REGISTER).raw == 5

    def test_coil_is_not_affected_by_auto_mode(self) -> None:
        slave = SlaveDatastore(1)
        point = RegisterPoint(
            address=5, kind=RegisterKind.COIL, datatype=ValueKind.BOOL, raw=0,
            auto_mode=AutoMode.INCREMENT, auto_min=0, auto_max=1, auto_period_sec=0.1,
        )
        slave.upsert_point(point)
        assert slave.tick_auto_values(1.0) is False

    def test_registry_ticks_every_slave_not_just_the_first(self) -> None:
        reg = SlaveRegistry()
        reg.add_slave(2)
        for sid in (1, 2):
            reg.get_slave(sid).upsert_point(
                _hr(1, raw=0, auto_mode=AutoMode.INCREMENT, auto_min=0, auto_max=10, auto_step=1, auto_period_sec=1.0)
            )
        reg.tick_auto_values(1.0)
        assert reg.get_slave(1).get_point(1, RegisterKind.HOLDING_REGISTER).raw == 1
        assert reg.get_slave(2).get_point(1, RegisterKind.HOLDING_REGISTER).raw == 1


class TestPersistenceRoundTrip:
    def test_advanced_settings_survive_to_dict_load_from_dict(self) -> None:
        reg = SlaveRegistry()
        reg.get_slave(1).upsert_point(
            _hr(6, raw=3, fault_mode=FaultMode.EXCEPTION,
                fault_exception=FaultException.GATEWAY_NO_RESPONSE,
                delay_min_ms=10, delay_max_ms=50, auto_mode=AutoMode.SINE,
                auto_min=1, auto_max=99, auto_step=2.5, auto_period_sec=3.0)
        )
        restored = SlaveRegistry()
        restored.load_from_dict(reg.to_dict())
        point = restored.get_slave(1).get_point(6, RegisterKind.HOLDING_REGISTER)
        assert point is not None
        assert point.fault_mode == FaultMode.EXCEPTION
        assert point.fault_exception == FaultException.GATEWAY_NO_RESPONSE
        assert point.delay_min_ms == 10
        assert point.delay_max_ms == 50
        assert point.auto_mode == AutoMode.SINE
        assert (point.auto_min, point.auto_max, point.auto_step, point.auto_period_sec) == (1, 99, 2.5, 3.0)

    def test_plain_points_do_not_gain_advanced_keys(self) -> None:
        reg = SlaveRegistry()
        reg.get_slave(1).upsert_point(_hr(7, raw=1))
        point_data = reg.to_dict()["slaves"][0]["points"][0]
        assert "fault_mode" not in point_data
        assert "auto_mode" not in point_data


class TestAdvancedViaApi:
    """旧 RegisterAdvancedDialog / グリッド編集の代替（HTTP 経由）。"""

    @pytest.fixture
    def client(self, tmp_path):
        for reg in (tcp_registry, rtu_registry):
            reg.load_from_dict({"slaves": [{"id": 1, "tag": "", "points": []}]})
        with TestClient(create_app(tmp_path / "s.json")) as c:
            yield c

    def test_apply_all_advanced_fields(self, client) -> None:
        r = client.put(
            "/api/slaves/tcp/1/points",
            json={
                "address": 8, "kind": "hr", "datatype": "uint16", "raw": 1,
                "fault_mode": "exception", "fault_exception": "illegal_data_address",
                "delay_min_ms": 5, "delay_max_ms": 15,
                "auto_mode": "increment", "auto_min": 0, "auto_max": 20,
                "auto_step": 2, "auto_period_sec": 1.5,
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["fault_mode"] == "exception"
        assert body["fault_exception"] == "illegal_data_address"
        assert body["delay_max_ms"] == 15
        assert body["auto_mode"] == "increment"

    def test_delay_max_less_than_min_rejected(self, client) -> None:
        r = client.put(
            "/api/slaves/tcp/1/points",
            json={"address": 11, "kind": "hr", "datatype": "uint16", "raw": 1,
                  "delay_min_ms": 100, "delay_max_ms": 10},
        )
        assert r.status_code == 400

    def test_auto_max_not_greater_than_min_rejected(self, client) -> None:
        r = client.put(
            "/api/slaves/tcp/1/points",
            json={"address": 12, "kind": "hr", "datatype": "uint16", "raw": 1,
                  "auto_mode": "increment", "auto_min": 10, "auto_max": 10},
        )
        assert r.status_code == 400

    def test_partial_edit_preserves_advanced_settings(self, client) -> None:
        client.put(
            "/api/slaves/tcp/1/points",
            json={"address": 15, "kind": "hr", "datatype": "uint16", "raw": 1,
                  "fault_mode": "exception", "fault_exception": "device_busy"},
        )
        # tag だけ更新
        r = client.put(
            "/api/slaves/tcp/1/points",
            json={"address": 15, "kind": "hr", "datatype": "uint16", "tag": "hello"},
        )
        body = r.json()
        assert body["tag"] == "hello"
        assert body["fault_mode"] == "exception"
        assert body["fault_exception"] == "device_busy"
