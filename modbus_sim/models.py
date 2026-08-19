"""Domain models for slave register points."""

from __future__ import annotations

from dataclasses import dataclass, field

from modbus_sim.config import AutoMode, FaultException, FaultMode, RegisterKind, ValueKind


@dataclass
class RegisterPoint:
    address: int
    kind: RegisterKind = RegisterKind.HOLDING_REGISTER
    datatype: ValueKind = ValueKind.UINT16
    tag: str = ""
    raw: int = 0

    # 異常応答シミュレーション（Holding/Input Register のみ）
    fault_mode: FaultMode = FaultMode.NONE
    fault_exception: FaultException = FaultException.DEVICE_FAILURE

    # 応答遅延（ミリ秒）。max > min ならリクエストごとにこの範囲でランダム抽選。
    delay_min_ms: int = 0
    delay_max_ms: int = 0

    # 値の自動変化（Holding/Input Register のみ）
    auto_mode: AutoMode = AutoMode.NONE
    auto_min: int = 0
    auto_max: int = 0
    auto_step: float = 1.0
    auto_period_sec: float = 1.0

    # 自動変化の内部進行状態。設定値ではないので比較・表示・永続化の対象外。
    auto_phase: float = field(default=0.0, compare=False, repr=False)

    @property
    def key(self) -> tuple[int, RegisterKind]:
        return self.address, self.kind

    def is_empty(self) -> bool:
        return self.tag == "" and self.raw == 0

    def has_advanced_settings(self) -> bool:
        return (
            self.fault_mode != FaultMode.NONE
            or self.delay_max_ms > 0
            or self.auto_mode != AutoMode.NONE
        )


@dataclass
class SlaveDevice:
    slave_id: int
    tag: str = ""


@dataclass
class CommSettings:
    tcp_host: str = ""
    tcp_port: int | None = None
    rtu_port: str = ""
    rtu_baudrate: int | None = None
    rtu_parity: str = ""
    rtu_bytesize: int | None = None
    rtu_stopbits: int | None = None
    configured: set[str] = field(default_factory=set)

    def mark(self, name: str) -> None:
        self.configured.add(name)

    def summary_lines(self) -> list[str]:
        lines: list[str] = []
        if "tcp_host" in self.configured and self.tcp_host:
            lines.append(f"TCP IP: {self.tcp_host}")
        if "tcp_port" in self.configured and self.tcp_port is not None:
            lines.append(f"TCP Port: {self.tcp_port}")
        if "rtu_port" in self.configured and self.rtu_port:
            lines.append(f"RTU Port: {self.rtu_port}")
        if "rtu_baudrate" in self.configured and self.rtu_baudrate is not None:
            lines.append(f"RTU Baud: {self.rtu_baudrate}")
        if "rtu_parity" in self.configured and self.rtu_parity:
            lines.append(f"RTU Parity: {self.rtu_parity}")
        if "rtu_bytesize" in self.configured and self.rtu_bytesize is not None:
            lines.append(f"RTU Data bits: {self.rtu_bytesize}")
        if "rtu_stopbits" in self.configured and self.rtu_stopbits is not None:
            lines.append(f"RTU Stop bits: {self.rtu_stopbits}")
        return lines
