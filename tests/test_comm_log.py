"""通信ログのサマリ生成と TCP 連携テスト。"""

from __future__ import annotations

from itertools import count

import pytest

from modbus_sim.config import CommMode, RegisterKind, TcpConfig, ValueKind
from modbus_sim.datastore import SlaveRegistry
from modbus_sim.models import RegisterPoint
from modbus_sim.packet_log import format_trace_log_line, summarize_modbus_packet
from modbus_sim.server_manager import ModbusServerManager
from modbus_sim.ui.log_panel import LogPanel

_port = count(17000)


def _next_port() -> int:
    return next(_port)


def _hr(address: int, raw: int) -> RegisterPoint:
    return RegisterPoint(
        address=address,
        kind=RegisterKind.HOLDING_REGISTER,
        datatype=ValueKind.UINT16,
        raw=raw,
    )


class TestSummarizePacket:
    def test_tcp_read_holding_request(self) -> None:
        # MBAP + unit=1 + FC03 addr=0 count=1
        packet = bytes.fromhex("000100000006010300000001")
        summary = summarize_modbus_packet(CommMode.TCP, packet)
        assert summary is not None
        assert "FC=03" in summary
        assert "ReadHoldingRegisters" in summary
        assert "addr=0" in summary
        assert "count=1" in summary
        assert "device=1" in summary

    def test_tcp_read_holding_response(self) -> None:
        # MBAP + unit=1 + FC03 byte_count=2 data=04D2 (1234)
        packet = bytes.fromhex("00010000000501030204D2")
        summary = summarize_modbus_packet(CommMode.TCP, packet)
        assert summary is not None
        assert "FC=03" in summary
        assert "values=[1234]" in summary

    def test_tcp_write_single_register(self) -> None:
        packet = bytes.fromhex("0002000000060106000004D2")
        summary = summarize_modbus_packet(CommMode.TCP, packet)
        assert summary is not None
        assert "FC=06" in summary
        assert "addr=0" in summary
        assert "value=1234" in summary

    def test_rtu_read_request(self) -> None:
        # slave=1 FC03 addr=0 count=10 CRC=C5CD
        packet = bytes.fromhex("01030000000AC5CD")
        summary = summarize_modbus_packet(CommMode.RTU, packet)
        assert summary is not None
        assert "device=1" in summary
        assert "FC=03" in summary
        assert "addr=0" in summary
        assert "count=10" in summary

    def test_format_line_includes_summary_and_hex(self) -> None:
        packet = bytes.fromhex("000100000006010300000001")
        line = format_trace_log_line(CommMode.TCP, False, packet, timestamp="2026-01-01 00:00:00")
        assert line.startswith("[2026-01-01 00:00:00] TCP RX")
        assert "FC=03" in line
        assert "|" in line
        assert "01 03 00 00 00 01" in line


@pytest.mark.asyncio
async def test_tcp_communication_appends_rx_tx_logs() -> None:
    from pymodbus.client import AsyncModbusTcpClient

    reg = SlaveRegistry()
    reg.get_slave(1).upsert_point(_hr(0, 100))
    mgr = ModbusServerManager(slave_registry=reg)
    port = _next_port()
    await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
    try:
        before = len(mgr.log_buffer)
        client = AsyncModbusTcpClient("127.0.0.1", port=port)
        assert await client.connect()
        result = await client.read_holding_registers(0, count=1, device_id=1)
        assert not result.isError()
        assert result.registers == [100]
        wr = await client.write_register(0, 1234, device_id=1)
        assert not wr.isError()
        client.close()

        lines = list(mgr.log_buffer)[before:]
        joined = "\n".join(lines)
        assert any("TCP RX" in line and "FC=03" in line for line in lines)
        assert any("TCP TX" in line and "FC=03" in line for line in lines)
        assert any("TCP RX" in line and "FC=06" in line for line in lines)
        assert "addr=0" in joined
        assert "value=1234" in joined or "values=[100]" in joined
    finally:
        await mgr.stop_tcp()


@pytest.mark.asyncio
async def test_tcp_invalid_protocol_id_logs_invalid() -> None:
    """不正 protocol id の TCP フレームが INVALID になること。"""
    import asyncio

    reg = SlaveRegistry()
    reg.get_slave(1).upsert_point(_hr(0, 1))
    mgr = ModbusServerManager(slave_registry=reg)
    port = _next_port()
    await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
    try:
        before = len(mgr.log_buffer)
        _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        # protocol id = 0xFFFF (!= 0)
        writer.write(b"\x00\x01\xff\xff\x00\x06\x01\x03\x00\x00\x00\x01")
        await writer.drain()
        await asyncio.sleep(0.3)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        lines = list(mgr.log_buffer)[before:]
        assert any("INVALID" in line and "protocol id" in line for line in lines)
    finally:
        await mgr.stop_tcp()


def test_log_invalid_helper_emits_invalid_line() -> None:
    mgr = ModbusServerManager(slave_registry=SlaveRegistry())
    mgr._log_invalid(CommMode.TCP, b"\xff\xff\x00\x01", "Unable to decode request")
    assert any(
        "INVALID" in line and "Unable to decode request" in line and "FF FF" in line
        for line in mgr.log_buffer
    )


def test_log_panel_set_lines_and_clear(qapp) -> None:
    cleared = {"done": False}

    def _on_clear() -> None:
        cleared["done"] = True

    panel = LogPanel(on_clear=_on_clear)
    assert panel.set_lines(["a", "b"]) is True
    assert panel.log_field.toPlainText() == "a\nb"
    assert panel.set_lines(["a", "b"]) is False  # unchanged
    panel.clear_button.click()
    assert cleared["done"] is True


def test_log_panel_mode_filter(qapp) -> None:
    panel = LogPanel()
    lines = [
        "[2026-08-04 10:00:00] TCP RX device=1 FC=03 addr=0 count=1 | 00",
        "[2026-08-04 10:00:01] RTU RX device=2 FC=03 addr=0 count=1 | 01",
    ]
    panel.set_lines(lines)
    panel.mode_filter.setCurrentText("TCP")
    assert panel.log_field.toPlainText() == lines[0]
    panel.mode_filter.setCurrentText("RTU")
    assert panel.log_field.toPlainText() == lines[1]
    panel.mode_filter.setCurrentText("すべて")
    assert panel.log_field.toPlainText() == "\n".join(lines)


def test_log_panel_search_filter(qapp) -> None:
    panel = LogPanel()
    lines = [
        "[2026-08-04 10:00:00] TCP RX device=1 FC=03 addr=0 count=1 | 00",
        "[2026-08-04 10:00:01] TCP RX device=2 FC=03 addr=0 count=1 | 01",
    ]
    panel.set_lines(lines)
    panel.search_field.setText("device=2")
    assert panel.log_field.toPlainText() == lines[1]


def test_log_panel_pause_holds_display_until_resumed(qapp) -> None:
    panel = LogPanel()
    panel.set_lines(["a"])
    panel.pause_button.setChecked(True)
    panel.set_lines(["a", "b"])
    assert panel.log_field.toPlainText() == "a"
    panel.pause_button.setChecked(False)
    assert panel.log_field.toPlainText() == "a\nb"


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    import sys

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app
