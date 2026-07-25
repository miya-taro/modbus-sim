"""Modbus server lifecycle management."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from datetime import datetime

from modbus_sim.config import CommMode, RtuConfig, TcpConfig
from modbus_sim.datastore import SlaveRegistry
from modbus_sim.logging_handler import LoggingModbusSerialServer, LoggingModbusTcpServer


def _parse_slave_id(mode: CommMode, sending: bool, packet: bytes) -> int | None:
    if sending:
        return None
    if mode == CommMode.TCP and len(packet) >= 7:
        return packet[6]
    if mode == CommMode.RTU and len(packet) >= 1:
        return packet[0]
    return None


class ModbusServerManager:
    def __init__(
        self,
        tcp_registry: SlaveRegistry | None = None,
        rtu_registry: SlaveRegistry | None = None,
        *,
        slave_registry: SlaveRegistry | None = None,
        on_log: Callable[[str], None] | None = None,
        on_tcp_state_change: Callable[[bool], None] | None = None,
        on_rtu_state_change: Callable[[bool], None] | None = None,
    ) -> None:
        # slave_registry はテスト互換: 指定時は TCP/RTU 両方に同じレジストリを使う
        if slave_registry is not None:
            self._tcp_registry = slave_registry
            self._rtu_registry = slave_registry
        else:
            from modbus_sim.datastore import rtu_registry as default_rtu
            from modbus_sim.datastore import tcp_registry as default_tcp

            self._tcp_registry = tcp_registry if tcp_registry is not None else default_tcp
            self._rtu_registry = rtu_registry if rtu_registry is not None else default_rtu
        self._tcp_server: LoggingModbusTcpServer | None = None
        self._rtu_server: LoggingModbusSerialServer | None = None
        self._tcp_task: asyncio.Task | None = None
        self._rtu_task: asyncio.Task | None = None
        self._on_log = on_log
        self._on_tcp_state_change = on_tcp_state_change
        self._on_rtu_state_change = on_rtu_state_change
        self.log_buffer: deque[str] = deque(maxlen=500)

    def _registry_for(self, mode: CommMode) -> SlaveRegistry:
        return self._tcp_registry if mode == CommMode.TCP else self._rtu_registry

    @property
    def tcp_running(self) -> bool:
        return self._tcp_server is not None

    @property
    def rtu_running(self) -> bool:
        return self._rtu_server is not None

    @property
    def any_running(self) -> bool:
        return self.tcp_running or self.rtu_running

    def _emit_log(self, message: str) -> None:
        self.log_buffer.append(message)
        if self._on_log:
            self._on_log(message)

    def _emit_tcp_state(self, running: bool) -> None:
        if self._on_tcp_state_change:
            self._on_tcp_state_change(running)

    def _emit_rtu_state(self, running: bool) -> None:
        if self._on_rtu_state_change:
            self._on_rtu_state_change(running)

    def _log_invalid(self, mode: CommMode, data: bytes, reason: str) -> None:
        hex_bytes = data.hex(" ").upper()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._emit_log(
            f"[{timestamp}] {mode.value.upper()} INVALID {reason}: {hex_bytes}"
        )

    def _make_trace_packet(self, mode: CommMode):
        registry = self._registry_for(mode)

        def _trace_packet(sending: bool, packet: bytes) -> bytes:
            direction = "TX" if sending else "RX"
            hex_bytes = packet.hex(" ").upper()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._emit_log(f"[{timestamp}] {mode.value.upper()} {direction} {hex_bytes}")
            slave_id = _parse_slave_id(mode, sending, packet)
            if slave_id is not None:
                registry.touch_activity(slave_id)
            return packet

        return _trace_packet

    def _make_on_invalid(self, mode: CommMode):
        def _on_invalid(data: bytes, reason: str) -> None:
            self._log_invalid(mode, data, reason)

        return _on_invalid

    async def start_tcp(self, config: TcpConfig) -> None:
        if self.tcp_running:
            raise RuntimeError("TCP server is already running")
        self._tcp_server = LoggingModbusTcpServer(
            self._tcp_registry.build_sim_devices(),
            address=(config.host, config.port),
            trace_packet=self._make_trace_packet(CommMode.TCP),
            on_invalid=self._make_on_invalid(CommMode.TCP),
        )
        # background=True: listen 完了後に戻る（クライアント接続前に待受準備を完了させる）
        await self._tcp_server.serve_forever(background=True)
        self._tcp_task = None
        self._tcp_registry.bind_server(self._tcp_server.context)
        self._emit_tcp_state(True)
        self._emit_log(
            f"[{datetime.now():%Y-%m-%d %H:%M:%S}] TCP server started on "
            f"{config.host}:{config.port}"
        )

    async def start_rtu(self, config: RtuConfig) -> None:
        if self.rtu_running:
            raise RuntimeError("RTU server is already running")
        self._rtu_server = LoggingModbusSerialServer(
            self._rtu_registry.build_sim_devices(),
            port=config.port,
            baudrate=config.baudrate,
            parity=config.parity.to_pyserial(),
            bytesize=config.bytesize,
            stopbits=config.stopbits,
            trace_packet=self._make_trace_packet(CommMode.RTU),
            on_invalid=self._make_on_invalid(CommMode.RTU),
        )
        await self._rtu_server.serve_forever(background=True)
        self._rtu_task = None
        self._rtu_registry.bind_server(self._rtu_server.context)
        self._emit_rtu_state(True)
        self._emit_log(
            f"[{datetime.now():%Y-%m-%d %H:%M:%S}] RTU server started on "
            f"{config.port} ({config.baudrate}, {config.parity.value})"
        )

    async def stop_tcp(self) -> None:
        if not self.tcp_running:
            return
        server = self._tcp_server
        task = self._tcp_task
        self._tcp_server = None
        self._tcp_task = None
        if server is not None:
            self._tcp_registry.unbind_server(server.context)
            await server.shutdown()
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._emit_tcp_state(False)
        self._emit_log(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] TCP server stopped")

    async def stop_rtu(self) -> None:
        if not self.rtu_running:
            return
        server = self._rtu_server
        task = self._rtu_task
        self._rtu_server = None
        self._rtu_task = None
        if server is not None:
            self._rtu_registry.unbind_server(server.context)
            await server.shutdown()
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._emit_rtu_state(False)
        self._emit_log(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] RTU server stopped")

    async def stop_all(self) -> None:
        await self.stop_tcp()
        await self.stop_rtu()
