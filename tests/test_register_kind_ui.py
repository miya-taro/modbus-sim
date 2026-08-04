"""レジスタ表の Kind 列（Coil / Discrete Input / Holding Register / Input Register）のUIテスト。

PySide6 の QComboBox は str 派生 Enum を userData に入れても currentData() では
素の str として返してくることがあり、isinstance チェックだけに頼ると
コンボ操作が無反応になる（過去に実際踏んだ回帰）。ここでは実際に
QComboBox を操作してデータストアへ反映されることを確認する。
"""

from __future__ import annotations

import sys

import pytest
from PySide6.QtWidgets import QApplication, QComboBox

from modbus_sim.config import RegisterKind, TcpConfig, ValueKind
from modbus_sim.datastore import SlaveRegistry
from modbus_sim.server_manager import ModbusServerManager
from modbus_sim.ui.slave_panel import DATATYPE_COL, KIND_COL, SlavePanel


@pytest.fixture
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication(sys.argv)
    return app


def _row_for_address(panel: SlavePanel, address: int) -> int:
    for row in range(panel.table.rowCount()):
        item = panel.table.item(row, 0)
        if item is not None and item.text() == str(address):
            return row
    raise AssertionError(f"address {address} not found in grid")


def _set_combo_data(combo: QComboBox, data) -> None:
    index = combo.findData(data)
    assert index >= 0, f"{data!r} not found in combo"
    combo.setCurrentIndex(index)


class TestKindColumn:
    def test_new_point_defaults_to_holding_register(self, qapp: QApplication) -> None:
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        panel.table.item(panel.table.rowCount() - 1, 0).setText("50")
        point = reg.get_slave(1).get_point(50, RegisterKind.HOLDING_REGISTER)
        assert point is not None
        assert point.datatype == ValueKind.UINT16

    def test_kind_combo_change_to_coil_forces_bool_datatype(self, qapp: QApplication) -> None:
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        panel.table.item(panel.table.rowCount() - 1, 0).setText("50")
        row = _row_for_address(panel, 50)

        kind_combo = panel.table.cellWidget(row, KIND_COL)
        assert isinstance(kind_combo, QComboBox)
        _set_combo_data(kind_combo, RegisterKind.COIL)

        assert reg.get_slave(1).get_point(50, RegisterKind.HOLDING_REGISTER) is None
        point = reg.get_slave(1).get_point(50, RegisterKind.COIL)
        assert point is not None
        assert point.datatype == ValueKind.BOOL

    def test_kind_combo_back_to_register_resets_datatype(self, qapp: QApplication) -> None:
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        panel.table.item(panel.table.rowCount() - 1, 0).setText("10")
        row = _row_for_address(panel, 10)

        kind_combo = panel.table.cellWidget(row, KIND_COL)
        _set_combo_data(kind_combo, RegisterKind.DISCRETE_INPUT)
        row = _row_for_address(panel, 10)
        kind_combo = panel.table.cellWidget(row, KIND_COL)
        _set_combo_data(kind_combo, RegisterKind.HOLDING_REGISTER)

        point = reg.get_slave(1).get_point(10, RegisterKind.HOLDING_REGISTER)
        assert point is not None
        assert point.datatype == ValueKind.UINT16

    def test_datatype_combo_change_is_committed(self, qapp: QApplication) -> None:
        """回帰: Datatype コンボの変更が実際にデータストアへ反映されること。"""
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        panel.table.item(panel.table.rowCount() - 1, 0).setText("10")
        row = _row_for_address(panel, 10)

        datatype_combo = panel.table.cellWidget(row, DATATYPE_COL)
        assert isinstance(datatype_combo, QComboBox)
        _set_combo_data(datatype_combo, ValueKind.INT32)

        point = reg.get_slave(1).get_point(10, RegisterKind.HOLDING_REGISTER)
        assert point is not None
        assert point.datatype == ValueKind.INT32

    @pytest.mark.asyncio
    async def test_coil_created_via_kind_combo_is_readable_over_tcp(
        self, qapp: QApplication
    ) -> None:
        from pymodbus.client import AsyncModbusTcpClient

        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        panel.table.item(panel.table.rowCount() - 1, 0).setText("50")
        row = _row_for_address(panel, 50)
        kind_combo = panel.table.cellWidget(row, KIND_COL)
        _set_combo_data(kind_combo, RegisterKind.COIL)
        row = _row_for_address(panel, 50)
        panel.table.item(row, 2).setText("1")  # Raw column (after Kind insertion)

        mgr = ModbusServerManager(slave_registry=reg)
        port = 19555
        await mgr.start_tcp(TcpConfig(host="127.0.0.1", port=port))
        try:
            client = AsyncModbusTcpClient("127.0.0.1", port=port)
            assert await client.connect()
            result = await client.read_coils(50, count=1, device_id=1)
            assert not result.isError(), result
            assert result.bits[0] is True
            client.close()
        finally:
            await mgr.stop_tcp()
