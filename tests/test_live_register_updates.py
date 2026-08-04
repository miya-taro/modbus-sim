"""サーバ起動後に追加したレジスタ/コイルが再起動なしで反映されることの回帰テスト。

以前は各 kind のシミュレータブロックが「起動時点で定義済みのアドレス範囲」だけを
カバーしていたため、起動後に新しいアドレスの点を追加してもクライアントからは
ILLEGAL ADDRESS のままだった。REGISTER_COUNT 全域を 1 ブロックとして渡すことで、
起動中の追加も即座に読み書きできることを確認する。
"""

from __future__ import annotations

from itertools import count

import pytest

from modbus_sim.config import RegisterKind, TcpConfig, ValueKind
from modbus_sim.datastore import SlaveRegistry
from modbus_sim.models import RegisterPoint
from modbus_sim.server_manager import ModbusServerManager

_port = count(17000)


def _next_port() -> int:
    return next(_port)


@pytest.mark.asyncio
async def test_holding_register_added_after_start_is_readable_without_restart() -> None:
    from pymodbus.client import AsyncModbusTcpClient

    reg = SlaveRegistry()
    mgr = ModbusServerManager(slave_registry=reg)
    port = _next_port()
    await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
    try:
        client = AsyncModbusTcpClient("127.0.0.1", port=port)
        assert await client.connect()

        # サーバ起動前は存在しなかったアドレスを、起動中に新規追加する。
        reg.get_slave(1).upsert_point(
            RegisterPoint(
                address=1234,
                kind=RegisterKind.HOLDING_REGISTER,
                datatype=ValueKind.UINT16,
                raw=0xBEEF,
            )
        )

        result = await client.read_holding_registers(1234, count=1, device_id=1)
        assert not result.isError(), result
        assert result.registers == [0xBEEF]

        wr = await client.write_register(1234, 0x1111, device_id=1)
        assert not wr.isError(), wr
        again = await client.read_holding_registers(1234, count=1, device_id=1)
        assert again.registers == [0x1111]

        client.close()
    finally:
        await mgr.stop_tcp()


@pytest.mark.asyncio
async def test_coil_added_after_start_is_readable_without_restart() -> None:
    from pymodbus.client import AsyncModbusTcpClient

    reg = SlaveRegistry()
    mgr = ModbusServerManager(slave_registry=reg)
    port = _next_port()
    await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
    try:
        client = AsyncModbusTcpClient("127.0.0.1", port=port)
        assert await client.connect()

        reg.get_slave(1).upsert_point(
            RegisterPoint(
                address=777,
                kind=RegisterKind.COIL,
                datatype=ValueKind.BOOL,
                raw=1,
            )
        )

        result = await client.read_coils(777, count=1, device_id=1)
        assert not result.isError(), result
        assert result.bits[0] is True

        client.close()
    finally:
        await mgr.stop_tcp()


@pytest.mark.asyncio
async def test_int32_added_after_start_is_readable_without_restart() -> None:
    import struct

    from pymodbus.client import AsyncModbusTcpClient

    reg = SlaveRegistry()
    mgr = ModbusServerManager(slave_registry=reg)
    port = _next_port()
    await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
    try:
        client = AsyncModbusTcpClient("127.0.0.1", port=port)
        assert await client.connect()

        reg.get_slave(1).upsert_point(
            RegisterPoint(
                address=5000,
                kind=RegisterKind.HOLDING_REGISTER,
                datatype=ValueKind.INT32,
                raw=0x12345678,
            )
        )

        result = await client.read_holding_registers(5000, count=2, device_id=1)
        assert not result.isError(), result
        assert struct.unpack(">i", struct.pack(">HH", *result.registers))[0] == 0x12345678

        client.close()
    finally:
        await mgr.stop_tcp()


@pytest.mark.asyncio
async def test_removed_register_reads_back_default_zero_without_restart() -> None:
    from pymodbus.client import AsyncModbusTcpClient

    reg = SlaveRegistry()
    reg.get_slave(1).upsert_point(
        RegisterPoint(address=10, kind=RegisterKind.HOLDING_REGISTER, datatype=ValueKind.UINT16, raw=42)
    )
    mgr = ModbusServerManager(slave_registry=reg)
    port = _next_port()
    await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
    try:
        client = AsyncModbusTcpClient("127.0.0.1", port=port)
        assert await client.connect()

        reg.get_slave(1).remove_point(10, RegisterKind.HOLDING_REGISTER)

        result = await client.read_holding_registers(10, count=1, device_id=1)
        assert not result.isError(), result
        assert result.registers == [0]

        client.close()
    finally:
        await mgr.stop_tcp()
