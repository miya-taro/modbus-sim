"""Modbus server handlers with invalid-packet logging."""

from __future__ import annotations

from collections.abc import Callable

from pymodbus.constants import ExcCodes
from pymodbus.exceptions import ModbusIOException
from pymodbus.pdu import ExceptionResponse
from pymodbus.server import ModbusSerialServer, ModbusTcpServer
from pymodbus.server.requesthandler import ServerRequestHandler
from pymodbus.transaction import TransactionManager

from modbus_sim.packet_log import detect_invalid_tcp_frame


class LoggingServerRequestHandler(ServerRequestHandler):
    def __init__(
        self,
        owner,
        trace_packet,
        trace_pdu,
        trace_connect,
        on_invalid: Callable[[bytes, str], None] | None = None,
    ) -> None:
        self._on_invalid = on_invalid
        super().__init__(owner, trace_packet, trace_pdu, trace_connect)

    def callback_data(self, data: bytes, addr: tuple | None = None) -> int:
        # 受信バッファ先頭が明らかな不正 TCP なら INVALID を出して破棄
        reason = detect_invalid_tcp_frame(data)
        if reason is not None and self._on_invalid:
            self._on_invalid(data, reason)
            return len(data)
        try:
            used_len = TransactionManager.callback_data(self, data, addr)
        except ModbusIOException as exc:
            if self._on_invalid:
                self._on_invalid(data, str(exc))
            # FC=40 は非標準なので、一般的な Read Holding の例外として返す
            response = ExceptionResponse(0x03, exception_code=ExcCodes.ILLEGAL_FUNCTION)
            self.server_send(response, 0)
            return len(data)
        if self.last_pdu:
            self.loop.call_soon(self.handle_later)
        return used_len


class _LoggingModbusServerMixin:
    _on_invalid: Callable[[bytes, str], None] | None = None

    def callback_new_connection(self):
        return LoggingServerRequestHandler(
            self,
            self.trace_packet,
            self.trace_pdu,
            self.trace_connect,
            self._on_invalid,
        )


class LoggingModbusTcpServer(_LoggingModbusServerMixin, ModbusTcpServer):
    def __init__(self, *args, on_invalid: Callable[[bytes, str], None] | None = None, **kwargs) -> None:
        self._on_invalid = on_invalid
        super().__init__(*args, **kwargs)


class LoggingModbusSerialServer(_LoggingModbusServerMixin, ModbusSerialServer):
    def __init__(self, *args, on_invalid: Callable[[bytes, str], None] | None = None, **kwargs) -> None:
        self._on_invalid = on_invalid
        super().__init__(*args, **kwargs)
