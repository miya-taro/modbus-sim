"""Modbus マスター（クライアント）機能。

実スレーブ（または自分自身の TCP サーバ）へ Read/Write する。
サーバ機能と同じ asyncio ループ上で動く。同時に 1 接続。
"""

from __future__ import annotations

import asyncio
import time
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


def _new_stats() -> dict:
    return {
        "count": 0,
        "errors": 0,
        "last_ms": None,
        "min_ms": None,
        "max_ms": None,
        "_total_ms": 0.0,
        "started_at": None,
    }


class ModbusMaster:
    def __init__(self, on_log: Callable[[str], None] | None = None) -> None:
        self._client = None
        self._mode: CommMode | None = None
        self._target = ""
        self._on_log = on_log
        self._lock = asyncio.Lock()
        self._stats = _new_stats()

    def stats(self) -> dict:
        s = self._stats
        count = s["count"]
        started = s["started_at"]
        return {
            "count": count,
            "errors": s["errors"],
            "last_ms": round(s["last_ms"], 2) if s["last_ms"] is not None else None,
            "min_ms": round(s["min_ms"], 2) if s["min_ms"] is not None else None,
            "max_ms": round(s["max_ms"], 2) if s["max_ms"] is not None else None,
            "avg_ms": round(s["_total_ms"] / count, 2) if count else None,
            "elapsed_s": round(time.monotonic() - started, 1) if started else 0.0,
        }

    def reset_stats(self) -> None:
        self._stats = _new_stats()
        self._stats["started_at"] = time.monotonic()

    def _record(self, ms: float, *, ok: bool) -> None:
        s = self._stats
        s["count"] += 1
        if not ok:
            s["errors"] += 1
        s["last_ms"] = ms
        s["_total_ms"] += ms
        s["min_ms"] = ms if s["min_ms"] is None else min(s["min_ms"], ms)
        s["max_ms"] = ms if s["max_ms"] is None else max(s["max_ms"], ms)

    # --- lifecycle ---------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.connected

    def describe(self) -> dict:
        return {
            "connected": self.connected,
            "mode": self._mode.value if self._mode else None,
            "target": self._target,
            "stats": self.stats(),
        }

    def _log(self, msg: str) -> None:
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] MASTER {msg}"
        if self._on_log:
            self._on_log(line)

    async def connect_tcp(self, config: TcpConfig) -> None:
        from pymodbus.client import AsyncModbusTcpClient

        await self.disconnect()
        client = AsyncModbusTcpClient(config.host, port=config.port, timeout=2, retries=1)
        if not await client.connect():
            raise ConnectionError(f"接続できませんでした: {config.host}:{config.port}")
        self._client = client
        self._mode = CommMode.TCP
        self._target = f"{config.host}:{config.port}"
        self.reset_stats()
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
            timeout=2,
            retries=1,
        )
        if not await client.connect():
            raise ConnectionError(f"シリアルポートを開けませんでした: {config.port}")
        self._client = client
        self._mode = CommMode.RTU
        self._target = config.summary()
        self.reset_stats()
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

        from pymodbus.exceptions import ModbusException

        async with self._lock:
            t0 = time.perf_counter()
            try:
                if function in _READ_FNS:
                    result = await self._do_read(function, device_id, address, count, datatype, word_order)
                elif function in _WRITE_FNS:
                    result = await self._do_write(function, device_id, address, datatype, word_order, values or [])
                else:
                    raise ValueError(f"未知の function: {function}")
            except (ModbusException, asyncio.TimeoutError, ConnectionResetError, OSError) as exc:
                # 通信レベルの失敗は結果として返す（呼び出し側で例外にしない）
                self._record((time.perf_counter() - t0) * 1000, ok=False)
                self._log(f"error {function}: {exc}")
                return {"ok": False, "error": str(exc), "exception_code": None, "raw": [], "values": []}
            except Exception:
                self._record((time.perf_counter() - t0) * 1000, ok=False)
                raise
            self._record((time.perf_counter() - t0) * 1000, ok=bool(result.get("ok")))
            return result

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
