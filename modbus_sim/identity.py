"""機器識別（FC 43 / Read Device Identification）の設定。

pymodbus のサーバ identity はサーバ全体で 1 つ（ユニット別ではない）。
標準 MEI オブジェクト 0x00〜0x06 を保持する。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from pymodbus.pdu.device import ModbusDeviceIdentification

# (attr, MEI object id, ラベル)
_FIELDS = (
    ("vendor_name", 0x00, "VendorName"),
    ("product_code", 0x01, "ProductCode"),
    ("major_minor_revision", 0x02, "MajorMinorRevision"),
    ("vendor_url", 0x03, "VendorUrl"),
    ("product_name", 0x04, "ProductName"),
    ("model_name", 0x05, "ModelName"),
    ("user_application_name", 0x06, "UserApplicationName"),
)


@dataclass
class DeviceIdentity:
    vendor_name: str = "modbus-sim"
    product_code: str = "MBSIM"
    major_minor_revision: str = "0.1"
    vendor_url: str = "https://github.com/miya-taro/modbus-sim"
    product_name: str = "Modbus Simulator"
    model_name: str = "TCP/RTU"
    user_application_name: str = ""

    def to_pymodbus(self) -> ModbusDeviceIdentification:
        ident = ModbusDeviceIdentification()
        for attr, _oid, pm_attr in _FIELDS:
            value = getattr(self, attr)
            if value:
                setattr(ident, pm_attr, value)
        return ident

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> "DeviceIdentity":
        if not isinstance(data, dict):
            return cls()
        kwargs = {}
        for attr, _oid, _pm in _FIELDS:
            val = data.get(attr)
            if isinstance(val, str):
                kwargs[attr] = val
        return cls(**kwargs)
