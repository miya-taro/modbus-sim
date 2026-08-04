"""Tests for register datatypes and Modbus read/write."""

from __future__ import annotations

import asyncio
import struct

import pytest

from modbus_sim.config import RegisterKind, TcpConfig, ValueKind
from modbus_sim.datastore import (
    SlaveDatastore,
    SlaveRegistry,
    decode_value,
    format_decoded_display,
    parse_decoded_input,
)
from modbus_sim.models import RegisterPoint
from modbus_sim.server_manager import ModbusServerManager


def _hr_point(address: int, datatype: ValueKind, raw: int) -> RegisterPoint:
    return RegisterPoint(
        address=address,
        kind=RegisterKind.HOLDING_REGISTER,
        datatype=datatype,
        raw=raw,
    )


class TestUint16:
    def test_write_read_memory(self) -> None:
        slave = SlaveDatastore(1)
        point = _hr_point(10, ValueKind.UINT16, 4660)
        slave.upsert_point(point)
        assert slave.read_raw(RegisterKind.HOLDING_REGISTER, 10) == 4660

    def test_decode_display(self) -> None:
        point = _hr_point(0, ValueKind.UINT16, 4660)
        assert decode_value(point) == 4660
        assert format_decoded_display(point) == "0x1234"
        assert parse_decoded_input("0x1234", ValueKind.UINT16) == 4660
        assert parse_decoded_input("1234", ValueKind.UINT16) == 4660
        assert parse_decoded_input("1234h", ValueKind.UINT16) == 4660


class TestInt16:
    def test_negative_value(self) -> None:
        slave = SlaveDatastore(1)
        point = _hr_point(5, ValueKind.INT16, -1)
        slave.upsert_point(point)
        assert slave.read_raw(RegisterKind.HOLDING_REGISTER, 5) == 0xFFFF

    def test_decode_negative(self) -> None:
        point = _hr_point(0, ValueKind.INT16, 0xFFFF)
        assert decode_value(point) == -1
        assert parse_decoded_input("0xFFFF", ValueKind.INT16) == 0xFFFF

    def test_sync_from_server_does_not_false_positive_on_int16(self) -> None:
        """int16 の -1 とメモリ 0xFFFF を別物と見ると UI が定期的に再描画されて遅くなる。"""
        slave = SlaveDatastore(1)
        point = _hr_point(5, ValueKind.INT16, -1)
        slave.upsert_point(point)
        assert slave.sync_from_server() is False
        assert point.raw == -1

        point.raw = 0xFFFF
        assert slave.sync_from_server() is False


class TestInt32:
    def test_two_register_storage(self) -> None:
        slave = SlaveDatastore(1)
        point = _hr_point(100, ValueKind.INT32, 0x12345678)
        slave.upsert_point(point)
        assert slave.read_raw(RegisterKind.HOLDING_REGISTER, 100) == 0x1234
        assert slave.read_raw(RegisterKind.HOLDING_REGISTER, 101) == 0x5678

    def test_sync_from_server_reconstructs_int32(self) -> None:
        slave = SlaveDatastore(1)
        point = _hr_point(100, ValueKind.INT32, 0)
        slave.upsert_point(point)
        slave._holding_registers[100] = 0x1234
        slave._holding_registers[101] = 0x5678
        assert slave.sync_from_server() is True
        assert point.raw == 0x12345678

    def test_decode_and_display(self) -> None:
        point = _hr_point(0, ValueKind.INT32, 0x12345678)
        assert decode_value(point) == 0x12345678
        assert format_decoded_display(point) == "0x12345678"
        assert parse_decoded_input("0x12345678", ValueKind.INT32) == 0x12345678

    def test_negative_hex_roundtrip(self) -> None:
        point = _hr_point(0, ValueKind.INT32, -1)
        assert format_decoded_display(point) == "0xFFFFFFFF"
        assert parse_decoded_input("0xFFFFFFFF", ValueKind.INT32) == -1
        assert parse_decoded_input("FFFFFFFF", ValueKind.INT32) == -1


class TestCoil:
    def test_bool_storage(self) -> None:
        slave = SlaveDatastore(1)
        point = RegisterPoint(
            address=3,
            kind=RegisterKind.COIL,
            datatype=ValueKind.BOOL,
            raw=1,
        )
        slave.upsert_point(point)
        assert slave.read_raw(RegisterKind.COIL, 3) is True
        assert decode_value(point) is True
        assert format_decoded_display(point) == "0x01"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("address", [0, 15, 16, 20, 100, 1000])
    async def test_tcp_coil_read_reflects_initial_value_at_any_address(
        self, address: int
    ) -> None:
        """先頭 Coil のアドレスが 16 以上でも、サーバ起動直後の値が正しく反映されること。

        コイル用の内部レジスタブロックはアドレスに応じたオフセットを持つため、
        そのオフセットを無視すると先頭 Coil が addr>=16 の場合に値が化けていた。
        """
        from pymodbus.client import AsyncModbusTcpClient

        reg = SlaveRegistry()
        reg.get_slave(1).upsert_point(
            RegisterPoint(address=address, kind=RegisterKind.COIL, datatype=ValueKind.BOOL, raw=1)
        )
        mgr = ModbusServerManager(slave_registry=reg)
        port = 15100 + address % 1000
        await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
        try:
            client = AsyncModbusTcpClient("127.0.0.1", port=port)
            assert await client.connect()
            result = await client.read_coils(address, count=1, device_id=1)
            assert not result.isError(), result
            assert result.bits[0] is True
            client.close()
        finally:
            await mgr.stop_tcp()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("address", [0, 16, 20, 100, 1000])
    async def test_tcp_coil_write_persists_at_any_address(self, address: int) -> None:
        """先頭 Coil のアドレスが 16 以上でも write_coil の結果が読み戻せること。"""
        from pymodbus.client import AsyncModbusTcpClient

        reg = SlaveRegistry()
        reg.get_slave(1).upsert_point(
            RegisterPoint(address=address, kind=RegisterKind.COIL, datatype=ValueKind.BOOL, raw=0)
        )
        mgr = ModbusServerManager(slave_registry=reg)
        port = 15200 + address % 1000
        await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
        try:
            client = AsyncModbusTcpClient("127.0.0.1", port=port)
            assert await client.connect()
            wr = await client.write_coil(address, True, device_id=1)
            assert not wr.isError(), wr
            result = await client.read_coils(address, count=1, device_id=1)
            assert not result.isError(), result
            assert result.bits[0] is True
            client.close()
        finally:
            await mgr.stop_tcp()


@pytest.mark.asyncio
async def test_tcp_read_uint16() -> None:
    reg = SlaveRegistry()
    slave = reg.get_slave(1)
    slave.upsert_point(_hr_point(0, ValueKind.UINT16, 1234))

    mgr = ModbusServerManager(slave_registry=reg)
    port = 15021
    await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
    try:
        from pymodbus.client import AsyncModbusTcpClient

        client = AsyncModbusTcpClient("127.0.0.1", port=port)
        await client.connect()
        result = await client.read_holding_registers(0, count=1, device_id=1)
        assert not result.isError()
        assert result.registers == [1234]
        client.close()
    finally:
        await mgr.stop_tcp()


@pytest.mark.asyncio
async def test_tcp_read_int16_negative() -> None:
    reg = SlaveRegistry()
    slave = reg.get_slave(1)
    slave.upsert_point(_hr_point(1, ValueKind.INT16, -42))

    mgr = ModbusServerManager(slave_registry=reg)
    port = 15022
    await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
    try:
        from pymodbus.client import AsyncModbusTcpClient

        client = AsyncModbusTcpClient("127.0.0.1", port=port)
        await client.connect()
        result = await client.read_holding_registers(1, count=1, device_id=1)
        assert not result.isError()
        assert result.registers[0] == struct.unpack(">H", struct.pack(">h", -42))[0]
        client.close()
    finally:
        await mgr.stop_tcp()


@pytest.mark.asyncio
async def test_tcp_read_int32() -> None:
    reg = SlaveRegistry()
    slave = reg.get_slave(1)
    slave.upsert_point(_hr_point(10, ValueKind.INT32, 0x00FF00FF))

    mgr = ModbusServerManager(slave_registry=reg)
    port = 15023
    await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
    try:
        from pymodbus.client import AsyncModbusTcpClient

        client = AsyncModbusTcpClient("127.0.0.1", port=port)
        await client.connect()
        result = await client.read_holding_registers(10, count=2, device_id=1)
        assert not result.isError()
        assert result.registers == [0x00FF, 0x00FF]
        combined = struct.unpack(">i", struct.pack(">HH", *result.registers))[0]
        assert combined == 0x00FF00FF
        client.close()
    finally:
        await mgr.stop_tcp()


@pytest.mark.asyncio
async def test_tcp_read_high_address_sparse() -> None:
    reg = SlaveRegistry()
    slave = reg.get_slave(1)
    slave.upsert_point(_hr_point(60000, ValueKind.UINT16, 42))

    mgr = ModbusServerManager(slave_registry=reg)
    port = 15026
    await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
    try:
        from pymodbus.client import AsyncModbusTcpClient

        client = AsyncModbusTcpClient("127.0.0.1", port=port)
        await client.connect()
        result = await client.read_holding_registers(60000, count=1, device_id=1)
        assert not result.isError()
        assert result.registers == [42]
        client.close()
    finally:
        await mgr.stop_tcp()


@pytest.mark.asyncio
async def test_tcp_start_is_fast() -> None:
    reg = SlaveRegistry()
    reg.get_slave(1).upsert_point(_hr_point(0, ValueKind.UINT16, 1))
    mgr = ModbusServerManager(slave_registry=reg)
    port = 15024

    async def _run() -> None:
        await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
        await mgr.stop_tcp()

    await asyncio.wait_for(_run(), timeout=5)


@pytest.mark.asyncio
async def test_tcp_ipv6_loopback() -> None:
    reg = SlaveRegistry()
    reg.get_slave(1).upsert_point(_hr_point(0, ValueKind.UINT16, 999))
    mgr = ModbusServerManager(slave_registry=reg)
    port = 15025
    await mgr.start_tcp(TcpConfig(host="::1", port=port))
    try:
        from pymodbus.client import AsyncModbusTcpClient

        client = AsyncModbusTcpClient("::1", port=port)
        await client.connect()
        result = await client.read_holding_registers(0, count=1, device_id=1)
        assert not result.isError()
        assert result.registers == [999]
        client.close()
    finally:
        await mgr.stop_tcp()


def test_build_sim_devices_returns_independent_instances() -> None:
    """同一レジストリでも起動ごとに別 SimDevice を返すこと。"""
    reg = SlaveRegistry()
    reg.get_slave(1).upsert_point(_hr_point(0, ValueKind.UINT16, 1))
    first = reg.build_sim_devices()
    second = reg.build_sim_devices()
    assert first is not second
    assert first[0] is not second[0]
    assert first[0].id == second[0].id


@pytest.mark.asyncio
async def test_tcp_and_rtu_use_separate_registries() -> None:
    """TCP と RTU で別レジストリを渡すと、値が混ざらないこと。"""
    tcp_reg = SlaveRegistry()
    rtu_reg = SlaveRegistry()
    tcp_reg.get_slave(1).upsert_point(_hr_point(0, ValueKind.UINT16, 111))
    rtu_reg.get_slave(1).upsert_point(_hr_point(0, ValueKind.UINT16, 222))

    mgr = ModbusServerManager(tcp_registry=tcp_reg, rtu_registry=rtu_reg)
    port = 15027
    await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
    try:
        from pymodbus.client import AsyncModbusTcpClient

        client = AsyncModbusTcpClient("127.0.0.1", port=port)
        await client.connect()
        result = await client.read_holding_registers(0, count=1, device_id=1)
        assert not result.isError()
        assert result.registers == [111]
        client.close()
    finally:
        await mgr.stop_tcp()

    assert rtu_reg.get_slave(1).read_raw(RegisterKind.HOLDING_REGISTER, 0) == 222
