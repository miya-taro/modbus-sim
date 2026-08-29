"""Modbus マスター（クライアント）機能。

実スレーブ（または自分自身の TCP サーバ）へ Read/Write する。
サーバ機能と同じ asyncio ループ上で動く。同時に 1 接続。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

from modbus_sim.config import CommMode, RtuConfig, TcpConfig, ValueKind
from modbus_sim.datastore import registers_to_values, value_to_registers, validate_address
from modbus_sim.wordorder import WordOrder

# フロントから来る function 名 -> (pymodbus メソッド名, 書き込みか, ビットか)
_READ_FNS = {
    "read_coils": (1, True),
    "read_discrete_inputs": (2, True),
    "read_holding_registers": (3, False),
    "read_input_registers": (4, False),
}
_WRITE_FNS = {
    "write_coil": (5, True, False),
    "write_coils": (15, True, True),
    "write_register": (6, False, False),
    "write_registers": (16, False, True),
}


class ModbusMaster:
    def __init__(self, on_log: Callable[[str], None] | None = None) -> None:
        self._client = None
        self._mode: CommMode | None = None
        self._target = ""
        self._on_log = on_log
        self._lock = asyncio.Lock()

    # --- lifecycle ---------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.connected

    def describe(self) -> dict:
        return {
            "connected": self.connected,
            "mode": self._mode.value if self._mode else None,
            "target": self._target,
        }

    def _log(self, msg: str) -> None:
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] MASTER {msg}"
        if self._on_log:
            self._on_log(line)

    async def connect_tcp(self, config: TcpConfig) -> None:
        from pymodbus.client import AsyncModbusTcpClient

        await self.disconnect()
        client = AsyncModbusTcpClient(config.host, port=config.port, timeout=3)
        if not await client.connect():
            raise ConnectionError(f"接続できませんでした: {config.host}:{config.port}")
        self._client = client
        self._mode = CommMode.TCP
        self._target = f"{config.host}:{config.port}"
        self._log(f"connected {self._target}")

    async def connect_rtu(self, config: RtuConfig) -> None:
        from pymodbus.client import AsyncModbusSerialClient

        await self.disconnect()
        client = AsyncModbusSerialClient(
            config.port,
            baudrate=config.baudrate,
            bytesize=config.bytesize,
            parity=config.parity.to_pyserial(),
            stopbits=config.stopbits,
            timeout=3,
        )
        if not await client.connect():
            raise ConnectionError(f"シリアルポートを開けませんでした: {config.port}")
        self._client = client
        self._mode = CommMode.RTU
        self._target = config.summary()
        self._log(f"connected {self._target}")

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._log("disconnected")
        self._client = None
        self._mode = None
        self._target = ""

    # --- request ---------------------------------------------------
    async def request(
        self,
        *,
        function: str,
        device_id: int,
        address: int,
        count: int = 1,
        datatype: ValueKind = ValueKind.UINT16,
        word_order: WordOrder = WordOrder.ABCD,
        values: list[float] | None = None,
    ) -> dict:
        if not self.connected:
            raise ConnectionError("マスターが接続されていません")
        if not 0 <= address <= 0xFFFF:
            raise ValueError("Addr は 0-65535 です")

        async with self._lock:
            if function in _READ_FNS:
                return await self._do_read(function, device_id, address, count, datatype, word_order)
            if function in _WRITE_FNS:
                return await self._do_write(function, device_id, address, datatype, word_order, values or [])
            raise ValueError(f"未知の function: {function}")

    async def _do_read(self, function, device_id, address, count, datatype, word_order) -> dict:
        _fc, is_bit = _READ_FNS[function]
        span = 1 if is_bit else datatype.register_span
        qty = max(1, count) * span
        method = getattr(self._client, function)
        rr = await method(address, count=qty, device_id=device_id)
        self._log(f"TX {function} device={device_id} addr={address} count={qty}")
        if rr.isError():
            return _error_result(rr)
        if is_bit:
            bits = list(rr.bits)[: max(1, count)]
            return {"ok": True, "raw": [int(b) for b in bits], "values": [bool(b) for b in bits]}
        regs = list(rr.registers)
        return {
            "ok": True,
            "raw": regs,
            "values": registers_to_values(regs, datatype, word_order),
        }

    async def _do_write(self, function, device_id, address, datatype, word_order, values) -> dict:
        _fc, is_bit, multi = _WRITE_FNS[function]
        if not values:
            raise ValueError("書き込む値がありません")
        if is_bit:
            bit_vals = [bool(v) for v in values]
            if multi:
                wr = await self._client.write_coils(address, bit_vals, device_id=device_id)
            else:
                wr = await self._client.write_coil(address, bit_vals[0], device_id=device_id)
        else:
            regs: list[int] = []
            for v in values:
                validate_address(address + len(regs), datatype)
                regs.extend(value_to_registers(v, datatype, word_order))
            if multi:
                wr = await self._client.write_registers(address, regs, device_id=device_id)
            else:
                wr = await self._client.write_register(address, regs[0], device_id=device_id)
        self._log(f"TX {function} device={device_id} addr={address} values={values}")
        if wr.isError():
            return _error_result(wr)
        return {"ok": True, "raw": [], "values": []}


def _error_result(resp) -> dict:
    code = getattr(resp, "exception_code", None)
    return {
        "ok": False,
        "error": str(resp),
        "exception_code": code,
        "raw": [],
        "values": [],
    }
