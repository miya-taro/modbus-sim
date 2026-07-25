"""厳密な境界・型・ポート検証。"""

from __future__ import annotations

import struct
from itertools import count

import pytest
from PySide6.QtWidgets import QApplication

from modbus_sim.config import REGISTER_COUNT, RegisterKind, TcpConfig, ValueKind
from modbus_sim.datastore import (
    SlaveDatastore,
    SlaveRegistry,
    decode_value,
    format_decoded_display,
    parse_decoded_input,
    validate_address,
)
from modbus_sim.models import RegisterPoint
from modbus_sim.server_manager import ModbusServerManager
from modbus_sim.ui.settings_panel import SettingsPanel

_port = count(16000)


def _next_port() -> int:
    return next(_port)


def _hr(address: int, datatype: ValueKind, raw: int) -> RegisterPoint:
    return RegisterPoint(
        address=address,
        kind=RegisterKind.HOLDING_REGISTER,
        datatype=datatype,
        raw=raw,
    )


# ---------------------------------------------------------------------------
# アドレス登録可否
# ---------------------------------------------------------------------------


class TestAddressRegistration:
    @pytest.mark.parametrize("address", [0, 1, 32767, 65534, 65535])
    def test_uint16_accepts_full_range(self, address: int) -> None:
        validate_address(address, ValueKind.UINT16)
        slave = SlaveDatastore(1)
        slave.upsert_point(_hr(address, ValueKind.UINT16, 7))
        assert slave.read_raw(RegisterKind.HOLDING_REGISTER, address) == 7

    @pytest.mark.parametrize("address", [-1, REGISTER_COUNT, REGISTER_COUNT + 1])
    def test_rejects_out_of_range(self, address: int) -> None:
        with pytest.raises(ValueError, match="Addr"):
            validate_address(address, ValueKind.UINT16)

    @pytest.mark.parametrize("address", [0, 1, 65534])
    def test_int32_accepts_up_to_65534(self, address: int) -> None:
        validate_address(address, ValueKind.INT32)
        slave = SlaveDatastore(1)
        slave.upsert_point(_hr(address, ValueKind.INT32, -2))
        assert slave.read_raw(RegisterKind.HOLDING_REGISTER, address) == 0xFFFF
        assert slave.read_raw(RegisterKind.HOLDING_REGISTER, address + 1) == 0xFFFE

    def test_int32_rejects_65535(self) -> None:
        with pytest.raises(ValueError, match="int32"):
            validate_address(65535, ValueKind.INT32)

    def test_int32_at_65534_registers_pair(self) -> None:
        slave = SlaveDatastore(1)
        slave.upsert_point(_hr(65534, ValueKind.INT32, 0x11223344))
        assert slave.read_raw(RegisterKind.HOLDING_REGISTER, 65534) == 0x1122
        assert slave.read_raw(RegisterKind.HOLDING_REGISTER, 65535) == 0x3344


# ---------------------------------------------------------------------------
# 全データ型 + 負数の 16 進往復
# ---------------------------------------------------------------------------


class TestDatatypeHexRoundtrip:
    """Raw ↔ Decoded(0xあり/なし) ↔ decode_value が型ごとに破綻しないこと。"""

    @pytest.mark.parametrize(
        ("raw", "hex_with_prefix", "hex_bare"),
        [
            (0, "0x0000", "0"),
            (1, "0x0001", "1"),
            (4660, "0x1234", "1234"),
            (65535, "0xFFFF", "FFFF"),
        ],
    )
    def test_uint16_hex_forms(
        self, raw: int, hex_with_prefix: str, hex_bare: str
    ) -> None:
        point = _hr(0, ValueKind.UINT16, raw)
        assert format_decoded_display(point) == hex_with_prefix
        assert parse_decoded_input(hex_with_prefix, ValueKind.UINT16) == raw
        assert parse_decoded_input(hex_bare, ValueKind.UINT16) == raw
        assert parse_decoded_input(hex_with_prefix.lower(), ValueKind.UINT16) == raw
        assert decode_value(point) == raw

    @pytest.mark.parametrize(
        ("raw", "display", "decoded_signed"),
        [
            (0, "0x0000", 0),
            (1, "0x0001", 1),
            (32767, "0x7FFF", 32767),
            (-1, "0xFFFF", -1),
            (-2, "0xFFFE", -2),
            (-32768, "0x8000", -32768),
            (-42, "0xFFD6", -42),
        ],
    )
    def test_int16_negative_hex(
        self, raw: int, display: str, decoded_signed: int
    ) -> None:
        point = _hr(0, ValueKind.INT16, raw)
        assert format_decoded_display(point) == display
        assert decode_value(point) == decoded_signed
        # 表示文字列をそのまま戻しても同じビットパターンになる
        parsed = parse_decoded_input(display, ValueKind.INT16)
        restored = _hr(0, ValueKind.INT16, parsed)
        assert format_decoded_display(restored) == display
        assert decode_value(restored) == decoded_signed
        # 0x なし
        bare = display[2:]
        parsed_bare = parse_decoded_input(bare, ValueKind.INT16)
        assert format_decoded_display(_hr(0, ValueKind.INT16, parsed_bare)) == display

    @pytest.mark.parametrize(
        ("raw", "display", "decoded_signed"),
        [
            (0, "0x00000000", 0),
            (1, "0x00000001", 1),
            (0x7FFFFFFF, "0x7FFFFFFF", 0x7FFFFFFF),
            (-1, "0xFFFFFFFF", -1),
            (-2, "0xFFFFFFFE", -2),
            (-2147483648, "0x80000000", -2147483648),
            (0x12345678, "0x12345678", 0x12345678),
            (-0x12345678, "0xEDCBA988", -0x12345678),
        ],
    )
    def test_int32_negative_hex(
        self, raw: int, display: str, decoded_signed: int
    ) -> None:
        point = _hr(0, ValueKind.INT32, raw)
        assert format_decoded_display(point) == display
        assert decode_value(point) == decoded_signed
        parsed = parse_decoded_input(display, ValueKind.INT32)
        assert parsed == decoded_signed
        restored = _hr(0, ValueKind.INT32, parsed)
        assert format_decoded_display(restored) == display
        assert decode_value(restored) == decoded_signed
        bare = display[2:]
        assert parse_decoded_input(bare, ValueKind.INT32) == decoded_signed

    def test_int16_memory_stores_two_complement(self) -> None:
        slave = SlaveDatastore(1)
        for raw in (-1, -42, -32768, 32767):
            slave.upsert_point(_hr(0, ValueKind.INT16, raw))
            mem = slave.read_raw(RegisterKind.HOLDING_REGISTER, 0)
            assert mem == raw & 0xFFFF

    def test_int32_memory_stores_big_endian_pair(self) -> None:
        slave = SlaveDatastore(1)
        for raw in (-1, -2, -2147483648, 0x7FFFFFFF, 0x12345678):
            slave.upsert_point(_hr(10, ValueKind.INT32, raw))
            hi = slave.read_raw(RegisterKind.HOLDING_REGISTER, 10)
            lo = slave.read_raw(RegisterKind.HOLDING_REGISTER, 11)
            assert struct.unpack(">i", struct.pack(">HH", hi, lo))[0] == raw


# ---------------------------------------------------------------------------
# TCP: 代表ポートで待受できること / 特権ポートは UI で拒否
# ---------------------------------------------------------------------------


class TestTcpPortPolicy:
    @pytest.mark.parametrize("port", [1, 22, 80, 443, 502, 1023])
    def test_privileged_ports_rejected_by_ui(self, port: int, qapp: QApplication) -> None:
        panel = SettingsPanel()
        panel.tcp_host.setCurrentText("127.0.0.1")
        panel.tcp_port.setText(str(port))
        with pytest.raises(ValueError, match="特権ポート"):
            panel.get_tcp_config()

    @pytest.mark.parametrize("port", [0, -1, 65536, 99999])
    def test_invalid_port_numbers_rejected(self, port: int, qapp: QApplication) -> None:
        panel = SettingsPanel()
        panel.tcp_host.setCurrentText("127.0.0.1")
        panel.tcp_port.setText(str(port))
        with pytest.raises(ValueError, match="ポート"):
            panel.get_tcp_config()

    @pytest.mark.parametrize("port", [1024, 5020, 15000, 40000, 65535])
    def test_unprivileged_ports_accepted_by_ui(self, port: int, qapp: QApplication) -> None:
        panel = SettingsPanel()
        panel.tcp_host.setCurrentText("127.0.0.1")
        panel.tcp_port.setText(str(port))
        config = panel.get_tcp_config()
        assert config.port == port


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ---------------------------------------------------------------------------
# Modbus TCP: 全型・境界アドレスで実際に Read/Write
# ---------------------------------------------------------------------------


async def _tcp_rw(
    address: int,
    datatype: ValueKind,
    raw: int,
    *,
    host: str = "127.0.0.1",
) -> list[int]:
    from pymodbus.client import AsyncModbusTcpClient

    reg = SlaveRegistry()
    reg.get_slave(1).upsert_point(_hr(address, datatype, raw))
    mgr = ModbusServerManager(slave_registry=reg)
    port = _next_port()
    await mgr.start_tcp(TcpConfig(host=host, port=port))
    try:
        client = AsyncModbusTcpClient(host, port=port)
        assert await client.connect()
        count = 2 if datatype == ValueKind.INT32 else 1
        result = await client.read_holding_registers(address, count=count, device_id=1)
        assert not result.isError(), result
        registers = list(result.registers)
        # write back same pattern via client then re-read
        if datatype == ValueKind.INT32:
            hi, lo = registers
            wr = await client.write_registers(address, [hi, lo], device_id=1)
        else:
            wr = await client.write_register(address, registers[0], device_id=1)
        assert not wr.isError(), wr
        again = await client.read_holding_registers(address, count=count, device_id=1)
        assert not again.isError()
        assert list(again.registers) == registers
        client.close()
        return registers
    finally:
        await mgr.stop_tcp()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("address", "raw"),
    [
        (0, 0),
        (0, 65535),
        (1, 4660),
        (65535, 42),
        (32768, 0xABCD),
    ],
)
async def test_tcp_uint16_addresses(address: int, raw: int) -> None:
    regs = await _tcp_rw(address, ValueKind.UINT16, raw)
    assert regs == [raw]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("address", "raw"),
    [
        (0, -1),
        (0, -32768),
        (100, -42),
        (65535, 32767),
        (200, 0),
    ],
)
async def test_tcp_int16_including_negatives(address: int, raw: int) -> None:
    regs = await _tcp_rw(address, ValueKind.INT16, raw)
    assert regs == [raw & 0xFFFF]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("address", "raw"),
    [
        (0, -1),
        (0, -2147483648),
        (10, 0x7FFFFFFF),
        (65534, -2),
        (1000, 0x12345678),
    ],
)
async def test_tcp_int32_including_negatives(address: int, raw: int) -> None:
    regs = await _tcp_rw(address, ValueKind.INT32, raw)
    assert struct.unpack(">i", struct.pack(">HH", *regs))[0] == raw


@pytest.mark.asyncio
@pytest.mark.parametrize("port", [1024, 5020, 25000, 45000])
async def test_tcp_listen_on_representative_ports(port: int) -> None:
    """代表的な非特権ポートで実際に待受・通信できること。"""
    from pymodbus.client import AsyncModbusTcpClient

    reg = SlaveRegistry()
    reg.get_slave(1).upsert_point(_hr(0, ValueKind.UINT16, 99))
    mgr = ModbusServerManager(slave_registry=reg)
    try:
        await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
    except OSError as exc:
        # 環境によっては特定ポートが使用中。その場合はスキップ相当として明示失敗理由を出す
        pytest.skip(f"port {port} unavailable: {exc}")
    try:
        client = AsyncModbusTcpClient("127.0.0.1", port=port)
        assert await client.connect()
        result = await client.read_holding_registers(0, count=1, device_id=1)
        assert not result.isError()
        assert result.registers == [99]
        client.close()
    finally:
        await mgr.stop_tcp()


@pytest.mark.asyncio
async def test_tcp_hex_decoded_path_survives_server_build_for_negatives() -> None:
    """Decoded で負数相当の 16 進を入れたあと、サーバ起動・Read できること。"""
    from pymodbus.client import AsyncModbusTcpClient

    reg = SlaveRegistry()
    slave = reg.get_slave(1)
    # UI 相当: Decoded 入力 → raw 反映 → upsert
    raw16 = parse_decoded_input("0xFFD6", ValueKind.INT16)  # -42
    raw32 = parse_decoded_input("FFFFFFFF", ValueKind.INT32)  # -1
    slave.upsert_point(_hr(1, ValueKind.INT16, raw16))
    slave.upsert_point(_hr(10, ValueKind.INT32, raw32))

    mgr = ModbusServerManager(slave_registry=reg)
    port = _next_port()
    await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
    try:
        client = AsyncModbusTcpClient("127.0.0.1", port=port)
        assert await client.connect()
        r16 = await client.read_holding_registers(1, count=1, device_id=1)
        r32 = await client.read_holding_registers(10, count=2, device_id=1)
        assert not r16.isError() and not r32.isError()
        assert r16.registers == [0xFFD6]
        assert struct.unpack(">i", struct.pack(">HH", *r32.registers))[0] == -1
        client.close()
    finally:
        await mgr.stop_tcp()
