"""Configuration models for Modbus simulator."""

from dataclasses import dataclass
from enum import Enum

from modbus_sim.network import normalize_host


class CommMode(str, Enum):
    TCP = "tcp"
    RTU = "rtu"


class Parity(str, Enum):
    NONE = "None"
    EVEN = "Even"
    ODD = "Odd"

    def to_pyserial(self) -> str:
        return {"None": "N", "Even": "E", "Odd": "O"}[self.value]


class RegisterKind(str, Enum):
    COIL = "coil"
    DISCRETE_INPUT = "di"
    HOLDING_REGISTER = "hr"
    INPUT_REGISTER = "ir"


class ValueKind(str, Enum):
    UINT16 = "uint16"
    INT16 = "int16"
    INT32 = "int32"
    FLOAT32 = "float32"
    FLOAT64 = "float64"
    BOOL = "bool"

    @property
    def register_span(self) -> int:
        """このデータ型が消費するレジスタ数（16bit ワード数）。"""
        if self == ValueKind.FLOAT64:
            return 4
        return 2 if self in (ValueKind.INT32, ValueKind.FLOAT32) else 1

    @property
    def is_float(self) -> bool:
        return self in (ValueKind.FLOAT32, ValueKind.FLOAT64)


class FaultMode(str, Enum):
    """レジスタ単位の異常応答シミュレーション（Holding/Input Register のみ対応）。"""

    NONE = "none"
    EXCEPTION = "exception"
    NO_RESPONSE = "no_response"


class FaultException(str, Enum):
    """FaultMode.EXCEPTION 時に返す Modbus 例外コード。"""

    ILLEGAL_FUNCTION = "illegal_function"
    ILLEGAL_DATA_ADDRESS = "illegal_data_address"
    ILLEGAL_DATA_VALUE = "illegal_data_value"
    DEVICE_FAILURE = "device_failure"
    ACKNOWLEDGE = "acknowledge"
    DEVICE_BUSY = "device_busy"
    NEGATIVE_ACKNOWLEDGE = "negative_acknowledge"
    MEMORY_PARITY_ERROR = "memory_parity_error"
    GATEWAY_PATH_UNAVAILABLE = "gateway_path_unavailable"
    GATEWAY_NO_RESPONSE = "gateway_no_response"


class AutoMode(str, Enum):
    """レジスタ値の自動変化（Holding/Input Register のみ対応）。"""

    NONE = "none"
    INCREMENT = "increment"
    RANDOM_WALK = "random_walk"
    SINE = "sine"


BAUD_RATES = (9600, 19200, 38400, 115200)
# 先頭がデフォルト表示になる（仕様既定: 8 data bits）
DATA_BITS = (8, 7)
STOP_BITS = (1, 2)
REGISTER_COUNT = 65536
ACTIVITY_TIMEOUT_SEC = 3.0
PAGE_SIZE = 20


@dataclass
class TcpConfig:
    host: str = "127.0.0.1"
    port: int = 5020

    def __post_init__(self) -> None:
        self.host = normalize_host(self.host)

    def summary(self) -> str:
        if ":" in self.host and "." not in self.host:
            return f"TCP [{self.host}]:{self.port}"
        return f"TCP {self.host}:{self.port}"


@dataclass
class RtuConfig:
    port: str = "COM1"
    baudrate: int = 9600
    parity: Parity = Parity.EVEN
    bytesize: int = 8
    stopbits: int = 1

    def summary(self) -> str:
        return (
            f"RTU {self.port} @ {self.baudrate}bps "
            f"{self.parity.value} {self.bytesize}N{self.stopbits}"
        )
