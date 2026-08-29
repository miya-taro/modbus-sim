"""レジスタ点 / Slave の削除操作に関するテスト（datastore レベル）。

UI 経由の削除メニュー・エラーセル表示・ショートカットのテストは Tauri フロント側
（vitest / Playwright）へ移行。ここではコアの不変条件のみを検証する。
"""

from __future__ import annotations

import pytest

from modbus_sim.config import RegisterKind, ValueKind
from modbus_sim.datastore import SlaveDatastore, SlaveRegistry
from modbus_sim.models import RegisterPoint


class TestSlaveDatastoreRemovePoint:
    def test_remove_point_deletes_and_resets_memory(self) -> None:
        slave = SlaveDatastore(1)
        point = RegisterPoint(
            address=10, kind=RegisterKind.HOLDING_REGISTER, datatype=ValueKind.UINT16, raw=42
        )
        slave.upsert_point(point)
        assert slave.get_point(10, RegisterKind.HOLDING_REGISTER) is not None

        removed = slave.remove_point(10, RegisterKind.HOLDING_REGISTER)
        assert removed is True
        assert slave.get_point(10, RegisterKind.HOLDING_REGISTER) is None
        assert slave.read_raw(RegisterKind.HOLDING_REGISTER, 10) == 0

    def test_remove_point_missing_returns_false(self) -> None:
        slave = SlaveDatastore(1)
        assert slave.remove_point(10, RegisterKind.HOLDING_REGISTER) is False

    def test_remove_point_invalidates_sim_devices(self) -> None:
        reg = SlaveRegistry()
        slave = reg.get_slave(1)
        slave.upsert_point(
            RegisterPoint(address=10, kind=RegisterKind.HOLDING_REGISTER, datatype=ValueKind.UINT16)
        )
        reg.build_sim_devices()
        reg._sim_devices = "sentinel"  # type: ignore[assignment]
        slave.remove_point(10, RegisterKind.HOLDING_REGISTER)
        assert reg._sim_devices is None


class TestSlaveRegistryRemoveSlave:
    def test_remove_slave(self) -> None:
        reg = SlaveRegistry()
        reg.add_slave(2)
        reg.remove_slave(2)
        assert reg.list_slave_ids() == [1]

    def test_remove_last_slave_raises(self) -> None:
        reg = SlaveRegistry()
        with pytest.raises(ValueError):
            reg.remove_slave(1)

    def test_remove_unknown_slave_raises(self) -> None:
        reg = SlaveRegistry()
        with pytest.raises(KeyError):
            reg.remove_slave(99)

    def test_remove_selected_slave_falls_back_to_remaining(self) -> None:
        reg = SlaveRegistry()
        reg.add_slave(2)
        reg.selected_slave_id = 2
        reg.remove_slave(2)
        assert reg.selected_slave_id == 1
