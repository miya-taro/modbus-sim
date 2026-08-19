"""Multi-slave Modbus datastore."""

from __future__ import annotations

import asyncio
import math
import random
import struct
import time
from collections.abc import Callable
from typing import Any

from pymodbus.constants import ExcCodes
from pymodbus.simulator import DataType, SimData, SimDevice
from pymodbus.simulator.simutils import SimUtils

from modbus_sim.config import (
    ACTIVITY_TIMEOUT_SEC,
    REGISTER_COUNT,
    AutoMode,
    FaultException,
    FaultMode,
    RegisterKind,
    ValueKind,
)
from modbus_sim.models import RegisterPoint

ActionFn = Callable[
    [int, int, int, int, list[int], list[int] | list[bool] | None],
    None | ExcCodes,
]

BlockMap = dict[str, tuple[int, int, list[int], list[int]] | None]

# FaultMode.NO_RESPONSE のとき、応答を送らずこの秒数だけ待つ
# （マスタのタイムアウトより十分長い想定。切断/サーバ停止で中断される）。
_NO_RESPONSE_HANG_SECONDS = 24 * 60 * 60

_FAULT_EXCEPTION_MAP: dict[FaultException, ExcCodes] = {
    FaultException.ILLEGAL_FUNCTION: ExcCodes.ILLEGAL_FUNCTION,
    FaultException.ILLEGAL_DATA_ADDRESS: ExcCodes.ILLEGAL_ADDRESS,
    FaultException.ILLEGAL_DATA_VALUE: ExcCodes.ILLEGAL_VALUE,
    FaultException.DEVICE_FAILURE: ExcCodes.DEVICE_FAILURE,
    FaultException.ACKNOWLEDGE: ExcCodes.ACKNOWLEDGE,
    FaultException.DEVICE_BUSY: ExcCodes.DEVICE_BUSY,
    FaultException.NEGATIVE_ACKNOWLEDGE: ExcCodes.NEGATIVE_ACKNOWLEDGE,
    FaultException.MEMORY_PARITY_ERROR: ExcCodes.MEMORY_PARITY_ERROR,
    FaultException.GATEWAY_PATH_UNAVAILABLE: ExcCodes.GATEWAY_PATH_UNAVIABLE,
    FaultException.GATEWAY_NO_RESPONSE: ExcCodes.GATEWAY_NO_RESPONSE,
}

# fault_mode / auto_mode の対象は Holding/Input Register のみ（コメント参照は config.py 側）。
_HOLDING_FAULT_FCS = (3, 6, 16, 22, 23)
_INPUT_FAULT_FC = 4


def datatype_bounds(datatype: ValueKind) -> tuple[int, int]:
    """レジスタ datatype が表現できる raw 値の範囲 (min, max)。"""
    if datatype == ValueKind.INT16:
        return -32768, 32767
    if datatype == ValueKind.INT32:
        return -2147483648, 2147483647
    if datatype == ValueKind.BOOL:
        return 0, 1
    return 0, 65535


def _block_key_for_kind(kind: RegisterKind) -> str:
    if kind == RegisterKind.COIL:
        return "c"
    if kind == RegisterKind.DISCRETE_INPUT:
        return "d"
    if kind == RegisterKind.HOLDING_REGISTER:
        return "h"
    return "i"


def _write_register_point_to_block(
    point: RegisterPoint,
    block: tuple[int, int, list[int], list[int]] | None,
    memory: list[int],
) -> None:
    if block is None:
        return
    start_address, register_count, registers, _flags = block
    offset = point.address - start_address
    if point.datatype == ValueKind.INT32:
        if 0 <= offset < register_count - 1:
            registers[offset] = memory[point.address]
            registers[offset + 1] = memory[point.address + 1]
    elif 0 <= offset < register_count:
        registers[offset] = memory[point.address]


class SlaveDatastore:
    def __init__(self, slave_id: int, owner: SlaveRegistry | None = None) -> None:
        self.slave_id = slave_id
        self._owner = owner
        self.points: dict[tuple[int, RegisterKind], RegisterPoint] = {}
        self._coils = [False] * REGISTER_COUNT
        self._discrete_inputs = [False] * REGISTER_COUNT
        self._holding_registers = [0] * REGISTER_COUNT
        self._input_registers = [0] * REGISTER_COUNT
        self._bindings: list[tuple[Any, BlockMap]] = []

    def list_points(self) -> list[RegisterPoint]:
        return sorted(self.points.values(), key=lambda point: (point.kind.value, point.address))

    def get_point(self, address: int, kind: RegisterKind) -> RegisterPoint | None:
        return self.points.get((address, kind))

    def upsert_point(self, point: RegisterPoint) -> None:
        existing = self.points.get(point.key)
        structural = (
            existing is None
            or existing.address != point.address
            or existing.kind != point.kind
            or existing.datatype != point.datatype
        )
        self.points[point.key] = point
        self._write_raw(point)
        if structural and self._owner is not None:
            self._owner.invalidate_sim_devices()

    def remove_point(self, address: int, kind: RegisterKind) -> bool:
        point = self.points.pop((address, kind), None)
        if point is None:
            return False
        self._write_raw(RegisterPoint(address=address, kind=kind, datatype=point.datatype, raw=0))
        if self._owner is not None:
            self._owner.invalidate_sim_devices()
        return True

    def _simdata_for_kind(self, kind: RegisterKind) -> list[SimData]:
        # レジスタ点だけを個別に渡すと、その時点で未定義のアドレスは
        # サーバ側のブロック範囲外になり、サーバ起動中に新しい点を追加しても
        # クライアントから読めない（ILLEGAL ADDRESS）ままになる。
        # そのため常に REGISTER_COUNT 全域を 1 ブロックとして渡し、
        # どのアドレスが後から追加されても既存ブロック内に収まるようにする。
        memory = list(self._memory(kind))
        if kind in (RegisterKind.COIL, RegisterKind.DISCRETE_INPUT):
            return [SimData(address=0, count=1, values=memory, datatype=DataType.BITS)]
        return [SimData(address=0, count=1, values=memory, datatype=DataType.REGISTERS)]

    def _memory(self, kind: RegisterKind) -> list[bool] | list[int]:
        if kind == RegisterKind.COIL:
            return self._coils
        if kind == RegisterKind.DISCRETE_INPUT:
            return self._discrete_inputs
        if kind == RegisterKind.HOLDING_REGISTER:
            return self._holding_registers
        return self._input_registers

    def read_raw(self, kind: RegisterKind, address: int):
        memory = self._memory(kind)
        return memory[address]

    def _all_blocks(self) -> list[BlockMap]:
        return [blocks for _runtime, blocks in self._bindings]

    def _write_raw(self, point: RegisterPoint) -> None:
        memory = self._memory(point.kind)
        if point.kind in (RegisterKind.COIL, RegisterKind.DISCRETE_INPUT):
            memory[point.address] = bool(point.raw)
            block_key = _block_key_for_kind(point.kind)
            bits = self._coils if block_key == "c" else self._discrete_inputs
            for blocks in self._all_blocks():
                block = blocks.get(block_key)
                if block is not None:
                    _sync_bits_to_registers(bits, block[2], block[0])
            return

        if point.datatype == ValueKind.INT32:
            packed = struct.pack(">i", int(point.raw))
            hi, lo = struct.unpack(">HH", packed)
            memory[point.address] = hi
            memory[point.address + 1] = lo
        else:
            value = int(point.raw)
            if point.datatype == ValueKind.INT16 and value < 0:
                value &= 0xFFFF
            memory[point.address] = value

        block_key = _block_key_for_kind(point.kind)
        memory = self._memory(point.kind)
        for blocks in self._all_blocks():
            _write_register_point_to_block(point, blocks.get(block_key), memory)

    def sync_from_server(self) -> bool:
        changed = False
        for point in self.points.values():
            if point.kind in (RegisterKind.COIL, RegisterKind.DISCRETE_INPUT):
                latest = int(bool(self.read_raw(point.kind, point.address)))
            elif point.datatype == ValueKind.INT32 and point.kind in (
                RegisterKind.HOLDING_REGISTER,
                RegisterKind.INPUT_REGISTER,
            ):
                memory = self._memory(point.kind)
                latest = raw_from_memory(
                    point,
                    hi=int(memory[point.address]),
                    lo=int(memory[point.address + 1]),
                )
            else:
                latest = raw_from_memory(
                    point, hi=int(self.read_raw(point.kind, point.address))
                )
            if _raw_values_equal(point, latest):
                continue
            point.raw = latest
            changed = True
        return changed

    def bind_runtime(self, runtime) -> None:
        blocks: BlockMap = {key: runtime.block.get(key) for key in ("c", "d", "h", "i")}
        self._bindings.append((runtime, blocks))
        self._push_all_to_server(blocks)

    def unbind_runtime(self, runtime) -> None:
        self._bindings = [(r, b) for r, b in self._bindings if r is not runtime]

    def _push_all_to_server(self, blocks: BlockMap) -> None:
        for point in self.points.values():
            if point.kind in (RegisterKind.COIL, RegisterKind.DISCRETE_INPUT):
                block_key = _block_key_for_kind(point.kind)
                block = blocks.get(block_key)
                if block is not None:
                    bits = self._coils if block_key == "c" else self._discrete_inputs
                    _sync_bits_to_registers(bits, block[2], block[0])
                continue
            memory = self._memory(point.kind)
            _write_register_point_to_block(point, blocks.get(_block_key_for_kind(point.kind)), memory)

    def _fault_kind_for_fc(self, function_code: int) -> RegisterKind | None:
        if function_code in _HOLDING_FAULT_FCS:
            return RegisterKind.HOLDING_REGISTER
        if function_code == _INPUT_FAULT_FC:
            return RegisterKind.INPUT_REGISTER
        return None

    def _first_fault_point(self, kind: RegisterKind, address: int, count: int) -> RegisterPoint | None:
        for offset in range(max(count, 1)):
            point = self.points.get((address + offset, kind))
            if point is not None and point.has_advanced_settings():
                return point
        return None

    async def _apply_faults(self, function_code: int, address: int, count: int) -> ExcCodes | None:
        """該当アドレスに fault/delay 設定があれば適用する。

        戻り値が ExcCodes の場合、呼び出し側は通常処理をせずそれを応答として返す。
        """
        kind = self._fault_kind_for_fc(function_code)
        if kind is None:
            return None
        point = self._first_fault_point(kind, address, count)
        if point is None:
            return None
        if point.delay_max_ms > 0:
            delay_ms = point.delay_min_ms
            if point.delay_max_ms > point.delay_min_ms:
                delay_ms = random.randint(point.delay_min_ms, point.delay_max_ms)
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000)
        if point.fault_mode == FaultMode.NO_RESPONSE:
            # マスタの切断/サーバ停止でこの await はキャンセルされる想定。
            await asyncio.sleep(_NO_RESPONSE_HANG_SECONDS)
            return None
        if point.fault_mode == FaultMode.EXCEPTION:
            return _FAULT_EXCEPTION_MAP[point.fault_exception]
        return None

    def make_action(self) -> ActionFn:
        slave = self

        async def _action(
            function_code: int,
            start_address: int,
            address: int,
            _count: int,
            current_registers: list[int],
            set_values: list[int] | list[bool] | None,
        ) -> None | ExcCodes:
            fault_result = await slave._apply_faults(function_code, address, _count)
            if fault_result is not None:
                return fault_result
            if function_code in (1, 5, 15):
                _sync_bits_to_registers(slave._coils, current_registers, start_address)
                if set_values is not None:
                    for index, value in enumerate(set_values):
                        slave._coils[address + index] = bool(value)
                    _sync_bits_to_registers(slave._coils, current_registers, start_address)
                    slave._sync_points_from_memory(RegisterKind.COIL, address, len(set_values))
            elif function_code == 2:
                _sync_bits_to_registers(slave._discrete_inputs, current_registers, start_address)
            elif function_code in (3, 6, 16, 22, 23):
                for index in range(len(current_registers)):
                    addr = start_address + index
                    if addr < len(slave._holding_registers):
                        current_registers[index] = slave._holding_registers[addr]
                if set_values is not None:
                    offset = address - start_address
                    for index, value in enumerate(set_values):
                        slave._holding_registers[offset + index] = int(value)
                    slave._sync_points_from_memory(RegisterKind.HOLDING_REGISTER, offset, len(set_values))
            elif function_code == 4:
                for index in range(len(current_registers)):
                    addr = start_address + index
                    if addr < len(slave._input_registers):
                        current_registers[index] = slave._input_registers[addr]
            return None

        return _action

    def _sync_points_from_memory(self, kind: RegisterKind, offset: int, count: int) -> None:
        for index in range(offset, offset + count):
            key = (index, kind)
            if key not in self.points:
                continue
            point = self.points[key]
            if point.datatype == ValueKind.INT32:
                memory = self._memory(kind)
                point.raw = raw_from_memory(
                    point, hi=int(memory[index]), lo=int(memory[index + 1])
                )
            else:
                point.raw = raw_from_memory(point, hi=int(self.read_raw(kind, index)))

    def tick_auto_values(self, dt: float) -> bool:
        """自動変化が有効な全ポイントを dt 秒進める。値が変わったら True。"""
        changed = False
        for point in self.points.values():
            if point.auto_mode == AutoMode.NONE:
                continue
            if point.kind not in (RegisterKind.HOLDING_REGISTER, RegisterKind.INPUT_REGISTER):
                continue
            new_raw = _next_auto_value(point, dt)
            if new_raw is None or new_raw == point.raw:
                continue
            point.raw = new_raw
            self._write_raw(point)
            changed = True
        return changed

    def build_sim_device(self) -> SimDevice:
        return SimDevice(
            id=self.slave_id,
            simdata=(
                self._simdata_for_kind(RegisterKind.COIL),
                self._simdata_for_kind(RegisterKind.DISCRETE_INPUT),
                self._simdata_for_kind(RegisterKind.HOLDING_REGISTER),
                self._simdata_for_kind(RegisterKind.INPUT_REGISTER),
            ),
            action=self.make_action(),
        )


class SlaveRegistry:
    def __init__(self) -> None:
        self._slaves: dict[int, SlaveDatastore] = {1: SlaveDatastore(1, owner=self)}
        self._tags: dict[int, str] = {1: ""}
        self._activity: dict[int, float] = {}
        self.selected_slave_id = 1
        self._sim_devices: list[SimDevice] | None = None

    def invalidate_sim_devices(self) -> None:
        self._sim_devices = None

    def list_slave_ids(self) -> list[int]:
        return sorted(self._slaves)

    def get_tag(self, slave_id: int) -> str:
        return self._tags.get(slave_id, "")

    def set_tag(self, slave_id: int, tag: str) -> None:
        if slave_id not in self._slaves:
            raise KeyError(f"Slave ID {slave_id} not found")
        self._tags[slave_id] = tag.strip()

    def touch_activity(self, slave_id: int) -> None:
        if slave_id in self._slaves:
            self._activity[slave_id] = time.monotonic()

    def activity_state(self, slave_id: int, *, any_server_running: bool) -> str:
        if not any_server_running:
            return "off"
        last = self._activity.get(slave_id)
        if last is not None and time.monotonic() - last < ACTIVITY_TIMEOUT_SEC:
            return "active"
        return "idle"

    def get_slave(self, slave_id: int) -> SlaveDatastore:
        if slave_id not in self._slaves:
            raise KeyError(f"Slave ID {slave_id} not found")
        return self._slaves[slave_id]

    def add_slave(self, slave_id: int) -> None:
        if not 1 <= slave_id <= 247:
            raise ValueError("Slave ID は 1-247 の範囲で指定してください")
        if slave_id in self._slaves:
            raise ValueError(f"Slave ID {slave_id} は既に存在します")
        self._slaves[slave_id] = SlaveDatastore(slave_id, owner=self)
        self._tags[slave_id] = ""
        self.invalidate_sim_devices()

    def remove_slave(self, slave_id: int) -> None:
        if slave_id not in self._slaves:
            raise KeyError(f"Slave ID {slave_id} not found")
        if len(self._slaves) <= 1:
            raise ValueError("最後の Slave は削除できません")
        del self._slaves[slave_id]
        self._tags.pop(slave_id, None)
        self._activity.pop(slave_id, None)
        if self.selected_slave_id == slave_id:
            self.selected_slave_id = self.list_slave_ids()[0]
        self.invalidate_sim_devices()

    def build_sim_devices(self) -> list[SimDevice]:
        # TCP / RTU が同じ SimDevice インスタンスを共有しないよう、起動のたびに新規生成する
        return [slave.build_sim_device() for slave in self._slaves.values()]

    def bind_server(self, context) -> None:
        for slave_id, runtime in context.devices.items():
            if slave_id in self._slaves:
                self._slaves[slave_id].bind_runtime(runtime)

    def unbind_server(self, context) -> None:
        for slave_id, runtime in context.devices.items():
            if slave_id in self._slaves:
                self._slaves[slave_id].unbind_runtime(runtime)

    def sync_from_server(self) -> bool:
        # any(...) だと最初に True を返した slave で残りの評価が打ち切られ、
        # 後続の slave が同期されなくなる。全 slave を必ず評価する。
        return any([slave.sync_from_server() for slave in self._slaves.values()])

    def tick_auto_values(self, dt: float) -> bool:
        return any([slave.tick_auto_values(dt) for slave in self._slaves.values()])

    def to_dict(self) -> dict:
        slaves = []
        for slave_id in self.list_slave_ids():
            slave = self._slaves[slave_id]
            points = []
            for point in slave.list_points():
                point_data = {
                    "address": point.address,
                    "kind": point.kind.value,
                    "datatype": point.datatype.value,
                    "raw": point.raw,
                    "tag": point.tag,
                }
                if point.has_advanced_settings():
                    point_data["fault_mode"] = point.fault_mode.value
                    point_data["fault_exception"] = point.fault_exception.value
                    point_data["delay_min_ms"] = point.delay_min_ms
                    point_data["delay_max_ms"] = point.delay_max_ms
                    point_data["auto_mode"] = point.auto_mode.value
                    point_data["auto_min"] = point.auto_min
                    point_data["auto_max"] = point.auto_max
                    point_data["auto_step"] = point.auto_step
                    point_data["auto_period_sec"] = point.auto_period_sec
                points.append(point_data)
            slaves.append(
                {
                    "id": slave_id,
                    "tag": self._tags.get(slave_id, ""),
                    "points": points,
                }
            )
        return {"slaves": slaves, "selected_slave_id": self.selected_slave_id}

    def load_from_dict(self, data: dict) -> None:
        slaves_data = data.get("slaves")
        if not isinstance(slaves_data, list) or not slaves_data:
            return
        self._slaves.clear()
        self._tags.clear()
        self._activity.clear()
        for entry in slaves_data:
            if not isinstance(entry, dict):
                continue
            try:
                slave_id = int(entry.get("id", 0))
            except (TypeError, ValueError):
                continue
            if not 1 <= slave_id <= 247:
                continue
            self._slaves[slave_id] = SlaveDatastore(slave_id, owner=self)
            self._tags[slave_id] = str(entry.get("tag", "")).strip()
            points = entry.get("points", [])
            if isinstance(points, list):
                for point_data in points:
                    if not isinstance(point_data, dict):
                        continue
                    try:
                        point = RegisterPoint(
                            address=int(point_data["address"]),
                            kind=RegisterKind(point_data.get("kind", RegisterKind.HOLDING_REGISTER.value)),
                            datatype=ValueKind(point_data.get("datatype", ValueKind.UINT16.value)),
                            tag=str(point_data.get("tag", "")),
                            raw=int(point_data.get("raw", 0)),
                        )
                        if "fault_mode" in point_data:
                            point.fault_mode = FaultMode(point_data["fault_mode"])
                        if "fault_exception" in point_data:
                            point.fault_exception = FaultException(point_data["fault_exception"])
                        if "delay_min_ms" in point_data:
                            point.delay_min_ms = int(point_data["delay_min_ms"])
                        if "delay_max_ms" in point_data:
                            point.delay_max_ms = int(point_data["delay_max_ms"])
                        if "auto_mode" in point_data:
                            point.auto_mode = AutoMode(point_data["auto_mode"])
                        if "auto_min" in point_data:
                            point.auto_min = int(point_data["auto_min"])
                        if "auto_max" in point_data:
                            point.auto_max = int(point_data["auto_max"])
                        if "auto_step" in point_data:
                            point.auto_step = float(point_data["auto_step"])
                        if "auto_period_sec" in point_data:
                            point.auto_period_sec = float(point_data["auto_period_sec"])
                        self._slaves[slave_id].upsert_point(point)
                    except (KeyError, ValueError):
                        continue
        if not self._slaves:
            self._slaves[1] = SlaveDatastore(1, owner=self)
            self._tags[1] = ""
        selected = data.get("selected_slave_id", 1)
        if isinstance(selected, int) and selected in self._slaves:
            self.selected_slave_id = selected
        else:
            self.selected_slave_id = self.list_slave_ids()[0]
        self.invalidate_sim_devices()


def _next_auto_value(point: RegisterPoint, dt: float) -> int | None:
    """auto_mode に従い dt 秒進めた次の raw 値を返す（変化なし/未設定なら None）。

    point.auto_phase を内部進行状態として書き換える副作用がある。
    """
    if point.auto_mode == AutoMode.NONE:
        return None
    lo, hi = datatype_bounds(point.datatype)
    auto_min = max(point.auto_min, lo)
    auto_max = min(point.auto_max, hi)
    if auto_min >= auto_max:
        return None  # 範囲が未設定/不正なら何もしない
    period = point.auto_period_sec
    if period <= 0:
        return None

    if point.auto_mode == AutoMode.SINE:
        point.auto_phase = (point.auto_phase + dt) % period
        span = auto_max - auto_min
        value = auto_min + span * (0.5 + 0.5 * math.sin(2 * math.pi * point.auto_phase / period))
        return int(round(value))

    # INCREMENT / RANDOM_WALK は auto_period_sec ごとに 1 ステップ進める
    point.auto_phase += dt
    if point.auto_phase < period:
        return None
    point.auto_phase = 0.0

    if point.auto_mode == AutoMode.INCREMENT:
        span = auto_max - auto_min + 1
        step = int(round(point.auto_step)) or 1  # 0 は「実質無変化」で分かりにくいため 1 扱い
        return auto_min + ((point.raw - auto_min) + step) % span

    if point.auto_mode == AutoMode.RANDOM_WALK:
        step = abs(point.auto_step) or 1.0
        delta = random.uniform(-step, step)
        return max(auto_min, min(auto_max, int(round(point.raw + delta))))

    return None


def validate_address(address: int, datatype: ValueKind) -> None:
    if not 0 <= address < REGISTER_COUNT:
        raise ValueError(f"Addr は 0-{REGISTER_COUNT - 1} です")
    if datatype == ValueKind.INT32 and address + 1 >= REGISTER_COUNT:
        raise ValueError(f"int32 は Addr が {REGISTER_COUNT - 2} 以下である必要があります")


def _sync_bits_to_registers(bits: list[bool], registers: list[int], block_start: int = 0) -> None:
    # registers はブロック先頭 (block_start 番目の packed ワード) から始まる
    # サーバ側の実配列なので、packed 側もそのオフセット分ずらして書き込む
    padded = bits + [False] * ((len(bits) + 15) // 16 * 16 - len(bits))
    packed = SimUtils.bitsToRegisters(padded)
    for index in range(len(registers) - 1):
        source_index = block_start + index
        if source_index < len(packed):
            registers[index] = packed[source_index]


def decode_value(point: RegisterPoint) -> str | int | bool:
    if point.kind in (RegisterKind.COIL, RegisterKind.DISCRETE_INPUT):
        return bool(point.raw)
    if point.datatype == ValueKind.UINT16:
        return int(point.raw) & 0xFFFF
    if point.datatype == ValueKind.INT16:
        value = int(point.raw) & 0xFFFF
        return value - 0x10000 if value >= 0x8000 else value
    if point.datatype == ValueKind.INT32:
        return int(point.raw)
    return point.raw


def raw_from_memory(point: RegisterPoint, *, hi: int | None = None, lo: int | None = None) -> int:
    """メモリ上の符号なし値を、point.datatype に合わせた raw に変換する。"""
    if point.kind in (RegisterKind.COIL, RegisterKind.DISCRETE_INPUT):
        return int(bool(hi if hi is not None else 0))
    if point.datatype == ValueKind.INT32:
        assert hi is not None and lo is not None
        return struct.unpack(">i", struct.pack(">HH", hi & 0xFFFF, lo & 0xFFFF))[0]
    value = int(hi if hi is not None else 0) & 0xFFFF
    if point.datatype == ValueKind.INT16:
        return value - 0x10000 if value >= 0x8000 else value
    return value


def _raw_values_equal(point: RegisterPoint, latest: int) -> bool:
    """UI raw とメモリ由来 raw が実質同じか（int16 の -1 と 0xFFFF を同一視）。"""
    if point.datatype == ValueKind.INT16:
        return (int(point.raw) & 0xFFFF) == (int(latest) & 0xFFFF)
    if point.datatype == ValueKind.INT32:
        return (int(point.raw) & 0xFFFFFFFF) == (int(latest) & 0xFFFFFFFF)
    if point.kind in (RegisterKind.COIL, RegisterKind.DISCRETE_INPUT):
        return bool(point.raw) == bool(latest)
    return int(point.raw) == int(latest)


def format_decoded_display(point: RegisterPoint) -> str:
    if point.kind in (RegisterKind.COIL, RegisterKind.DISCRETE_INPUT):
        return f"0x{int(bool(point.raw)):02X}"
    if point.datatype == ValueKind.INT32:
        value = int(point.raw) & 0xFFFFFFFF
        return f"0x{value:08X}"
    value = int(point.raw) & 0xFFFF
    return f"0x{value:04X}"


def parse_decoded_input(value: str, datatype: ValueKind) -> int:
    text = value.strip()
    if not text:
        return 0
    if text.lower().startswith("0x"):
        parsed = int(text, 16)
    elif len(text) > 1 and text[-1].lower() == "h":
        parsed = int(text[:-1], 16)
    else:
        # 0x なしも 16 進として受け付ける（例: 1234 → 0x1234）
        parsed = int(text, 16)

    if datatype == ValueKind.BOOL:
        return 1 if parsed else 0
    if datatype == ValueKind.UINT16:
        return parsed & 0xFFFF
    if datatype == ValueKind.INT16:
        return parsed & 0xFFFF
    # INT32: struct.pack(">i") 向けに符号付きへ正規化（例: FFFFFFFF → -1）
    value32 = parsed & 0xFFFFFFFF
    if value32 >= 0x80000000:
        value32 -= 0x100000000
    return value32


registry = SlaveRegistry()  # 後方互換（TCP と同一）
tcp_registry = registry
rtu_registry = SlaveRegistry()
