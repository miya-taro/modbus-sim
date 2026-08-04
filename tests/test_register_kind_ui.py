"""レジスタ表の Kind タブ（Coil / Discrete Input / Holding / Input）のUIテスト。"""

from __future__ import annotations

import sys

import pytest
from PySide6.QtWidgets import QApplication

from modbus_sim.config import RegisterKind, TcpConfig, ValueKind
from modbus_sim.datastore import SlaveRegistry
from modbus_sim.server_manager import ModbusServerManager
from modbus_sim.ui.slave_panel import ADDR_COL, DATATYPE_COL, RAW_COL, SlavePanel


@pytest.fixture
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication(sys.argv)
    return app


def _row_for_address(panel: SlavePanel, address: int) -> int:
    for row in range(panel.table.rowCount()):
        item = panel.table.item(row, ADDR_COL)
        if item is not None and item.text() == str(address):
            return row
    raise AssertionError(f"address {address} not found in grid")


class TestKindTabs:
    def test_new_point_defaults_to_holding_register(self, qapp: QApplication) -> None:
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        assert panel.active_kind == RegisterKind.HOLDING_REGISTER
        panel.table.item(panel.table.rowCount() - 1, ADDR_COL).setText("50")
        point = reg.get_slave(1).get_point(50, RegisterKind.HOLDING_REGISTER)
        assert point is not None
        assert point.datatype == ValueKind.UINT16

    def test_kind_tab_switch_creates_coil(self, qapp: QApplication) -> None:
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        panel.set_active_kind(RegisterKind.COIL)
        panel.table.item(panel.table.rowCount() - 1, ADDR_COL).setText("50")

        assert reg.get_slave(1).get_point(50, RegisterKind.HOLDING_REGISTER) is None
        point = reg.get_slave(1).get_point(50, RegisterKind.COIL)
        assert point is not None
        assert point.datatype == ValueKind.BOOL

    def test_kind_tabs_isolate_points(self, qapp: QApplication) -> None:
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        panel.table.item(panel.table.rowCount() - 1, ADDR_COL).setText("10")
        panel.set_active_kind(RegisterKind.DISCRETE_INPUT)
        panel.table.item(panel.table.rowCount() - 1, ADDR_COL).setText("10")

        assert reg.get_slave(1).get_point(10, RegisterKind.HOLDING_REGISTER) is not None
        assert reg.get_slave(1).get_point(10, RegisterKind.DISCRETE_INPUT) is not None
        panel.set_active_kind(RegisterKind.HOLDING_REGISTER)
        assert _row_for_address(panel, 10) >= 0
        panel.set_active_kind(RegisterKind.COIL)
        with pytest.raises(AssertionError):
            _row_for_address(panel, 10)

    def test_datatype_cell_change_is_committed(self, qapp: QApplication) -> None:
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        panel.table.item(panel.table.rowCount() - 1, ADDR_COL).setText("10")
        row = _row_for_address(panel, 10)

        assert panel.table.cellWidget(row, DATATYPE_COL) is None
        panel.table.item(row, DATATYPE_COL).setText("int32")

        point = reg.get_slave(1).get_point(10, RegisterKind.HOLDING_REGISTER)
        assert point is not None
        assert point.datatype == ValueKind.INT32

    def test_datatype_uses_delegate_not_permanent_combo(self, qapp: QApplication) -> None:
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        panel.table.item(panel.table.rowCount() - 1, ADDR_COL).setText("10")
        row = _row_for_address(panel, 10)
        assert panel.table.cellWidget(row, DATATYPE_COL) is None
        assert panel.table.item(row, DATATYPE_COL).text() == "uint16"

    def test_raw_edit_still_works_after_datatype_change(self, qapp: QApplication) -> None:
        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        panel.table.item(panel.table.rowCount() - 1, ADDR_COL).setText("10")
        row = _row_for_address(panel, 10)
        panel.table.item(row, DATATYPE_COL).setText("int16")
        panel.table.item(row, RAW_COL).setText("-1")

        point = reg.get_slave(1).get_point(10, RegisterKind.HOLDING_REGISTER)
        assert point is not None
        assert point.datatype == ValueKind.INT16
        assert point.raw == -1

    def test_table_has_no_kind_column(self, qapp: QApplication) -> None:
        panel = SlavePanel(slave_registry=SlaveRegistry())
        headers = [
            panel.table.horizontalHeaderItem(i).text()
            for i in range(panel.table.columnCount())
        ]
        assert "Kind" not in headers
        assert headers == ["Addr", "Raw", "Decoded", "Datatype", "Tag"]

    @pytest.mark.asyncio
    async def test_coil_created_via_kind_tab_is_readable_over_tcp(
        self, qapp: QApplication
    ) -> None:
        from pymodbus.client import AsyncModbusTcpClient

        reg = SlaveRegistry()
        panel = SlavePanel(slave_registry=reg)
        panel.set_active_kind(RegisterKind.COIL)
        panel.table.item(panel.table.rowCount() - 1, ADDR_COL).setText("50")
        row = _row_for_address(panel, 50)
        panel.table.item(row, RAW_COL).setText("1")

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
