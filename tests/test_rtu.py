"""RTU (シリアル) 経路のテスト。pymodbus nullmodem を使う。"""

from __future__ import annotations

import asyncio

import pytest
from pymodbus.client import AsyncModbusSerialClient
from pymodbus.transport import NULLMODEM_HOST

from modbus_sim.config import Parity, RegisterKind, RtuConfig, TcpConfig, ValueKind
from modbus_sim.datastore import SlaveRegistry
from modbus_sim.models import RegisterPoint
from modbus_sim.server_manager import ModbusServerManager


def _hr(address: int, raw: int) -> RegisterPoint:
    return RegisterPoint(
        address=address,
        kind=RegisterKind.HOLDING_REGISTER,
        datatype=ValueKind.UINT16,
        raw=raw,
    )


def _nullmodem_port(channel: int = 21) -> str:
    return f"{NULLMODEM_HOST}:{channel}"


@pytest.mark.asyncio
async def test_rtu_read_write_over_nullmodem() -> None:
    reg = SlaveRegistry()
    reg.get_slave(1).upsert_point(_hr(0, 42))
    mgr = ModbusServerManager(slave_registry=reg)
    serial_port = _nullmodem_port(21)
    config = RtuConfig(
        port=serial_port,
        baudrate=9600,
        parity=Parity.EVEN,
        bytesize=8,
        stopbits=1,
    )
    await mgr.start_rtu(config)
    client = None
    try:
        client = AsyncModbusSerialClient(
            port=serial_port,
            baudrate=9600,
            parity="E",
            bytesize=8,
            stopbits=1,
        )
        assert await client.connect()
        await asyncio.sleep(0.05)
        result = await client.read_holding_registers(0, count=1, device_id=1)
        assert not result.isError(), result
        assert result.registers == [42]

        wr = await client.write_register(0, 99, device_id=1)
        assert not wr.isError(), wr
        again = await client.read_holding_registers(0, count=1, device_id=1)
        assert not again.isError()
        assert again.registers == [99]

        lines = list(mgr.log_buffer)
        assert any("RTU" in line and "RX" in line for line in lines)
        assert any("RTU" in line and "TX" in line for line in lines)
    finally:
        if client is not None:
            client.close()
        await mgr.stop_rtu()


@pytest.mark.asyncio
@pytest.mark.parametrize(("address", "channel"), [(1, 23), (256, 24), (0x1234, 25)])
async def test_rtu_read_nonzero_address_over_nullmodem(address: int, channel: int) -> None:
    """アドレスの上位/下位バイトが非ゼロでも RTU 通信できること。

    RTU フレームの addr フィールドを TCP の MBAP protocol_id と誤認すると、
    正常なフレームが INVALID 扱いで握りつぶされていた（回帰防止）。
    """
    reg = SlaveRegistry()
    reg.get_slave(1).upsert_point(_hr(address, 42))
    mgr = ModbusServerManager(slave_registry=reg)
    serial_port = _nullmodem_port(channel)
    config = RtuConfig(port=serial_port, baudrate=9600, parity=Parity.EVEN, bytesize=8, stopbits=1)
    await mgr.start_rtu(config)
    client = None
    try:
        client = AsyncModbusSerialClient(
            port=serial_port, baudrate=9600, parity="E", bytesize=8, stopbits=1
        )
        assert await client.connect()
        await asyncio.sleep(0.05)
        result = await client.read_holding_registers(address, count=1, device_id=1)
        assert not result.isError(), result
        assert result.registers == [42]
        assert not any("INVALID" in line for line in mgr.log_buffer)
    finally:
        if client is not None:
            client.close()
        await mgr.stop_rtu()


@pytest.mark.asyncio
async def test_tcp_and_rtu_independent_via_nullmodem() -> None:
    from pymodbus.client import AsyncModbusTcpClient

    tcp_reg = SlaveRegistry()
    rtu_reg = SlaveRegistry()
    tcp_reg.get_slave(1).upsert_point(_hr(0, 111))
    rtu_reg.get_slave(1).upsert_point(_hr(0, 222))

    mgr = ModbusServerManager(tcp_registry=tcp_reg, rtu_registry=rtu_reg)
    tcp_port = 17201
    serial_port = _nullmodem_port(22)
    await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=tcp_port))
    await mgr.start_rtu(
        RtuConfig(port=serial_port, baudrate=9600, parity=Parity.EVEN, bytesize=8, stopbits=1)
    )
    serial_client = None
    try:
        tcp_client = AsyncModbusTcpClient("127.0.0.1", port=tcp_port)
        assert await tcp_client.connect()
        tr = await tcp_client.read_holding_registers(0, count=1, device_id=1)
        assert not tr.isError()
        assert tr.registers == [111]
        tcp_client.close()

        serial_client = AsyncModbusSerialClient(
            port=serial_port, baudrate=9600, parity="E", bytesize=8, stopbits=1
        )
        assert await serial_client.connect()
        await asyncio.sleep(0.05)
        rr = await serial_client.read_holding_registers(0, count=1, device_id=1)
        assert not rr.isError(), rr
        assert rr.registers == [222]
    finally:
        if serial_client is not None:
            serial_client.close()
        await mgr.stop_all()
